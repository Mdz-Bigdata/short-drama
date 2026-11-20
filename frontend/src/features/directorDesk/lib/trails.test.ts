import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { ActorKey, CameraKey, SpacePoint, StagePlan } from '../../spatial/spatialTypes';
import { ghostKeys, keyStamp, pulseTime, shotTrails, trailArrows, trailLength, trailSpot, type TrailKey } from './trails';

const CAMERA_KEYS: CameraKey[] = [
  { time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
  { time: 4, position: [0, 1.5, 1], target: [0, 1, 0], lens_mm: 56, easing: 'linear' },
];

function timed(camera: CameraKey[], actors: Record<string, ActorKey[]> = {}): StagePlan {
  return { ...PLAN, timelines: { '1': { duration_s: 4, fps: 24, camera, actors } } };
}

describe('shotTrails', () => {
  it('gives the filming lens a route with the time it is at each point, and its keys with where they look', () => {
    const plan = timed(CAMERA_KEYS);
    const [trail] = shotTrails(plan, plan.shots[0], 4);
    expect(trail).toMatchObject({ key: 'camera:cam-01', kind: 'camera', owner: 'cam-01', durationS: 4, times: [0, 1, 2, 3, 4] });
    expect(trail.points).toEqual([[0, 1.5, 5], [0, 1.5, 4], [0, 1.5, 3], [0, 1.5, 2], [0, 1.5, 1]]);
    expect(trail.keys).toEqual([
      { time: 0, position: [0, 1.5, 5], target: [0, 1, 0] },
      { time: 4, position: [0, 1.5, 1], target: [0, 1, 0] },
    ]);
  });

  it('reads a planner move as a route too, and gives a lens that stays put none', () => {
    // cam-02 pushes from its position to move.end_position over the default five seconds.
    expect(shotTrails(PLAN, PLAN.shots[1]).map(trail => [trail.key, trail.keys.map(key => key.time)])).toEqual([['camera:cam-02', [0, 5]]]);
    expect(shotTrails(PLAN, PLAN.shots[0])).toEqual([]);
    expect(shotTrails(PLAN, undefined)).toEqual([]);
  });

  it('draws an actor route on the ground through its placed keys, keeping each key as a corner', () => {
    const plan = timed([], {
      林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 1, yaw_deg: 45, easing: 'smooth' }, { time: 1.5, position: [0.7, 0], easing: 'linear' }, { time: 4, position: [0.7, 2], easing: 'linear' }],
      // Sits down where it stands: one placed key is not a route.
      助手: [{ time: 0, position: [0, -2], easing: 'linear' }, { time: 2, pose: { preset: 'sit' }, easing: 'linear' }],
    });
    const trails = shotTrails(plan, plan.shots[0], 4);
    expect(trails.map(trail => trail.key)).toEqual(['actor:林夏']);
    const [walk] = trails;
    // The key at 1.5 s falls between two even samples and is sampled anyway.
    expect(walk.times).toEqual([0, 1, 1.5, 2, 3, 4]);
    expect(walk.points[2]).toEqual([0.7, 0, 0]);
    expect(walk.points.every(point => point[1] === 0)).toBe(true);
    expect(walk.keys).toEqual([{ time: 0, position: [-1.3, 0, 0] }, { time: 1.5, position: [0.7, 0, 0] }, { time: 4, position: [0.7, 0, 2] }]);
  });

  it('follows the easing of a leg: a held key keeps the figure back until the moment it is reached', () => {
    const plan = timed([], { 林夏: [{ time: 0, position: [0, 0], easing: 'linear' }, { time: 4, position: [4, 0], easing: 'hold' }] });
    const [walk] = shotTrails(plan, plan.shots[0], 4);
    expect(walk.points.map(point => point[0])).toEqual([0, 0, 0, 0, 4]);
  });

  it('leaves out someone who is not in the shot', () => {
    const plan = timed([], { 不在场的人: [{ time: 0, position: [0, 0], easing: 'linear' }, { time: 4, position: [2, 0], easing: 'linear' }] });
    expect(shotTrails(plan, plan.shots[0])).toEqual([]);
  });
});

