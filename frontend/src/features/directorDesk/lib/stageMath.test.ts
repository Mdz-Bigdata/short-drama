import { DirectionalLight, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StageActor, StageLandmark, StagePlan } from '../../spatial/spatialTypes';
import { sampleShot, stagePlanAt } from './sampling';
import { lightReach, paneReach, shadowRig, stageReach, type ShadowRig } from './stageMath';

/** The key light's shadow camera as the stage sets it up: aimed at the rig's target, its shadow box read again. */
function shadowCamera(rig: ShadowRig) {
  const light = new DirectionalLight();
  light.position.set(...rig.position);
  light.target.position.set(...rig.target);
  light.updateMatrixWorld();
  light.target.updateMatrixWorld();
  Object.assign(light.shadow.camera, { left: -rig.span, right: rig.span, top: rig.span, bottom: -rig.span, near: 0.5, far: rig.far });
  light.shadow.camera.updateProjectionMatrix();
  light.shadow.updateMatrices(light);
  return light.shadow.camera;
}

function inShadowBox(rig: ShadowRig, point: [number, number, number]): boolean {
  const seen = new Vector3(...point).project(shadowCamera(rig));
  return Math.max(Math.abs(seen.x), Math.abs(seen.y), Math.abs(seen.z)) <= 1;
}

const actorAt = (x: number, z: number) => ({ position: [x, z] }) as StageActor;
const pieceAt = (x: number, z: number, size: [number, number, number]) => ({ position: [x, z], size }) as StageLandmark;

describe('shadowRig', () => {
  it('covers the default stage from the origin', () => {
    expect(shadowRig(6)).toEqual({ span: 12, position: [12 * 0.55, 12 * 0.9, 12 * 0.4], target: [0, 0, 0], far: 48 });
  });

  it('follows a set built away from the origin', () => {
    const rig = shadowRig(6, [40.2, -17.6]);
    expect(rig.target).toEqual([40, 0, -18]);
    // The light keeps its direction: the same offset from wherever it aims.
    expect(rig.position[0] - rig.target[0]).toBeCloseTo(12 * 0.55, 6);
    expect(rig.position[1]).toBeCloseTo(12 * 0.9, 6);
    expect(rig.position[2] - rig.target[2]).toBeCloseTo(12 * 0.4, 6);
  });

  it('grows with the set, and reaches past it', () => {
    const { center, radius } = stageReach({ actors: [], landmarks: [{ id: 'm', name: '街道', kind: 'architecture', position: [0, 0], size: [80, 12, 6] }] });
    const rig = shadowRig(radius, center);
    expect(rig.span).toBeGreaterThan(radius * 1.3);
    // The far plane has to pass the whole set seen from the light, which stands about 1.13 spans away.
    expect(rig.far).toBeGreaterThan(rig.span * 2.2);
  });

  it('holds every corner of a set far from the origin inside the shadow box', () => {
    const center: [number, number] = [40.4, -17.6];
    const radius = 22;
    const rig = shadowRig(radius, center);
    for (let step = 0; step < 8; step += 1) {
      const angle = (step * Math.PI) / 4;
      // On the floor at the rim, and the top of a 3 m wall standing there.
      for (const height of [0, 3]) {
        expect(inShadowBox(rig, [center[0] + Math.cos(angle) * radius, height, center[1] + Math.sin(angle) * radius])).toBe(true);
      }
    }
  });

  it('keeps the cast in the shadow box wherever it stands next to the set', () => {
    // What the canvases hand the light: the set pieces and the shot's cast together.
    const stagings = [
      { landmarks: [pieceAt(0, -20, [6, 1, 5])], actors: [actorAt(0, 0), actorAt(-1.5, 1), actorAt(2, 2)] },
      { landmarks: [pieceAt(9, 9, [0.4, 0.4, 3])], actors: [actorAt(-4, -4), actorAt(0, 0)] },
      { landmarks: [pieceAt(0, 0, [3, 3, 2])], actors: [actorAt(18, 0), actorAt(0, -18)] },
      { landmarks: [], actors: [actorAt(20, 15), actorAt(22, 16)] },
    ];
    for (const staging of stagings) {
      const { center, radius } = stageReach(staging);
      const rig = shadowRig(radius, center);
      for (const actor of staging.actors) {
        // Feet and the top of the head.
        for (const height of [0, 1.9]) expect(inShadowBox(rig, [actor.position[0], height, actor.position[1]])).toBe(true);
      }
    }
  });

  it('does not re-aim for a move of a few centimetres', () => {
    expect(shadowRig(9.02, [3.1, 3.1])).toEqual(shadowRig(9.11, [3.3, 2.8]));
  });
});

