import { describe, expect, it } from 'vitest';

import { snapAngle, snapPosition, snapToFaces, snapToGrid, snapValue, type OrientedBox } from './snapping';

const box = (position: [number, number], size: [number, number, number] = [1, 1, 1], yawDeg = 0, baseY = 0): OrientedBox => ({ position, size, yawDeg, baseY });

describe('grid snapping', () => {
  it('rounds to the nearest step and leaves values alone without one', () => {
    expect(snapValue(0.37, 0.25)).toBe(0.25);
    expect(snapValue(-0.38, 0.25)).toBe(-0.5);
    expect(snapValue(0.37, 0)).toBe(0.37);
    expect(snapToGrid([1.13, -2.62], 0.5)).toEqual([1, -2.5]);
    expect(snapAngle(52)).toBe(45);
    expect(snapAngle(-8, 15)).toBe(-15);
  });
});

describe('face snapping', () => {
  it('closes a gap under 0.2 m so the faces touch', () => {
    const result = snapToFaces(box([1.1, 0]), [box([0, 0])]);
    expect(result.position).toEqual([1, 0]);
    expect(result.snappedTo).toEqual([0]);
  });

  it('pushes a slightly overlapping box back out to the face', () => {
    expect(snapToFaces(box([-0.9, 0.3]), [box([0, 0])]).position).toEqual([-1, 0.3]);
  });

  it('leaves a box beyond the threshold where it is', () => {
    const result = snapToFaces(box([1.25, 0]), [box([0, 0])]);
    expect(result.position).toEqual([1.25, 0]);
    expect(result.snappedTo).toEqual([]);
  });

  it('needs overlap on the other ground axis', () => {
    // The X faces are 0.1 m apart, but the boxes pass each other in Z.
    expect(snapToFaces(box([1.1, 3]), [box([0, 0])]).snappedTo).toEqual([]);
  });

  it('needs overlap in height', () => {
    expect(snapToFaces(box([1.1, 0], [1, 1, 1], 0, 2), [box([0, 0])]).snappedTo).toEqual([]);
  });

  it('lines faces up in one plane when the boxes are square to each other', () => {
    // Touching in X already; the far Z faces are 0.1 m from flush.
    const result = snapToFaces(box([1, 0.1]), [box([0, 0])]);
    expect(result.position).toEqual([1, 0]);
  });

  it('works in the frame of a turned neighbour', () => {
    // The neighbour is turned 90°, so its 4 m width now runs along world Z and its faces sit at x = ±0.25.
    const wall = box([0, 0], [4, 0.5, 2], 90);
    const result = snapToFaces(box([0.85, 1]), [wall]);
    expect(result.position[0]).toBeCloseTo(0.75, 3);
    expect(result.position[1]).toBeCloseTo(1, 3);
  });

  it('uses the turned footprint of the moving box and never flushes a corner', () => {
    // Turned 45°, a 1 m square reaches 0.707 m from its centre.
    const result = snapToFaces(box([1.3, 0], [1, 1, 1], 45), [box([0, 0])]);
    expect(result.position[0]).toBeCloseTo(0.5 + Math.SQRT1_2, 3);
    expect(result.position[1]).toBe(0);
    // With no touching face in reach a rotated box has nothing to align.
    expect(snapToFaces(box([0.05, 0], [1, 1, 1], 45), [box([0, 0], [3, 3, 1])]).snappedTo).toEqual([]);
  });

  it('snaps into a corner along two perpendicular directions, once each', () => {
    const others = [box([0, 0], [1, 4, 1]), box([2, -1.6], [4, 1, 1])];
    const result = snapToFaces(box([1.1, -0.5]), others);
    expect(result.position).toEqual([1, -0.6]);
    expect(result.snappedTo).toEqual([0, 1]);
  });

  it('prefers the nearest face', () => {
    const result = snapToFaces(box([1.15, 0]), [box([0, 0]), box([2.2, 0])]);
    expect(result.position).toEqual([1.2, 0]);
    expect(result.snappedTo[0]).toBe(1);
  });
});

describe('snapPosition', () => {
  const settings = { grid: true, gridSize: 0.25, faces: true };

  it('lets a face in reach win over the grid', () => {
    expect(snapPosition(box([1.63, 0]), [box([0, 0], [2.2, 1, 1])], settings)).toEqual([1.6, 0]);
  });

  it('falls back to the grid, or to nothing', () => {
    expect(snapPosition(box([3.1, 0.4]), [box([0, 0])], settings)).toEqual([3, 0.5]);
    expect(snapPosition(box([3.1, 0.4]), [box([0, 0])], { ...settings, grid: false })).toEqual([3.1, 0.4]);
    expect(snapPosition(box([1.1, 0]), [box([0, 0])], { ...settings, faces: false })).toEqual([1, 0]);
  });
});
