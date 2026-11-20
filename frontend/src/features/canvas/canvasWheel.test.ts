import { describe, expect, it } from 'vitest';

import { screenToWorld } from './canvasGeometry';
import {
  applyWheel, classifyWheel, createWheelIntentGate, isMouseWheelLike, normalizeWheelDelta, wheelForcesCanvas, wheelPanDelta, wheelZoomFactor,
  WHEEL_GESTURE_IDLE_MS, WHEEL_HOVER_MS, type WheelLike,
} from './canvasWheel';

const wheel = (deltaY: number, extra: Partial<WheelLike> = {}): WheelLike => ({
  deltaX: 0, deltaY, deltaMode: 0, ctrlKey: false, metaKey: false, shiftKey: false, ...extra,
});

describe('normalizeWheelDelta', () => {
  it('turns lines and pages into pixels', () => {
    expect(normalizeWheelDelta({ deltaX: 1, deltaY: 3, deltaMode: 0 })).toEqual({ dx: 1, dy: 3 });
    expect(normalizeWheelDelta({ deltaX: 1, deltaY: 3, deltaMode: 1 })).toEqual({ dx: 16, dy: 48 });
    expect(normalizeWheelDelta({ deltaX: 0, deltaY: -1, deltaMode: 2 })).toEqual({ dx: 0, dy: -720 });
  });
});

describe('classifyWheel', () => {
  it.each<[string, WheelLike, string]>([
    ['mouse wheel notch 100', wheel(100), 'zoom'],
    ['mouse wheel notch 120', wheel(-120), 'zoom'],
    ['Windows 125% scaling notch', wheel(125), 'zoom'],
    ['two Windows 125% notches', wheel(250), 'zoom'],
    ['Firefox line mode', wheel(3, { deltaMode: 1 }), 'zoom'],
    ['page mode', wheel(1, { deltaMode: 2 }), 'zoom'],
    ['small trackpad scroll', wheel(4), 'pan'],
    ['trackpad momentum 87', wheel(87), 'pan'],
    ['trackpad with horizontal component', wheel(100, { deltaX: 2 }), 'pan'],
    ['horizontal only', { ...wheel(0), deltaX: 30 }, 'pan'],
    ['shift + mouse wheel', wheel(100, { shiftKey: true }), 'pan'],
    ['trackpad pinch (ctrl)', wheel(3.5, { ctrlKey: true }), 'pinch'],
    ['meta + trackpad', wheel(-2, { metaKey: true }), 'pinch'],
    ['ctrl + mouse wheel', wheel(120, { ctrlKey: true }), 'zoom'],
    ['ctrl + shift trackpad', wheel(2, { ctrlKey: true, shiftKey: true }), 'pinch'],
  ])('%s', (_label, event, kind) => {
    expect(classifyWheel(event)).toBe(kind);
  });

  it('only treats near multiples of 100/120/125 from 80 up as a notched wheel', () => {
    expect(isMouseWheelLike(40, 0)).toBe(false);
    expect(isMouseWheelLike(240, 0)).toBe(true);
    expect(isMouseWheelLike(375, 0)).toBe(true);
    expect(isMouseWheelLike(110, 0)).toBe(false);
    expect(isMouseWheelLike(0, 1)).toBe(false);
  });
});

describe('applyWheel', () => {
  const view = { x: 40, y: -20, zoom: 0.8 };

  it('pans by the negative delta', () => {
    expect(applyWheel(view, { ...wheel(12), deltaX: -5 }, 0, 0)).toEqual({ x: 45, y: -32, zoom: 0.8 });
  });

  it('turns shift + vertical wheel into a horizontal pan', () => {
    expect(wheelPanDelta(wheel(100, { shiftKey: true }))).toEqual({ dx: 100, dy: 0 });
    expect(applyWheel(view, wheel(100, { shiftKey: true }), 0, 0)).toEqual({ x: -60, y: -20, zoom: 0.8 });
  });

  it('zooms around the cursor, faster for a pinch than for a wheel', () => {
    const before = screenToWorld(view, 300, 200);
    const zoomed = applyWheel(view, wheel(-120), 300, 200);
    expect(zoomed.zoom).toBeCloseTo(0.8 * Math.pow(1.1, 120 / 72));
    const after = screenToWorld(zoomed, 300, 200);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
    expect(wheelZoomFactor(-24, 'pinch')).toBeCloseTo(1.1);
    expect(wheelZoomFactor(-72, 'zoom')).toBeCloseTo(1.1);
    expect(wheelZoomFactor(24, 'pinch')).toBeCloseTo(1 / 1.1);
  });
});

describe('wheel intent gate', () => {
  const area = { id: 'scroller' };
  const at = { clientX: 10, clientY: 10 };

  it('hands the wheel to an inner area only after the pointer has rested on it', () => {
    const gate = createWheelIntentGate<typeof area>();
    gate.move(area, at, 0);
    expect(gate.resolve(area, at, WHEEL_HOVER_MS - 1)).toBe('canvas');
    gate.reset();
    gate.move(area, at, 0);
    expect(gate.resolve(area, at, WHEEL_HOVER_MS)).toBe('scroll');
  });

  it('keeps a running canvas gesture on the canvas until it idles', () => {
    const gate = createWheelIntentGate<typeof area>();
    expect(gate.resolve(null, at, 0)).toBe('canvas');
    gate.move(area, at, 10);
    expect(gate.resolve(area, at, 10 + WHEEL_HOVER_MS)).toBe('canvas');
    const later = 10 + WHEEL_HOVER_MS + WHEEL_GESTURE_IDLE_MS;
    expect(gate.resolve(area, at, later)).toBe('scroll');
  });

  it('tolerates 6px of jitter but restarts the rest timer beyond it', () => {
    const gate = createWheelIntentGate<typeof area>();
    gate.move(area, at, 0);
    gate.move(area, { clientX: 14, clientY: 14 }, 100);
    expect(gate.resolve(area, { clientX: 14, clientY: 14 }, WHEEL_HOVER_MS)).toBe('scroll');
    gate.reset();
    gate.move(area, at, 0);
    gate.move(area, { clientX: 20, clientY: 10 }, 100);
    expect(gate.resolve(area, { clientX: 20, clientY: 10 }, WHEEL_HOVER_MS)).toBe('canvas');
  });

  it('lets pinch, shift and horizontal gestures force the canvas', () => {
    const gate = createWheelIntentGate<typeof area>();
    gate.move(area, at, 0);
    expect(gate.resolve(area, at, 500, wheelForcesCanvas(wheel(3, { ctrlKey: true })))).toBe('canvas');
    expect(wheelForcesCanvas({ ...wheel(2), deltaX: 10 })).toBe(true);
    expect(wheelForcesCanvas(wheel(100, { shiftKey: true }))).toBe(true);
    expect(wheelForcesCanvas(wheel(100))).toBe(false);
  });
});
