import { describe, expect, it } from 'vitest';

import { anglePresetCamera, facingOf, framingDistance } from './anglePresets';
import { verticalFov } from './stageMath';

const solo = [{ name: '林夏', position: [2, 1] as [number, number], yaw_deg: 90, height_m: 1.7 }];
const pair = [
  { name: '林夏', position: [-1.3, 0] as [number, number], yaw_deg: 90, height_m: 1.7 },
  { name: '周教授', position: [1.3, 0] as [number, number], yaw_deg: -90, height_m: 1.8 },
];
const ASPECT = 9 / 16;

describe('framingDistance', () => {
  it('solves the film-back equation', () => {
    // 1.7 m filling 80 % of a 90° frame: half the visible height equals the distance.
    expect(framingDistance(1.7, 90, 0.8)).toBeCloseTo(1.7 / 0.8 / 2, 6);
    expect(verticalFov(18, 16 / 9)).toBeCloseTo(58.7, 1);
    expect(verticalFov(18, 9 / 16)).toBeCloseTo(90, 6);
  });
});

describe('facingOf', () => {
  it('follows a lone subject and picks the master side for a face-to-face pair', () => {
    expect(facingOf(solo)[0]).toBeCloseTo(1, 6);
    expect(facingOf(pair)).toEqual([-0, 1]);
  });
});

describe('anglePresetCamera', () => {
  it('stands in front of the subject, level, far enough to hold the whole body', () => {
    const camera = anglePresetCamera('front', solo, ASPECT)!;
    expect(camera.label).toBe('正面');
    expect(camera.target).toEqual([2, 0.85, 1]);
    expect(camera.position[1]).toBe(0.85);
    expect(camera.position[2]).toBeCloseTo(1, 2);
    const distance = camera.position[0] - 2;
    // In a 9:16 frame a metre of elbow room is the tighter constraint than 1.7 m of height.
    expect(distance).toBeCloseTo(framingDistance(1 / ASPECT, verticalFov(35, ASPECT)), 1);
    const wide = anglePresetCamera('front', solo, 16 / 9)!;
    expect(wide.position[0] - 2).toBeCloseTo(framingDistance(1.7, verticalFov(35, 16 / 9)), 1);
  });

  it('goes square to the facing for a profile', () => {
    const camera = anglePresetCamera('side', solo, ASPECT)!;
    expect(camera.position[0]).toBeCloseTo(2, 2);
    expect(Math.abs(camera.position[2] - 1)).toBeGreaterThan(1);
  });

  it('pulls back until a wide pair fits the narrow frame', () => {
    const one = anglePresetCamera('front', [pair[0]], ASPECT)!;
    const two = anglePresetCamera('front', pair, ASPECT)!;
    expect(two.target[0]).toBe(0);
    expect(two.position[2]).toBeGreaterThan(Math.hypot(one.position[0] - one.target[0], one.position[2] - one.target[2]));
  });

  it('shoots past the near shoulder at the far face', () => {
    const camera = anglePresetCamera('over_shoulder', pair, ASPECT)!;
    expect(camera.target).toEqual([-1.3, 1.5, 0]);
    expect(camera.position[0]).toBeGreaterThan(1.3);            // behind 周教授, away from 林夏
    expect(Math.abs(camera.position[2])).toBeCloseTo(0.45, 2);  // off to one side of the axis
    expect(camera.position[1]).toBeCloseTo(1.66, 2);
  });

  it('borrows the nearest bystander for a single, or settles for a three-quarter front', () => {
    const bystander = { name: '助手', position: [2, 3] as [number, number], yaw_deg: 0, height_m: 1.7 };
    expect(anglePresetCamera('over_shoulder', solo, ASPECT, [bystander])!.position[2]).toBeGreaterThan(3);
    const alone = anglePresetCamera('over_shoulder', solo, ASPECT)!;
    expect(alone.position[0]).toBeGreaterThan(2);
    expect(alone.position[2]).not.toBeCloseTo(1, 1);
  });

  it('looks down from above and up from the floor', () => {
    const high = anglePresetCamera('high', solo, ASPECT)!;
    const low = anglePresetCamera('low', solo, ASPECT)!;
    expect(high.position[1]).toBeGreaterThan(high.target[1] + 1);
    expect(low.position[1]).toBe(0.35);
    expect(low.target[1]).toBeGreaterThan(1.4);
  });

  it('moves in on the face for a close-up', () => {
    const close = anglePresetCamera('close_up', pair, ASPECT)!;
    const reach = Math.hypot(close.position[0] - close.target[0], close.position[2] - close.target[2]);
    expect(close.lens_mm).toBe(85);
    expect(close.target).toEqual([-1.3, 1.53, 0]);
    expect(reach).toBeGreaterThan(0.6);
    expect(reach).toBeLessThan(2.5);
  });

  it('has nothing to offer an empty shot, and never puts the lens on its target', () => {
    expect(anglePresetCamera('front', [], ASPECT)).toBeNull();
    (['front', 'side', 'over_shoulder', 'high', 'low', 'close_up'] as const).forEach(id => {
      const camera = anglePresetCamera(id, pair, 16 / 9)!;
      expect(Math.hypot(...camera.position.map((value, index) => value - camera.target[index]))).toBeGreaterThan(0.5);
      expect(camera.position[1]).toBeGreaterThanOrEqual(0.25);
    });
  });
});
