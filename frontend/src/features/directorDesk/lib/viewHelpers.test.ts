import { describe, expect, it } from 'vitest';

import { fitDistance, focusPose, frustumReach, gridCells, lensLabel, metresPerPixel, screenLift, screenScale, wholeSetPose } from './viewHelpers';

describe('screenScale', () => {
  it('measures a pixel in metres at a distance', () => {
    // 90° lens, 10 m away: the view is 20 m tall there, drawn over 1000 px.
    expect(metresPerPixel(10, 90, 1000)).toBeCloseTo(0.02, 6);
  });

  it('leaves a handle at its real size while it is big enough', () => {
    // An 11 cm ball 2 m away is 27 px tall: no help needed.
    expect(screenScale(0.11, 16, 2, 90, 1000)).toBe(1);
  });

  it('grows a handle that would fall under the smallest size', () => {
    // 40 m away the same ball is 1.4 px; 16 px there is 1.28 m.
    const scale = screenScale(0.11, 16, 40, 90, 1000);
    expect(scale * 0.11).toBeCloseTo(1.28, 6);
  });

  it('never scales by a size it cannot divide by', () => {
    expect(screenScale(0, 16, 40, 90, 1000)).toBe(1);
  });
});

describe('screenLift', () => {
  it('is the plain offset while the helper is its real size', () => {
    expect(screenLift(0.24, 0.28, 16, 2, 42, 600)).toBe(0.24);
  });

  it('clears a helper that has grown', () => {
    // A lens body (0.28 m long, 0.16 m tall, at least 16 px) seen from 80 m in a 600 px pane.
    const bodyTop = 0.08 * screenScale(0.28, 16, 80, 42, 600);
    expect(bodyTop).toBeGreaterThan(0.24);
    // The label keeps the gap it has up close, in the body's own measure: one body height above its top.
    expect(screenLift(0.24, 0.28, 16, 80, 42, 600)).toBeCloseTo(bodyTop * 3, 6);
  });
});

describe('fitDistance', () => {
  it('stands back by the radius over the half-angle tangent', () => {
    expect(fitDistance(5, 90, 16 / 9)).toBeCloseTo(5, 6);
  });

  it('stands further back in a pane narrower than tall', () => {
    expect(fitDistance(5, 90, 0.5)).toBeCloseTo(10, 6);
  });
});

describe('wholeSetPose', () => {
  it('looks at the middle of the set on the floor, from the front right above', () => {
    const pose = wholeSetPose([10, -4], 5, 90, 2);
    expect(pose.target).toEqual([10, 0, -4]);
    expect(pose.position[0]).toBeCloseTo(12.25, 6);
    expect(pose.position[1]).toBeCloseTo(3.75, 6);
    expect(pose.position[2]).toBeCloseTo(-1, 6);
  });
});

describe('focusPose', () => {
  it('keeps the direction it was looking from and moves onto the focus', () => {
    const pose = focusPose({ position: [0, 10, 10], target: [0, 0, 0] }, { center: [20, 1, 5], radius: 2 }, 90, 2);
    expect(pose.target).toEqual([20, 1, 5]);
    // 2 m radius, 25% air around it: 2.5 m away, still looking down at 45°.
    const offset = [pose.position[0] - 20, pose.position[1] - 1, pose.position[2] - 5];
    expect(Math.hypot(...offset)).toBeCloseTo(2.5, 6);
    expect(offset[0]).toBeCloseTo(0, 6);
    expect(offset[1]).toBeCloseTo(offset[2], 6);
  });

  it('falls back to the default bearing when the view has none', () => {
    const pose = focusPose({ position: [1, 1, 1], target: [1, 1, 1] }, { center: [0, 0, 0], radius: 4 }, 90, 2);
    expect(pose.position[1]).toBeGreaterThan(0);
    expect(Math.hypot(...pose.position)).toBeCloseTo(5, 6);
  });

  it('never comes closer than the orbit allows', () => {
    const pose = focusPose({ position: [0, 0, 3], target: [0, 0, 0] }, { center: [0, 0, 0], radius: 0.01 }, 90, 2);
    expect(pose.position).toEqual([0, 0, 0.5]);
  });
});

describe('gridCells', () => {
  it('rules a section every five cells whatever the snap step', () => {
    expect(gridCells(0.1)).toEqual({ cell: 1, section: 5 });
    expect(gridCells(0.25)).toEqual({ cell: 1, section: 5 });
    expect(gridCells(0.5)).toEqual({ cell: 2, section: 10 });
    expect(gridCells(1)).toEqual({ cell: 4, section: 20 });
  });
});

describe('frustumReach', () => {
  it('draws the lens in hand out to what it looks at, up to 8 m', () => {
    expect(frustumReach(3.4, 'selected')).toBe(3.4);
    expect(frustumReach(30, 'selected')).toBe(8);
    expect(frustumReach(0.1, 'selected')).toBe(0.5);
  });

  it('keeps the filming lens short and every other lens a stub', () => {
    expect(frustumReach(6, 'active')).toBe(2.4);
    expect(frustumReach(1.2, 'active')).toBe(1.2);
    expect(frustumReach(6, 'idle')).toBe(0.7);
  });
});

describe('lensLabel', () => {
  it('names every shot a lens films, not just the first', () => {
    // A 9-shot scene that comes back to its establishing lens for the last shot.
    const shots = [1, 2, 3, 4, 5, 6, 7, 8, 9].map(id => ({ shot_id: id, camera_id: id === 9 ? 'cam-01' : `cam-0${id}` }));
    expect(lensLabel({ id: 'cam-01', label: '01 建立' }, shots)).toBe('1、9');
    expect(lensLabel({ id: 'cam-04', label: '04' }, shots)).toBe('4');
  });

  it('falls back to its own name, then its id, while it films nothing', () => {
    expect(lensLabel({ id: 'cam-12', label: '备用 广角' }, [])).toBe('备用 广角');
    expect(lensLabel({ id: 'cam-12', label: '' }, [])).toBe('cam-12');
  });
});
