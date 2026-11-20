import { describe, expect, it } from 'vitest';

import { MAX_ZOOM, MIN_ZOOM } from './canvasGeometry';
import { backgroundStyle, BACKGROUND_BLEED, gridSpacing } from './canvasBackground';

describe('gridSpacing', () => {
  it('keeps on-screen spacing within [2/3·base, 4/3·base) across every zoom', () => {
    for (const base of [24, 32]) {
      for (let zoom = MIN_ZOOM; zoom <= MAX_ZOOM; zoom += 0.013) {
        const spacing = gridSpacing(base, zoom);
        expect(spacing).toBeGreaterThanOrEqual((base * 2) / 3 - 1e-9);
        expect(spacing).toBeLessThan((base * 4) / 3);
        // A world-aligned fold: the spacing is the zoomed base times a power of two.
        const ratio = Math.log2(spacing / (base * zoom));
        expect(Math.abs(ratio - Math.round(ratio))).toBeLessThan(1e-9);
      }
    }
  });

  it('leaves the base alone at 100% and falls back on bad zooms', () => {
    expect(gridSpacing(24, 1)).toBe(24);
    expect(gridSpacing(24, 0)).toBe(24);
    expect(gridSpacing(24, Number.NaN)).toBe(24);
  });
});

describe('backgroundStyle', () => {
  it('draws nothing for blank', () => {
    expect(backgroundStyle('blank', { x: 0, y: 0, zoom: 1 })).toEqual({ backgroundImage: 'none' });
  });

  it('sizes dots and grid lines and wraps the offset into one cell', () => {
    const dots = backgroundStyle('dots', { x: -100, y: 37, zoom: 1 });
    expect(dots.backgroundSize).toBe('24px 24px');
    expect(dots.backgroundImage).toContain('var(--accent-rgb)');
    const wrap = (value: number) => ((value % 24) + 24) % 24;
    expect(dots.backgroundPosition).toBe(`${wrap(-100 + BACKGROUND_BLEED)}px ${wrap(37 + BACKGROUND_BLEED)}px`);
    const grid = backgroundStyle('grid', { x: 0, y: 0, zoom: 0.5 });
    expect(grid.backgroundSize).toBe('32px 32px');
    expect(grid.backgroundImage).toContain('var(--line)');
    expect(backgroundStyle('grid', { x: 5, y: 7, zoom: 1 }, 0).backgroundPosition).toBe('5px 7px');
  });
});
