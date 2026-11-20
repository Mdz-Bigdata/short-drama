import { describe, expect, it } from 'vitest';

import { centreOn, imagePointAt, INITIAL_VIEW, MAX_ZOOM, wheelZoomFactor, zoomAtPointer, zoomBy, type ImageView, type ViewPoint } from './assetImageZoom';

/** 图上一点此刻落在舞台的哪里。 */
function screenOf(view: ImageView, image: ViewPoint): ViewPoint {
  return {
    x: view.origin.x + (image.x - view.origin.x) * view.zoom,
    y: view.origin.y + (image.y - view.origin.y) * view.zoom,
  };
}

describe('assetImageZoom', () => {
  it('zooms the unzoomed picture around the point that was clicked', () => {
    const view = zoomAtPointer(INITIAL_VIEW, { x: 25, y: 75 }, 1.5);
    expect(view).toEqual({ zoom: 1.5, origin: { x: 25, y: 75 }, focus: { x: 25, y: 75 } });
  });

  it('keeps the detail under the cursor in place when zooming further in', () => {
    const first = zoomAtPointer(INITIAL_VIEW, { x: 25, y: 75 }, 2);
    const pointer = { x: 80, y: 40 };
    const detail = imagePointAt(first, pointer);
    expect(detail).toEqual({ x: 52.5, y: 57.5 });

    const second = zoomAtPointer(first, pointer, 3);
    expect(second.focus).toEqual(detail);
    const shown = screenOf(second, detail);
    expect(shown.x).toBeCloseTo(pointer.x);
    expect(shown.y).toBeCloseTo(pointer.y);
    expect(second.origin.x).toBeGreaterThanOrEqual(0);
    expect(second.origin.x).toBeLessThanOrEqual(100);
  });

  it('never lets zooming out pull the picture off the stage', () => {
    const zoomedIn = zoomAtPointer(INITIAL_VIEW, { x: 95, y: 5 }, 4);
    const out = zoomAtPointer(zoomedIn, { x: 5, y: 95 }, 2);
    for (const value of [out.origin.x, out.origin.y]) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    }
    expect(zoomAtPointer(out, { x: 5, y: 95 }, 0.2).zoom).toBe(1);
  });

  it('holds the picture still when the wheel keeps turning at the limit', () => {
    const atLimit = zoomAtPointer(INITIAL_VIEW, { x: 50, y: 50 }, MAX_ZOOM);
    const more = zoomAtPointer(atLimit, { x: 90, y: 50 }, MAX_ZOOM * 1.2);
    expect(more.zoom).toBe(MAX_ZOOM);
    expect(more.origin).toEqual(atLimit.origin);
    expect(more.focus).toEqual({ x: 60, y: 50 });
  });

  it('centres on the clicked detail once the zoom is at its limit', () => {
    const atLimit = zoomAtPointer(INITIAL_VIEW, { x: 50, y: 50 }, MAX_ZOOM);
    expect(centreOn(atLimit, { x: 90, y: 50 })).toEqual({ zoom: MAX_ZOOM, origin: { x: 60, y: 50 }, focus: { x: 60, y: 50 } });
  });

  it('steps from the buttons without moving the centre', () => {
    const view = zoomAtPointer(INITIAL_VIEW, { x: 25, y: 75 }, 1.5);
    expect(zoomBy(view, 0.5)).toEqual({ ...view, zoom: 2 });
    expect(zoomBy(INITIAL_VIEW, -0.5).zoom).toBe(1);
    expect(zoomBy({ ...view, zoom: 3.8 }, 0.5).zoom).toBe(MAX_ZOOM);
  });

  it('adds up a slow scroll or pinch instead of losing every small step', () => {
    const pointer = { x: 30, y: 60 };
    const travel = (start: ImageView, deltaY: number, events: number, pinch = false) => {
      let view = start;
      for (let step = 0; step < events; step += 1) {
        view = zoomAtPointer(view, pointer, view.zoom * wheelZoomFactor(deltaY, pinch));
      }
      return view;
    };

    // 同样滚 600，一格一格滚和一点一点滚到的倍数一样。
    const notches = travel(INITIAL_VIEW, -100, 6).zoom;
    expect(notches).toBeCloseTo(Math.exp(0.9), 5);
    expect(travel(INITIAL_VIEW, -1, 600).zoom).toBeCloseTo(notches, 5);
    expect(travel(INITIAL_VIEW, -3, 200).zoom).toBeCloseTo(notches, 5);
    expect(travel(INITIAL_VIEW, -0.3, 200, true).zoom).toBeCloseTo(Math.exp(0.6), 5);

    // 往回缩也一样，并且指针下的那一点一路没动。
    const enlarged = zoomAtPointer(INITIAL_VIEW, pointer, 3);
    const detail = imagePointAt(enlarged, pointer);
    const out = travel(enlarged, 1, 300);
    expect(out.zoom).toBeCloseTo(3 * Math.exp(-0.45), 5);
    expect(screenOf(out, detail).x).toBeCloseTo(pointer.x);
    expect(screenOf(out, detail).y).toBeCloseTo(pointer.y);
    expect(travel(enlarged, 0.5, 6000).zoom).toBe(1);

    const stepped = zoomBy(travel(INITIAL_VIEW, -1, 100), 0.5);
    expect(stepped.zoom).toBeCloseTo(Math.exp(0.15) + 0.5, 5);
  });

  it('turns wheel travel into a gentle factor instead of a fixed jump', () => {
    // 滚轮一格：约 1.16 倍，而不是一下加半档。
    expect(wheelZoomFactor(-100, false)).toBeCloseTo(1.162, 3);
    expect(wheelZoomFactor(100, false)).toBeCloseTo(0.861, 3);
    // 触控板的一小步几乎不动；捏合(带 ctrl)同样的位移走得快些。
    expect(wheelZoomFactor(-4, false)).toBeCloseTo(1.006, 3);
    expect(wheelZoomFactor(-4, true)).toBeCloseTo(1.041, 3);
  });
});