const ROUTE = { points: [[0, 0, 0], [2, 0, 0], [2, 0, 2]] as SpacePoint[], times: [0, 1, 3] };

describe('trailSpot', () => {
  it('finds the traveller between two samples and counts the legs behind it', () => {
    expect(trailSpot(ROUTE, 0.5)).toEqual({ position: [1, 0, 0], legs: 0 });
    expect(trailSpot(ROUTE, 1)).toEqual({ position: [2, 0, 0], legs: 1 });
    expect(trailSpot(ROUTE, 2)).toEqual({ position: [2, 0, 1], legs: 1 });
  });

  it('holds at either end', () => {
    expect(trailSpot(ROUTE, -1)).toEqual({ position: [0, 0, 0], legs: 0 });
    expect(trailSpot(ROUTE, 0)).toEqual({ position: [0, 0, 0], legs: 0 });
    expect(trailSpot(ROUTE, 3)).toEqual({ position: [2, 0, 2], legs: 2 });
    expect(trailSpot(ROUTE, 99)).toEqual({ position: [2, 0, 2], legs: 2 });
    expect(trailSpot({ points: [], times: [] }, 1)).toEqual({ position: [0, 0, 0], legs: 0 });
  });
});

describe('trailArrows', () => {
  it('spaces arrowheads along the route by distance, each pointing the way it runs', () => {
    expect(trailLength(ROUTE.points)).toBe(4);
    const arrows = trailArrows(ROUTE.points, 2);
    expect(arrows).toEqual([
      { position: [1, 0, 0], direction: [1, 0, 0] },
      { position: [2, 0, 1], direction: [0, 0, 1] },
    ]);
  });

  it('caps the count on a long route and gives a route that goes nowhere none', () => {
    const long: SpacePoint[] = [[0, 0, 0], [100, 0, 0]];
    expect(trailArrows(long, 1.2, 14)).toHaveLength(14);
    expect(trailArrows([[0, 0, 0], [0.1, 0, 0]])).toEqual([]);
    expect(trailArrows([[1, 0, 1], [1, 0, 1]])).toEqual([]);
    expect(trailArrows([])).toEqual([]);
  });
});

describe('pulseTime', () => {
  it('runs the route at the pace of the shot, rests, and sets off again', () => {
    expect(pulseTime(0, 4, 1)).toBe(0);
    expect(pulseTime(3.5, 4, 1)).toBe(3.5);
    expect(pulseTime(4.5, 4, 1)).toBeNull();
    expect(pulseTime(5, 4, 1)).toBe(0);
    expect(pulseTime(12.25, 4, 1)).toBeCloseTo(2.25);
  });

  it('shows nothing for a shot without a length', () => {
    expect(pulseTime(1, 0)).toBeNull();
    expect(pulseTime(Number.NaN, 4)).toBeNull();
  });
});

describe('ghostKeys', () => {
  const key = (time: number): TrailKey => ({ time, position: [time, 1.5, 0], target: [time, 1, 3] });

  it('keeps every key of a short route, and the two ends plus an even spread of a long one', () => {
    expect(ghostKeys([key(0), key(1), key(2)]).map(item => item.time)).toEqual([0, 1, 2]);
    const drawn = Array.from({ length: 15 }, (_, index) => key(index));
    expect(ghostKeys(drawn).map(item => item.time)).toEqual([0, 4, 7, 11, 14]);
  });

  it('skips a key that does not say where it looks', () => {
    expect(ghostKeys([{ time: 0, position: [0, 0, 0] }, key(1)]).map(item => item.time)).toEqual([1]);
  });
});

describe('keyStamp', () => {
  it('reads to a tenth of a second', () => {
    expect([0, 1.25, 4].map(keyStamp)).toEqual(['0.0s', '1.3s', '4.0s']);
  });
});
