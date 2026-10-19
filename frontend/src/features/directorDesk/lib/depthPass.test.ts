// @vitest-environment jsdom
import { Mesh, PerspectiveCamera, Scene, ShaderMaterial, Vector2, type WebGLRenderer } from 'three';
import { describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StageCamera, StagePlan } from '../../spatial/spatialTypes';
import { HELPER_FLAG, enterDeliveryRender, enterDepthView } from './capture';
import { BACKDROP_FLAG, DEPTH_FALLBACK_RANGE, createDepthMaterial, depthRange, hiddenInDepth } from './depthPass';

// A lens at eye height looking straight down -Z: a subject at z is exactly 5 - z metres deep.
const LENS: StageCamera = { ...PLAN.cameras[0], position: [0, 1, 5], target: [0, 1, 0] };

function plan(patch: Partial<StagePlan>): StagePlan {
  return { ...PLAN, landmarks: [], ...patch };
}

describe('depthRange', () => {
  it('spans the nearest to the farthest subject in front of the lens, padded a metre each side', () => {
    const stage = plan({
      actors: [
        { ...PLAN.actors[0], position: [0, 0] },   // 5 m
        { ...PLAN.actors[1], position: [1, -3] },  // 8 m
      ],
      landmarks: [{ ...PLAN.landmarks[0], position: [0, -6], size: [1, 1, 1] }], // 11 m
    });
    expect(depthRange(stage, LENS)).toEqual({ near: 4, far: 12 });
  });

  it('measures along the lens axis, not to the lens point, and counts heads as well as feet', () => {
    const tilted: StageCamera = { ...LENS, position: [0, 5, 5], target: [0, 0, 0] };
    // One actor straight ahead at the origin: the feet are the far point, the head the near one.
    const stage = plan({ actors: [{ ...PLAN.actors[0], position: [0, 0], height_m: 2 }] });
    const range = depthRange(stage, tilted);
    const unit = Math.SQRT1_2;
    expect(range.far).toBeCloseTo(10 * unit + 1, 6);
    expect(range.near).toBeCloseTo(((0 - 5) * -unit + (2 - 5) * -unit) - 1, 6);
  });

  it('keeps a single subject on a gradient at least two metres deep, and never starts behind the lens', () => {
    const one = plan({ actors: [{ ...PLAN.actors[0], position: [0, 0], height_m: 1.7 }] });
    expect(depthRange(one, LENS)).toEqual({ near: 4, far: 6 });
    const close = plan({ actors: [{ ...PLAN.actors[0], position: [0, 4.7], height_m: 1.7 }] });
    expect(depthRange(close, LENS)).toEqual({ near: 0, far: 2 });
  });

  it('falls back to 1–20 m without a lens, with an aimless lens, or with everything behind it', () => {
    expect(depthRange(PLAN, undefined)).toEqual(DEPTH_FALLBACK_RANGE);
    expect(depthRange(PLAN, { ...LENS, target: LENS.position })).toEqual(DEPTH_FALLBACK_RANGE);
    const behind = plan({ actors: [{ ...PLAN.actors[0], position: [0, 9] }] });
    expect(depthRange(behind, LENS)).toEqual(DEPTH_FALLBACK_RANGE);
    expect(depthRange(plan({ actors: [] }), LENS)).toEqual(DEPTH_FALLBACK_RANGE);
  });

  it('reads the shot: an actor sent offstage does not stretch the range', () => {
    const stage = plan({
      actors: [
        { ...PLAN.actors[0], position: [0, 0] },
        { ...PLAN.actors[2], name: '助手', position: [0, -30] },
      ],
    });
    const shot = { ...PLAN.shots[0], overrides: [{ name: '助手', offstage: true }] };
    expect(depthRange(stage, LENS, shot).far).toBe(6);
    expect(depthRange(stage, LENS).far).toBe(36);
  });
});

