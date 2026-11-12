import { describe, expect, it } from 'vitest';

import { buildNodeIndex, buildSpatialIndex, sameGeometry, MAX_ITEM_CELLS } from './canvasSpatialIndex';
import type { CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 320, height = 180): CanvasNode => ({
  id, kind: 'media', track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});

const rect = (x: number, y: number, width: number, height: number) => ({ x, y, width, height });

describe('canvas spatial index', () => {
  it('finds overlapping items across cells, in insertion order', () => {
    const index = buildSpatialIndex([
      { id: 'far', rect: rect(2048, 0, 152, 120) },
      { id: 'near', rect: rect(900, 40, 200, 120) },
      { id: 'cross', rect: rect(1000, -40, 1100, 80) },
    ], 1024);
    expect(index.query(rect(950, 0, 200, 100))).toEqual(['near', 'cross']);
    // 'cross' ends at x = 2100: touching the query is not overlapping it.
    expect(index.query(rect(2100, 0, 100, 100))).toEqual(['far']);
    expect(index.query(rect(2099, 0, 100, 100))).toEqual(['far', 'cross']);
    expect(index.size).toBe(3);
    expect(index.rectOf('near')).toEqual(rect(900, 40, 200, 120));
  });

  it('leaves out items that only touch the query edge, and skips empty or broken rects', () => {
    const index = buildSpatialIndex([
      { id: 'touching', rect: rect(0, 0, 10, 10) },
      { id: 'empty', rect: rect(0, 0, 0, 10) },
      { id: 'broken', rect: rect(Number.NaN, 0, 10, 10) },
    ]);
    expect(index.query(rect(10, 0, 10, 10))).toEqual([]);
    expect(index.query(rect(0, 10, 10, 10))).toEqual([]);
    expect(index.query(rect(1, 1, 1, 1))).toEqual(['touching']);
    expect(index.size).toBe(1);
    expect(index.query(rect(0, 0, 0, 0))).toEqual([]);
  });

  it('keeps an oversized item out of the grid but still finds it, ordered with the rest', () => {
    const index = buildSpatialIndex([
      { id: 'small-before', rect: rect(20_000, 20_000, 50, 50) },
      { id: 'large', rect: rect(-100_000, -100_000, 200_000, 200_000) },
      { id: 'small', rect: rect(20_000, 20_000, 100, 100) },
    ], 100);
    expect(index.query(rect(0, 0, 10, 10))).toEqual(['large']);
    expect(index.query(rect(20_000, 20_000, 50, 50))).toEqual(['small-before', 'large', 'small']);
    expect(MAX_ITEM_CELLS).toBe(256);
  });

  it('stops at a limit and still returns the hits in insertion order', () => {
    const index = buildSpatialIndex(Array.from({ length: 10 }, (_, i) => ({ id: `n${i}`, rect: rect(i * 2, 0, 1, 1) })));
    expect(index.query(rect(0, 0, 100, 100), { limit: 3 })).toEqual(['n0', 'n1', 'n2']);
    expect(index.query(rect(0, 0, 100, 100), { limit: 0 })).toHaveLength(10);
  });

  it('answers a viewport query over 50k nodes from nearby cells only', () => {
    const nodes = Array.from({ length: 50_000 }, (_, i) => node(`node${i}`, (i % 250) * 360, Math.floor(i / 250) * 220));
    const index = buildSpatialIndex(nodes.map(item => ({ id: item.id, rect: item })));
    const view = rect(10_000, 8_000, 1600, 900);
    const expected = nodes
      .filter(item => item.x < view.x + view.width && item.x + item.width > view.x && item.y < view.y + view.height && item.y + item.height > view.y)
      .map(item => item.id);
    const stats = { scanned: 0 };
    expect(index.query(view, { stats })).toEqual(expected);
    // Only the few cells under the view are examined, not the 50k nodes.
    expect(stats.scanned).toBeLessThan(200);
    expect(expected.length).toBeGreaterThan(0);
    expect(index.query(rect(0, 0, 1600, 900), { limit: 720 }).length).toBeLessThanOrEqual(720);

    // The whole canvas at once (5% zoom) still comes back complete and ordered.
    expect(index.query(rect(-1, -1, 100_000, 50_000))).toHaveLength(50_000);
  });
});

describe('node index', () => {
  it('builds once per array and reuses the index when only payloads changed', () => {
    const nodes = [node('a', 0, 0), node('b', 400, 0)];
    const index = buildNodeIndex(nodes);
    expect(buildNodeIndex(nodes)).toBe(index);
    const edited = nodes.map(item => ({ ...item, payload: { prompt: 'changed' } }));
    expect(sameGeometry(nodes, edited)).toBe(true);
    expect(buildNodeIndex(edited)).toBe(index);
    const moved = edited.map((item, i) => (i === 1 ? { ...item, x: 800 } : item));
    expect(sameGeometry(edited, moved)).toBe(false);
    const rebuilt = buildNodeIndex(moved);
    expect(rebuilt).not.toBe(index);
    expect(rebuilt.query(rect(790, 0, 20, 20))).toEqual(['b']);
    expect(sameGeometry(nodes, nodes.slice(0, 1))).toBe(false);
    expect(sameGeometry(nodes, [nodes[1], nodes[0]])).toBe(false);
  });
});
