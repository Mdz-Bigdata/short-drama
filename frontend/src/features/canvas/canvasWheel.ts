// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-wheel.ts, web/src/lib/canvas/canvas-wheel-intent.ts and web/src/components/canvas/canvas-viewport.tsx (wheel handling).
import { zoomAt } from './canvasGeometry';
import type { Viewport } from './canvasTypes';

export interface WheelDeltaLike {
  deltaX: number;
  deltaY: number;
  /** 0 pixels, 1 lines, 2 pages (WheelEvent.DOM_DELTA_*). */
  deltaMode: number;
}

export interface WheelLike extends WheelDeltaLike {
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}

/** 'pinch' a trackpad pinch (ctrl/meta with smooth deltas), 'zoom' a notched mouse wheel, 'pan' a two-finger scroll. */
export type WheelKind = 'pinch' | 'zoom' | 'pan';

export const LINE_HEIGHT_PX = 16;
export const PAGE_HEIGHT_PX = 720;
/** Wheel distance (px) that scales the view by 1.1×: a pinch reports small deltas, so it needs a shorter distance. */
export const PINCH_ZOOM_DISTANCE = 24;
export const WHEEL_ZOOM_DISTANCE = 72;

export function normalizeWheelDelta(event: WheelDeltaLike): { dx: number; dy: number } {
  const scale = event.deltaMode === 1 ? LINE_HEIGHT_PX : event.deltaMode === 2 ? PAGE_HEIGHT_PX : 1;
  return { dx: event.deltaX * scale, dy: event.deltaY * scale };
}

/** A notched mouse wheel: line/page deltas, or a pixel step of 100/120/125 (Windows 125% scaling) or a multiple of it. */
export function isMouseWheelLike(deltaY: number, deltaMode: number) {
  const amount = Math.abs(deltaY);
  if (!Number.isFinite(amount) || !amount) return false;
  if (deltaMode !== 0) return true;
  return amount >= 80 && [100, 120, 125].some(step => Math.abs(amount - Math.round(amount / step) * step) < 1);
}

export function classifyWheel(event: WheelLike): WheelKind {
  const { dx, dy } = normalizeWheelDelta(event);
  const modifier = event.ctrlKey || event.metaKey;
  const mouseLike = isMouseWheelLike(event.deltaY, event.deltaMode);
  if (modifier) return mouseLike ? 'zoom' : 'pinch';
  if (event.shiftKey || Math.abs(dx) > 0 || (!mouseLike && Math.abs(dy) > 0)) return 'pan';
  return 'zoom';
}

/** Screen pixels to pan by; shift turns a vertical wheel into a horizontal pan. */
export function wheelPanDelta(event: WheelLike): { dx: number; dy: number } {
  const { dx, dy } = normalizeWheelDelta(event);
  if (event.shiftKey && Math.abs(dx) < 1) return { dx: dy, dy: 0 };
  return { dx, dy };
}

export function wheelZoomFactor(dy: number, kind: WheelKind) {
  return Math.pow(1.1, -dy / (kind === 'pinch' ? PINCH_ZOOM_DISTANCE : WHEEL_ZOOM_DISTANCE));
}

/** The view after one wheel event with the cursor at (cursorX, cursorY) in surface coordinates. */
export function applyWheel(view: Viewport, event: WheelLike, cursorX: number, cursorY: number): Viewport {
  const kind = classifyWheel(event);
  if (kind === 'pan') {
    const { dx, dy } = wheelPanDelta(event);
    return { zoom: view.zoom, x: view.x - dx, y: view.y - dy };
  }
  const { dy } = normalizeWheelDelta(event);
  return zoomAt(view, cursorX, cursorY, wheelZoomFactor(dy, kind));
}

/** Pinch, shift and mostly-horizontal gestures always belong to the canvas, even over a scrollable area. */
export function wheelForcesCanvas(event: WheelLike) {
  const { dx, dy } = normalizeWheelDelta(event);
  return event.ctrlKey || event.metaKey || event.shiftKey || Math.abs(dx) > Math.abs(dy);
}

export const WHEEL_HOVER_MS = 160;
export const WHEEL_GESTURE_IDLE_MS = 180;
export const WHEEL_POINTER_SLOP = 6;
export const WHEEL_INTENT_SELECTOR = '[data-canvas-wheel-intent]';
const WHEEL_POPUP_SELECTOR = "[role='dialog'],[role='menu'],[role='listbox']";

export interface WheelPoint {
  clientX: number;
  clientY: number;
}

export interface WheelIntentGate<T> {
  /** Track the hovered area on pointer move, so resting over it can be timed. */
  move(target: T | null, point: WheelPoint, now: number): void;
  /** Who takes this wheel event: the inner scrollable area, or the canvas. */
  resolve(target: T | null, point: WheelPoint, now: number, forceCanvas?: boolean): 'canvas' | 'scroll';
  reset(): void;
}

/**
 * An inner scrollable area takes the wheel only once the pointer has rested on it for WHEEL_HOVER_MS
 * and the previous gesture has been idle for WHEEL_GESTURE_IDLE_MS, so a canvas pan that sweeps
 * across a node never gets caught by the node's own scroller halfway through.
 */
export function createWheelIntentGate<T>(): WheelIntentGate<T> {
  let hovered: T | null = null;
  let settledAt = 0;
  let anchorX = 0;
  let anchorY = 0;
  let lastWheelAt = -Infinity;
  let scrollOwner: T | null = null;
  let gestureActive = false;

  const move = (target: T | null, point: WheelPoint, now: number) => {
    if (target !== hovered || Math.hypot(point.clientX - anchorX, point.clientY - anchorY) > WHEEL_POINTER_SLOP) {
      hovered = target;
      settledAt = now;
      anchorX = point.clientX;
      anchorY = point.clientY;
    }
  };

  return {
    move,
    resolve(target, point, now, forceCanvas = false) {
      move(target, point, now);
      if (forceCanvas) {
        scrollOwner = null;
        gestureActive = true;
      } else if (!gestureActive || now - lastWheelAt >= WHEEL_GESTURE_IDLE_MS) {
        scrollOwner = target && now - settledAt >= WHEEL_HOVER_MS ? target : null;
        gestureActive = true;
      } else if (scrollOwner !== target) {
        scrollOwner = null;
      }
      lastWheelAt = now;
      return scrollOwner ? 'scroll' : 'canvas';
    },
    reset() {
      hovered = null;
      scrollOwner = null;
      lastWheelAt = -Infinity;
      gestureActive = false;
    },
  };
}

/** The [data-canvas-wheel-intent] area under the pointer; popups and form fields never count. */
export function wheelIntentTarget(target: Element | null): Element | null {
  if (!target || target.closest(WHEEL_POPUP_SELECTOR) || target.closest('input,select')) return null;
  return target.closest(WHEEL_INTENT_SELECTOR);
}
