// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-live-viewport.ts (canvasGridMetrics) and web/src/components/canvas/canvas-viewport.tsx (CanvasGrid).
import type { CSSProperties } from 'react';

import type { Viewport } from './canvasTypes';

export type CanvasBackgroundMode = 'dots' | 'grid' | 'blank';

export const BACKGROUND_MODES: readonly CanvasBackgroundMode[] = ['dots', 'grid', 'blank'];
export const BACKGROUND_BASE: Record<Exclude<CanvasBackgroundMode, 'blank'>, number> = { dots: 24, grid: 32 };
/** The background layer is meant to extend this far past the surface's top-left (inset: -64px 0 0 -64px). */
export const BACKGROUND_BLEED = 64;

/** On-screen spacing: the base scaled by zoom, folded by 2× into [2/3·base, 4/3·base) so density stays even. */
export function gridSpacing(base: number, zoom: number) {
  let spacing = base * zoom;
  if (!Number.isFinite(spacing) || spacing <= 0) spacing = base;
  while (spacing < (base * 2) / 3) spacing *= 2;
  while (spacing >= (base * 4) / 3) spacing /= 2;
  return spacing;
}

function mod(value: number, size: number) {
  return ((value % size) + size) % size;
}

/**
 * CSS for the background layer at this view. With the layer bled by `bleed` past the top-left the pattern
 * stays anchored to world (0, 0); pass bleed 0 when painting the surface element itself.
 */
export function backgroundStyle(mode: CanvasBackgroundMode, view: Viewport, bleed = BACKGROUND_BLEED): CSSProperties {
  if (mode === 'blank') return { backgroundImage: 'none' };
  const spacing = gridSpacing(BACKGROUND_BASE[mode], view.zoom);
  const backgroundImage = mode === 'dots'
    ? 'radial-gradient(circle, rgba(var(--accent-rgb), 0.24) 1px, transparent 1.4px)'
    : 'linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px)';
  return {
    backgroundImage,
    backgroundSize: `${spacing}px ${spacing}px`,
    backgroundPosition: `${mod(view.x + bleed, spacing)}px ${mod(view.y + bleed, spacing)}px`,
  };
}
