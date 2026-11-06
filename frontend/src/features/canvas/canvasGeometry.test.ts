import { describe, expect, it } from 'vitest';

import {
  boundsOf, contains, edgePath, fitView, intersects, minimapToWorld, nodeAt, normalizeRect, screenToWorld, snapMove, visibleRect, zoomAt, MAX_ZOOM, MIN_ZOOM,
} from './canvasGeometry';
import type { CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 100, height = 100, kind: CanvasNode['kind'] = 'note'): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});

describe('canvas geometry', () => {
  it('zooms around the cursor: the world point under it stays under it', () => {
    const view = { x: 120, y: -40, zoom: 0.8 };
    const before = screenToWorld(view, 300, 200);
    const zoomed = zoomAt(view, 300, 200, 1.7);
    expect(zoomed.zoom).toBeCloseTo(1.36);
    const after = screenToWorld(zoomed, 300, 200);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it('never zooms past its limits, and stays anchored there', () => {
    expect(zoomAt({ x: 0, y: 0, zoom: 1 }, 0, 0, 1000).zoom).toBe(MAX_ZOOM);
    expect(zoomAt({ x: 0, y: 0, zoom: 1 }, 0, 0, 0.0001).zoom).toBe(MIN_ZOOM);
    const before = screenToWorld({ x: 50, y: 50, zoom: 2.5 }, 10, 10);
    const after = screenToWorld(zoomAt({ x: 50, y: 50, zoom: 2.5 }, 10, 10, 3), 10, 10);
    expect(after.x).toBeCloseTo(before.x);
  });

  it('knows what is on screen', () => {
    expect(visibleRect({ x: -100, y: -200, zoom: 2 }, 800, 600)).toEqual({ x: 50, y: 100, width: 400, height: 300 });
    expect(intersects({ x: 0, y: 0, width: 10, height: 10 }, { x: 10, y: 0, width: 5, height: 5 })).toBe(false);
    expect(intersects({ x: 0, y: 0, width: 10, height: 10 }, { x: 9, y: 9, width: 5, height: 5 })).toBe(true);
    expect(contains({ x: 0, y: 0, width: 10, height: 10 }, { x: 1, y: 1, width: 2, height: 2 })).toBe(true);
    expect(normalizeRect(10, 20, 0, 5)).toEqual({ x: 0, y: 5, width: 10, height: 15 });
    expect(boundsOf([])).toBeNull();
  });

  it('fits a rectangle in view, centred, without blowing up a small canvas', () => {
    const view = fitView({ x: 0, y: 0, width: 2000, height: 1000 }, 1000, 500, 0);
    expect(view.zoom).toBeCloseTo(0.5);
    expect(view.x).toBeCloseTo(0);
    expect(fitView({ x: 0, y: 0, width: 10, height: 10 }, 1000, 500).zoom).toBe(1);
  });

  it('finds the node on top, and a group only when nothing else is there', () => {
    const nodes = [node('g', 0, 0, 500, 500, 'group'), node('a', 10, 10), node('b', 50, 50)];
    expect(nodeAt(nodes, 60, 60)?.id).toBe('b');
    expect(nodeAt(nodes, 20, 20)?.id).toBe('a');
    expect(nodeAt(nodes, 400, 400)?.id).toBe('g');
    expect(nodeAt(nodes, 900, 900)).toBeNull();
    expect(nodeAt(nodes, 60, 60, new Set(['b']))?.id).toBe('a');
  });

  it('snaps edges and centres to the closest line, and reports the guide', () => {
    const other = { x: 200, y: 300, width: 100, height: 100 };
    const left = snapMove({ x: 204, y: 0, width: 50, height: 50 }, [other], 6);
    expect(left.dx).toBe(-4);
    expect(left.guides[0]).toMatchObject({ axis: 'x', at: 200 });
    const centred = snapMove({ x: 226, y: 900, width: 50, height: 50 }, [other], 6);
    expect(centred.dx).toBe(-1);
    expect(centred.guides[0].at).toBe(250);
    const far = snapMove({ x: 1000, y: 1000, width: 50, height: 50 }, [other], 6);
    expect(far).toEqual({ dx: 0, dy: 0, guides: [] });
    const both = snapMove({ x: 197, y: 303, width: 50, height: 50 }, [other, { x: 195, y: 0, width: 10, height: 10 }], 6);
    expect(both.dx).toBe(-2);
    expect(both.dy).toBe(-3);
    expect(both.guides.map(item => item.axis)).toEqual(['x', 'y']);
  });

  it('maps a minimap click back to the world, letterboxed or not', () => {
    const point = minimapToWorld({ width: 200, height: 100 }, { x: -100, y: 0, width: 100, height: 100 }, 100, 50);
    expect(point.x).toBeCloseTo(-50);
    expect(point.y).toBeCloseTo(50);
  });

  it('draws an edge as one smooth curve between its ends', () => {
    expect(edgePath(0, 0, 100, 50)).toMatch(/^M 0 0 C /);
  });
});