describe('createDepthMaterial', () => {
  it('is an unlit shader that maps the range to white→black and can be inverted', () => {
    const material = createDepthMaterial({ range: { near: 2, far: 9 } });
    expect(material).toBeInstanceOf(ShaderMaterial);
    expect(material.lights).toBe(false);
    expect(material.uniforms.nearM.value).toBe(2);
    expect(material.uniforms.farM.value).toBe(9);
    expect(material.uniforms.invert.value).toBe(0);
    expect(createDepthMaterial({ range: { near: 2, far: 9 }, invert: true }).uniforms.invert.value).toBe(1);
  });

  it('keeps a skinned humanoid deforming under the override', () => {
    const { vertexShader } = createDepthMaterial({ range: DEPTH_FALLBACK_RANGE });
    ['skinning_pars_vertex', 'skinbase_vertex', 'skinning_vertex', 'project_vertex'].forEach(chunk => expect(vertexShader).toContain(`#include <${chunk}>`));
  });
});

describe('a depth delivery render', () => {
  function fakeRenderer() {
    const size = new Vector2(300, 533);
    return {
      domElement: document.createElement('canvas'),
      getPixelRatio: () => 1, setPixelRatio: vi.fn(),
      getSize: (target: Vector2) => target.copy(size), setSize: vi.fn(),
      render: vi.fn(),
    } as unknown as WebGLRenderer;
  }

  it('draws with the depth material, drops the backdrop even when it is asked into captures, then puts everything back', () => {
    const scene = new Scene();
    const backdrop = new Mesh();
    backdrop.userData[BACKDROP_FLAG] = true;
    const helper = new Mesh();
    helper.userData[HELPER_FLAG] = true;
    const figure = new Mesh();
    scene.add(backdrop, helper, figure);
    expect(hiddenInDepth(backdrop)).toBe(true);
    expect(hiddenInDepth(figure)).toBe(false);

    const delivery = enterDeliveryRender({ gl: fakeRenderer(), scene, camera: new PerspectiveCamera(), width: 720, height: 1280, monochrome: true, depth: { range: { near: 1, far: 9 } } });
    expect(scene.overrideMaterial).toBeInstanceOf(ShaderMaterial);
    expect((scene.overrideMaterial as ShaderMaterial).uniforms.farM.value).toBe(9);
    expect([backdrop.visible, helper.visible, figure.visible]).toEqual([false, false, true]);

    delivery.restore();
    expect(scene.overrideMaterial).toBeNull();
    expect([backdrop.visible, helper.visible, figure.visible]).toEqual([true, true, true]);
  });

  it('previews live the same way, hiding helpers that arrive later, and a capture taken meanwhile restores to the preview', () => {
    const scene = new Scene();
    const backdrop = new Mesh();
    backdrop.userData[BACKDROP_FLAG] = true;
    scene.add(backdrop);
    const preview = enterDepthView(scene, { range: { near: 1, far: 9 } });
    const previewMaterial = scene.overrideMaterial;
    expect(previewMaterial).toBeInstanceOf(ShaderMaterial);
    expect(backdrop.visible).toBe(false);

    const late = new Mesh();
    late.userData[HELPER_FLAG] = true;
    scene.add(late);
    preview.hide();
    expect(late.visible).toBe(false);

    // An ordinary still while the preview is on is not a depth picture, and the preview comes back after it.
    const delivery = enterDeliveryRender({ gl: fakeRenderer(), scene, camera: new PerspectiveCamera(), width: 720, height: 1280, monochrome: false });
    expect(scene.overrideMaterial).toBeNull();
    delivery.restore();
    expect(scene.overrideMaterial).toBe(previewMaterial);
    expect([backdrop.visible, late.visible]).toEqual([false, false]);

    preview.restore();
    expect(scene.overrideMaterial).toBeNull();
    expect([backdrop.visible, late.visible]).toEqual([true, true]);
  });

  it('leaves the backdrop in an ordinary capture that asked for it', () => {
    const scene = new Scene();
    const backdrop = new Mesh();
    backdrop.userData[BACKDROP_FLAG] = true;
    scene.add(backdrop);
    const delivery = enterDeliveryRender({ gl: fakeRenderer(), scene, camera: new PerspectiveCamera(), width: 720, height: 1280, monochrome: false });
    expect(backdrop.visible).toBe(true);
    expect(scene.overrideMaterial).toBeNull();
    delivery.restore();
  });
});
