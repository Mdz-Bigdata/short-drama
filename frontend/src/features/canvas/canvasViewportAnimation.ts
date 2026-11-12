// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-viewport.ts, web/src/pages/canvas/use-canvas-viewport-transition.ts and web/src/pages/canvas/use-canvas-viewport-controller.ts.
import { boundsOf, centerOn, clampZoom, fitView, MAX_ZOOM, zoomAt } from './canvasGeometry';
import type { Rect, Viewport } from './canvasTypes';

export const ZOOM_STEP = 0.1;
export const ZOOM_PRESETS: readonly number[] = [0.25, 0.5, 1, 2].map(zoom => Math.min(zoom, MAX_ZOOM));
export const VIEW_TRANSITION_MS = 220;
export const FIT_PADDING = 88;
export const FIT_ALL_MAX_ZOOM = 1;
export const FIT_SELECTION_MAX_ZOOM = 1.25;

export function easeOutCubic(t: number) {
  const clamped = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - clamped, 3);
}

/**
 * The view part-way from `from` to `to` (t in 0..1, not eased): the world point at the surface centre
 * moves in a straight line and the zoom moves evenly in log space, so zooming far out and back in
 * feels as fast at both ends. Without a size the surface's top-left corner is the anchor.
 */
export function interpolateView(from: Viewport, to: Viewport, t: number, width = 0, height = 0): Viewport {
  const p = Math.min(1, Math.max(0, t));
  if (p <= 0) return { ...from };
  if (p >= 1) return { ...to };
  const cx = width / 2;
  const cy = height / 2;
  const fromX = (cx - from.x) / from.zoom;
  const fromY = (cy - from.y) / from.zoom;
  const toX = (cx - to.x) / to.zoom;
  const toY = (cy - to.y) / to.zoom;
  const zoom = Math.exp(Math.log(from.zoom) + (Math.log(to.zoom) - Math.log(from.zoom)) * p);
  const worldX = fromX + (toX - fromX) * p;
  const worldY = fromY + (toY - fromY) * p;
  return { zoom, x: cx - worldX * zoom, y: cy - worldY * zoom };
}

export interface AnimateViewOptions {
  /** Surface size, so the interpolation anchors on its centre. */
  width?: number;
  height?: number;
  ease?: (t: number) => number;
  onDone?: () => void;
  /** Jump straight to `to`; defaults to the prefers-reduced-motion setting. */
  reducedMotion?: boolean;
  now?: () => number;
  raf?: (callback: (time: number) => void) => number;
  cancelRaf?: (handle: number) => void;
}

function prefersReducedMotion() {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** Animate the view; the returned function stops it where it is (onDone is then not called). */
export function animateView(from: Viewport, to: Viewport, durationMs: number, onFrame: (view: Viewport) => void, options: AnimateViewOptions = {}): () => void {
  const reduced = options.reducedMotion ?? prefersReducedMotion();
  if (durationMs <= 0 || reduced) {
    onFrame({ ...to });
    options.onDone?.();
    return () => {};
  }
  const now = options.now ?? (() => performance.now());
  const raf = options.raf ?? (callback => requestAnimationFrame(callback));
  const cancelRaf = options.cancelRaf ?? (handle => cancelAnimationFrame(handle));
  const ease = options.ease ?? easeOutCubic;
  const startedAt = now();
  let handle: number | null = null;
  const step = (time: number) => {
    const progress = (time - startedAt) / durationMs;
    if (progress >= 1) {
      handle = null;
      onFrame({ ...to });
      options.onDone?.();
      return;
    }
    onFrame(interpolateView(from, to, ease(progress), options.width, options.height));
    handle = raf(step);
  };
  handle = raf(step);
  return () => {
    if (handle === null) return;
    cancelRaf(handle);
    handle = null;
  };
}

/** The view at `zoom`, keeping the surface centre on the same world point. */
export function zoomTo(view: Viewport, zoom: number, width: number, height: number): Viewport {
  const target = clampZoom(zoom);
  return zoomAt(view, width / 2, height / 2, target / view.zoom);
}

/** One ±ZOOM_STEP click (linear, not multiplicative) around the surface centre. */
export function zoomStep(view: Viewport, dir: 1 | -1, width: number, height: number): Viewport {
  const next = Math.round((view.zoom + ZOOM_STEP * dir) * 100) / 100;
  return zoomTo(view, next, width, height);
}

/** The view that shows every rect, or null when there is nothing to show. */
export function fitAll(rects: readonly Rect[], width: number, height: number): Viewport | null {
  const bounds = boundsOf(rects);
  return bounds ? fitView(bounds, width, height, FIT_PADDING, FIT_ALL_MAX_ZOOM) : null;
}

/** Like fitAll, but a small selection may be shown a little larger than 100%. */
export function fitSelection(rects: readonly Rect[], width: number, height: number): Viewport | null {
  const bounds = boundsOf(rects);
  return bounds ? fitView(bounds, width, height, FIT_PADDING, FIT_SELECTION_MAX_ZOOM) : null;
}

/** Centre a rect (a search hit) at a readable zoom without zooming a comfortable view in or out needlessly. */
export function focusRect(rect: Rect, view: Viewport, width: number, height: number, limits: { minZoom?: number; maxZoom?: number } = {}): Viewport {
  const minZoom = limits.minZoom ?? 0.72;
  const maxZoom = limits.maxZoom ?? 1.18;
  const zoom = clampZoom(Math.min(maxZoom, Math.max(view.zoom, minZoom)));
  return centerOn(rect, { ...view, zoom }, width, height);
}
