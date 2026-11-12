import { describe, expect, it, vi } from 'vitest';

import { MAX_ZOOM, MIN_ZOOM, screenToWorld } from './canvasGeometry';
import {
  animateView, easeOutCubic, fitAll, fitSelection, focusRect, interpolateView, zoomStep, ZOOM_PRESETS,
} from './canvasViewportAnimation';

const W = 1000;
const H = 600;

describe('interpolateView', () => {
  const from = { x: 100, y: 50, zoom: 0.25 };
  const to = { x: -400, y: 200, zoom: 1 };

  it('starts at from and ends at to', () => {
    expect(interpolateView(from, to, 0, W, H)).toEqual(from);
    expect(interpolateView(from, to, 1, W, H)).toEqual(to);
    expect(interpolateView(from, to, -1, W, H)).toEqual(from);
    expect(interpolateView(from, to, 2, W, H)).toEqual(to);
  });

  it('moves the zoom evenly in log space and the centre linearly in world space', () => {
    const mid = interpolateView(from, to, 0.5, W, H);
    expect(mid.zoom).toBeCloseTo(0.5);
    const a = screenToWorld(from, W / 2, H / 2);
    const b = screenToWorld(to, W / 2, H / 2);
    const centre = screenToWorld(mid, W / 2, H / 2);
    expect(centre.x).toBeCloseTo((a.x + b.x) / 2);
    expect(centre.y).toBeCloseTo((a.y + b.y) / 2);
  });

  it('eases out', () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875);
  });
});

describe('animateView', () => {
  const from = { x: 0, y: 0, zoom: 1 };
  const to = { x: 200, y: 100, zoom: 2 };

  function fakeFrames() {
    const queue: Array<(time: number) => void> = [];
    return {
      raf: (callback: (time: number) => void) => queue.push(callback),
      cancelRaf: vi.fn(),
      tick: (time: number) => queue.shift()?.(time),
      pending: () => queue.length,
    };
  }

  it('runs frames and lands exactly on the target', () => {
    const frames = fakeFrames();
    const onFrame = vi.fn();
    const onDone = vi.fn();
    animateView(from, to, 200, onFrame, { now: () => 0, raf: frames.raf, cancelRaf: frames.cancelRaf, reducedMotion: false, onDone, width: W, height: H });
    frames.tick(100);
    expect(onFrame).toHaveBeenCalledTimes(1);
    const halfway = onFrame.mock.calls[0][0];
    expect(halfway.zoom).toBeGreaterThan(1);
    expect(halfway.zoom).toBeLessThan(2);
    frames.tick(250);
    expect(onFrame).toHaveBeenLastCalledWith(to);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(frames.pending()).toBe(0);
  });

  it('can be cancelled mid-way', () => {
    const frames = fakeFrames();
    const onFrame = vi.fn();
    const onDone = vi.fn();
    const cancel = animateView(from, to, 200, onFrame, { now: () => 0, raf: frames.raf, cancelRaf: frames.cancelRaf, reducedMotion: false, onDone });
    frames.tick(50);
    cancel();
    expect(frames.cancelRaf).toHaveBeenCalledTimes(1);
    cancel();
    expect(frames.cancelRaf).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  });

  it('jumps straight there with reduced motion', () => {
    const onFrame = vi.fn();
    const raf = vi.fn();
    animateView(from, to, 200, onFrame, { reducedMotion: true, raf });
    expect(onFrame).toHaveBeenCalledWith(to);
    expect(raf).not.toHaveBeenCalled();
  });
});

describe('zoom step and presets', () => {
  it('steps by 0.1 around the surface centre', () => {
    const view = { x: 30, y: -10, zoom: 1 };
    const before = screenToWorld(view, W / 2, H / 2);
    const inView = zoomStep(view, 1, W, H);
    expect(inView.zoom).toBeCloseTo(1.1);
    const after = screenToWorld(inView, W / 2, H / 2);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
    expect(zoomStep({ ...view, zoom: 0.3 }, -1, W, H).zoom).toBeCloseTo(0.2);
  });

  it('stays within the zoom limits', () => {
    expect(zoomStep({ x: 0, y: 0, zoom: 0.1 }, -1, W, H).zoom).toBeCloseTo(MIN_ZOOM);
    expect(zoomStep({ x: 0, y: 0, zoom: MAX_ZOOM }, 1, W, H).zoom).toBeCloseTo(MAX_ZOOM);
    expect(ZOOM_PRESETS).toEqual([0.25, 0.5, 1, 2]);
    expect(Math.max(...ZOOM_PRESETS)).toBeLessThanOrEqual(MAX_ZOOM);
  });
});

describe('fit and focus', () => {
  const small = [{ x: 0, y: 0, width: 100, height: 50 }, { x: 200, y: 100, width: 100, height: 50 }];

  it('fits everything with 88px padding, never past 100%', () => {
    const view = fitAll(small, W, H)!;
    expect(view.zoom).toBe(1);
    const centre = screenToWorld(view, W / 2, H / 2);
    expect(centre.x).toBeCloseTo(150);
    expect(centre.y).toBeCloseTo(75);
    const big = fitAll([{ x: 0, y: 0, width: 4000, height: 1000 }], W, H)!;
    expect(big.zoom).toBeCloseTo((W - 176) / 4000);
    expect(fitAll([], W, H)).toBeNull();
  });

  it('lets a small selection go up to 125%', () => {
    expect(fitSelection([{ x: 0, y: 0, width: 40, height: 40 }], W, H)!.zoom).toBe(1.25);
    expect(fitSelection([], W, H)).toBeNull();
  });

  it('focuses a rect between 72% and 118% and centres it', () => {
    const rect = { x: 500, y: 500, width: 200, height: 100 };
    expect(focusRect(rect, { x: 0, y: 0, zoom: 0.2 }, W, H).zoom).toBe(0.72);
    expect(focusRect(rect, { x: 0, y: 0, zoom: 2 }, W, H).zoom).toBe(1.18);
    const kept = focusRect(rect, { x: 0, y: 0, zoom: 0.9 }, W, H);
    expect(kept.zoom).toBe(0.9);
    const centre = screenToWorld(kept, W / 2, H / 2);
    expect(centre.x).toBeCloseTo(600);
    expect(centre.y).toBeCloseTo(550);
    expect(focusRect(rect, { x: 0, y: 0, zoom: 0.2 }, W, H, { minZoom: 0.5, maxZoom: 0.6 }).zoom).toBe(0.5);
  });
});
