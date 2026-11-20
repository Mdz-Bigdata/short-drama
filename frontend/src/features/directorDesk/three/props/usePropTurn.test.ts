import { Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { tiltQuaternion } from './usePropTurn';

function turned(up: number[], forward: number[], local: [number, number, number]) {
  const point = new Vector3(...local).applyQuaternion(tiltQuaternion(up, forward));
  return [point.x, point.y, point.z].map(value => Math.round(value * 1000) / 1000 + 0);
}

describe('tiltQuaternion', () => {
  it('leaves an upright piece that faces ahead as it stands', () => {
    expect(turned([0, 1, 0], [0, 0, 1], [1, 2, 3])).toEqual([1, 2, 3]);
  });

  it('runs the piece’s height along the lean and faces its depth the way asked', () => {
    // A sword held level, pointing along +X with its edge down.
    expect(turned([1, 0, 0], [0, -1, 0], [0, 1, 0])).toEqual([1, 0, 0]);
    expect(turned([1, 0, 0], [0, -1, 0], [0, 0, 1])).toEqual([0, -1, 0]);
    // Not mirrored: width, height and depth stay a right-handed set.
    expect(turned([1, 0, 0], [0, -1, 0], [1, 0, 0])).toEqual([0, 0, -1]);
  });

  it('squares a facing that is not quite square to the lean, and makes do without one', () => {
    expect(turned([0, 1, 0], [0, 0.5, 1], [0, 0, 1])).toEqual([0, 0, 1]);
    const blind = turned([0, 0, 1], [0, 0, 1], [0, 1, 0]);
    expect(blind).toEqual([0, 0, 1]);
    expect(turned([0, 0, 0], [0, 0, 1], [1, 2, 3])).toEqual([1, 2, 3]);
  });
});
