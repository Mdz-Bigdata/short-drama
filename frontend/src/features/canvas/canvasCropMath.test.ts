import { describe, expect, it } from 'vitest';

import {
  CROP_ASPECTS, DEFAULT_CROP, MIN_CROP_EDGE, aspectFits, clampRect, cropPixels, fitAspect, moveRect, resizeRect, unitRatio, type CropRect,
} from './canvasCropMath';

const inside = (rect: CropRect) => rect.x >= 0 && rect.y >= 0 && rect.x + rect.w <= 1 + 1e-9 && rect.y + rect.h <= 1 + 1e-9;
const BOX: CropRect = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };

describe('the crop rectangle', () => {
  it('stays inside the picture and never goes under the smallest crop', () => {
    expect(clampRect({ x: -1, y: 2, w: 0.5, h: 0.5 })).toEqual({ x: 0, y: 0.5, w: 0.5, h: 0.5 });
    expect(clampRect({ x: 0.99, y: 0.99, w: 0.001, h: 3 })).toEqual({ x: 1 - MIN_CROP_EDGE, y: 0, w: MIN_CROP_EDGE, h: 1 });
    expect(inside(clampRect(DEFAULT_CROP))).toBe(true);
  });

  it('moves without changing size and stops at the edges', () => {
    expect(moveRect(BOX, 0.1, -0.1)).toEqual({ x: 0.3, y: 0.1, w: 0.4, h: 0.4 });
    expect(moveRect(BOX, 5, 5)).toEqual({ x: 0.6, y: 0.6, w: 0.4, h: 0.4 });
    expect(moveRect(BOX, -5, -5)).toEqual({ x: 0, y: 0, w: 0.4, h: 0.4 });
  });

  it('resizes from a handle while the opposite side stays put', () => {
    expect(resizeRect(BOX, 'se', 0.1, 0.2)).toEqual({ x: 0.2, y: 0.2, w: 0.5, h: 0.6 });
    expect(resizeRect(BOX, 'nw', 0.1, 0.1)).toEqual({ x: 0.3, y: 0.3, w: 0.3, h: 0.3 });
    expect(resizeRect(BOX, 'e', 0.1, 0.9)).toEqual({ x: 0.2, y: 0.2, w: 0.5, h: 0.4 });
    expect(resizeRect(BOX, 'n', 0.9, -0.1)).toEqual({ x: 0.2, y: 0.1, w: 0.4, h: 0.5 });
  });

  it('a resize stops at the picture and at the smallest crop', () => {
    expect(resizeRect(BOX, 'se', 9, 9)).toEqual({ x: 0.2, y: 0.2, w: 0.8, h: 0.8 });
    expect(resizeRect(BOX, 'nw', -9, -9)).toEqual({ x: 0, y: 0, w: 0.6, h: 0.6 });
    const pinched = resizeRect(BOX, 'se', -9, -9);
    expect(pinched).toEqual({ x: 0.2, y: 0.2, w: MIN_CROP_EDGE, h: MIN_CROP_EDGE });
    const fromWest = resizeRect(BOX, 'w', 9, 0);
    expect(fromWest).toEqual({ x: 0.6 - MIN_CROP_EDGE, y: 0.2, w: MIN_CROP_EDGE, h: 0.4 });
  });
});

describe('holding a crop to a shape', () => {
  it('turns a pixel shape into the rectangle\'s own units', () => {
    // On a 2:1 picture a square crop is half as wide, in units, as it is tall.
    expect(unitRatio(1, { width: 200, height: 100 })).toBe(0.5);
    expect(unitRatio(16 / 9, { width: 1920, height: 1080 })).toBeCloseTo(1);
    expect(unitRatio(null, { width: 10, height: 10 })).toBeNull();
    expect(unitRatio(1, null)).toBeNull();
    expect(CROP_ASPECTS.map(item => item.id)).toEqual(['free', '1:1', '9:16', '16:9', '4:3', '3:4']);
  });

  it('reshapes about the centre to the largest such shape inside the rectangle', () => {
    const square = fitAspect({ x: 0.1, y: 0.1, w: 0.8, h: 0.4 }, 1);
    expect(square).toEqual({ x: 0.3, y: 0.1, w: 0.4, h: 0.4 });
    const wide = fitAspect({ x: 0.1, y: 0.1, w: 0.8, h: 0.8 }, 2);
    expect(wide).toEqual({ x: 0.1, y: 0.3, w: 0.8, h: 0.4 });
    expect(fitAspect(BOX, null)).toEqual(BOX);
  });

  it('a shape too thin for this picture is not offered', () => {
    expect(aspectFits(1)).toBe(true);
    expect(aspectFits(null)).toBe(true);
    // 9:16 out of a 20:1 banner would be 2.8% of its width: under the smallest crop.
    expect(aspectFits(unitRatio(9 / 16, { width: 2000, height: 100 }))).toBe(false);
    expect(aspectFits(unitRatio(9 / 16, { width: 1000, height: 500 }))).toBe(true);
  });

  it('keeps the shape through every handle, inside the picture', () => {
    const start = fitAspect(BOX, 2);
    for (const handle of ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const) {
      for (const [dx, dy] of [[0.05, 0.05], [-0.05, -0.05], [9, 9], [-9, -9]]) {
        const next = resizeRect(start, handle, dx, dy, 2);
        expect(next.w / next.h, `${handle} ${dx},${dy}`).toBeCloseTo(2, 4);
        expect(inside(next), `${handle} ${dx},${dy}`).toBe(true);
        expect(Math.min(next.w, next.h), `${handle} ${dx},${dy}`).toBeGreaterThanOrEqual(MIN_CROP_EDGE - 1e-6);
      }
    }
    // A corner keeps the opposite corner where it was.
    const grown = resizeRect(start, 'se', 0.1, 0);
    expect([grown.x, grown.y]).toEqual([start.x, start.y]);
    expect(grown.w).toBeCloseTo(start.w + 0.1);
  });

  it('says how many pixels the server will cut', () => {
    expect(cropPixels({ x: 0.5, y: 0, w: 0.5, h: 0.5 }, { width: 40, height: 20 })).toEqual({ width: 20, height: 10 });
    expect(cropPixels({ x: 0, y: 0, w: 0.06, h: 0.06 }, { width: 10, height: 10 })).toEqual({ width: 1, height: 1 });
  });
});
