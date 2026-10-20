import { describe, expect, it } from 'vitest';

import { cameraCone, floorBounds, floorTransform, forwardOf, horizontalFov, isOverhead, parseAspect, yawToward } from './floorPlanGeometry';
import { PLAN } from './spatialFixtures';
import { actorsInShot } from './spatialTypes';

describe('floor plan geometry', () => {
  it('uses the backend convention: yaw 0 faces +Z and yaw 90 faces +X', () => {
    expect(forwardOf(0)[1]).toBeCloseTo(1);
    expect(forwardOf(90)[0]).toBeCloseTo(1);
    expect(yawToward([0, 0], [1, 0])).toBeCloseTo(90);
    expect(yawToward([0, 0], [0, -1])).toBeCloseTo(180);
  });

  it('draws the camera side at the bottom, so the left of the drawing is screen left', () => {
    const transform = floorTransform(floorBounds(PLAN), 720, 540);
    const [linX] = transform.toView(PLAN.actors[0].position);
    const [zhouX] = transform.toView(PLAN.actors[1].position);
    const [, cameraY] = transform.toView([PLAN.cameras[0].position[0], PLAN.cameras[0].position[2]]);
    const [, actorY] = transform.toView(PLAN.actors[0].position);

    expect(linX).toBeLessThan(zhouX);
    expect(cameraY).toBeGreaterThan(actorY);
  });

  it('round-trips a point through the view and keeps a lone mark at a sane zoom', () => {
    const transform = floorTransform(floorBounds(PLAN), 720, 540);
    const [x, y] = transform.toView([1.25, -0.5]);
    expect(transform.toWorld(x, y)).toEqual([1.25, -0.5]);

    const lone = floorBounds({ ...PLAN, actors: [PLAN.actors[0]], landmarks: [], cameras: [] });
    expect(lone.maxX - lone.minX).toBeGreaterThanOrEqual(6);
  });

  it('opens the camera cone by the horizontal field of view of the delivery frame', () => {
    expect(parseAspect('9:16')).toBeCloseTo(0.5625);
    expect(parseAspect('oops')).toBeCloseTo(0.5625);
    const camera = PLAN.cameras[0];
    expect(horizontalFov(camera)).toBeLessThan(camera.fov_deg);   // a portrait frame is narrower than it is tall

    const cone = cameraCone(camera);
    expect(cone).toHaveLength(3);
    expect(cone[0]).toEqual([0, 5.2]);
    expect(cone[1][1]).toBeLessThan(5.2);                          // it opens toward the actors, away from the lens
    expect(cameraCone(PLAN.cameras[1], undefined, true)[0]).toEqual([-0.2, 0.65]);
  });

  it('knows an overhead lens and draws no cone for it', () => {
    const overhead = { ...PLAN.cameras[0], position: [0, 8, 0.01] as [number, number, number], target: [0, 1, 0] as [number, number, number] };
    expect(isOverhead(overhead)).toBe(true);
    expect(isOverhead(PLAN.cameras[0])).toBe(false);
    expect(cameraCone(overhead)).toEqual([]);
  });

  it('stages a shot with its overrides: whoever is offstage is not drawn', () => {
    expect(actorsInShot(PLAN, PLAN.shots[0]).map(actor => actor.name)).toEqual(['林夏', '周教授', '助手']);
    expect(actorsInShot(PLAN, PLAN.shots[1]).map(actor => actor.name)).toEqual(['林夏', '周教授']);
    const moved = { ...PLAN.shots[0], overrides: [{ name: '林夏', position: [-3, 0] as [number, number], posture: 'walk' as const }] };
    expect(actorsInShot(PLAN, moved)[0]).toMatchObject({ position: [-3, 0], posture: 'walk', yaw_deg: 90 });
  });
});