describe('paneReach', () => {
  it('takes in a cast standing on a set with no pieces', () => {
    const bare: StagePlan = { ...PLAN, landmarks: [], actors: PLAN.actors.map(actor => ({ ...actor, position: [actor.position[0] + 20, actor.position[1] + 10] as [number, number] })) };
    const { center, radius } = paneReach(bare, 1, []);
    for (const actor of bare.actors) {
      expect(Math.hypot(actor.position[0] - center[0], actor.position[1] - center[1])).toBeLessThan(radius);
    }
  });

  it('takes in a cast standing well away from the set', () => {
    const apart: StagePlan = { ...PLAN, actors: PLAN.actors.map(actor => ({ ...actor, position: [actor.position[0] + 15, actor.position[1]] as [number, number] })) };
    const { center, radius } = paneReach(apart, 1, []);
    for (const point of [...apart.actors.map(actor => actor.position), apart.landmarks[0].position]) {
      expect(Math.hypot(point[0] - center[0], point[1] - center[1])).toBeLessThan(radius);
    }
  });

  it('reads the shot\'s re-marks and leaves out who is offstage or hidden', () => {
    const plan: StagePlan = {
      ...PLAN, landmarks: [],
      shots: PLAN.shots.map(shot => (shot.shot_id !== 2 ? shot : { ...shot, overrides: [...shot.overrides, { name: '林夏', position: [-9, 0] as [number, number] }] })),
    };
    // Shot 2 moves 林夏 to x = -9 and sends 助手 off; 周教授 is hidden in the outliner.
    expect(paneReach(plan, 2, ['actor:周教授'])).toEqual(stageReach({ actors: [{ ...PLAN.actors[0], position: [-9, 0] }], landmarks: [] }));
  });

  it('holds still while a shot plays', () => {
    const keyed: StagePlan = {
      ...PLAN,
      timelines: {
        '1': { duration_s: 4, fps: 24, camera: [], actors: { 林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 4, position: [-12, 6], easing: 'linear' }] } },
      },
    };
    // Only worth asserting if the playhead really moves her.
    expect(sampleShot(keyed, keyed.shots[0], 4).actors['林夏']?.position[0]).toBeLessThan(-10);
    expect(paneReach(stagePlanAt(keyed, 1, 4), 1, [])).not.toEqual(paneReach(keyed, 1, []));
    // The plan as stored frames her on her mark, wherever the playhead is.
    expect(paneReach(keyed, 1, [])).toEqual(paneReach(PLAN, 1, []));
  });
});

describe('lightReach', () => {
  const keyed: StagePlan = {
    ...PLAN,
    timelines: {
      '1': { duration_s: 4, fps: 24, camera: [], actors: { 林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 4, position: [-12, 6], easing: 'linear' }] } },
    },
  };
  const castAt = (seconds: number) => stagePlanAt(keyed, 1, seconds).actors;

  it('stays the same at every frame of a walk, so the shadows do not step', () => {
    const start = lightReach(keyed, 1, castAt(0));
    for (let frame = 0; frame <= 96; frame += 1) {
      expect(lightReach(keyed, 1, castAt(frame / 24))).toEqual(start);
    }
    // Without the keys the reach follows her and moves.
    expect(stageReach({ actors: castAt(4), landmarks: keyed.landmarks })).not.toEqual(stageReach({ actors: castAt(0), landmarks: keyed.landmarks }));
  });

  it('covers where the keys take someone, and is the plain reach for a shot with no keys', () => {
    const { center, radius } = lightReach(keyed, 1, castAt(0));
    expect(Math.hypot(-12 - center[0], 6 - center[1])).toBeLessThan(radius);
    expect(lightReach(keyed, 2, keyed.actors)).toEqual(stageReach({ actors: keyed.actors, landmarks: keyed.landmarks }));
  });
});
