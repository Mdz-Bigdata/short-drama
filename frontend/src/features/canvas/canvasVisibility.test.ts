import { describe, expect, it } from 'vitest';

import { buildSpatialIndex } from './canvasSpatialIndex';
import type { CanvasEdge, CanvasNode, Rect } from './canvasTypes';
import { edgesToDraw, renderBudget, visibilityRanges, visibleNodeIds, ENTER_PADDING, RETAIN_PADDING } from './canvasVisibility';

const node = (id: string, x: number, y: number, width = 100, height = 100): CanvasNode => ({
  id, kind: 'note', track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});
const indexOf = (nodes: CanvasNode[]) => buildSpatialIndex(nodes.map(item => ({ id: item.id, rect: item })));
const edge = (id: string, source: string, target: string): CanvasEdge => ({ id, source, target, kind: 'lineage', payload: {} });

// The view at zoom 1 with the world origin at the screen origin: world (0,0)-(1000,800) is on screen.
const VIEW = { x: 0, y: 0, zoom: 1 };
const W = 1000;
const H = 800;

describe('visibility ranges', () => {
  it('pads the view by screen pixels, so the world padding grows as the zoom shrinks', () => {
    const near = visibilityRanges({ x: 0, y: 0, zoom: 1 }, W, H);
    expect([near.view.x + 0, near.view.y + 0, near.view.width, near.view.height]).toEqual([0, 0, 1000, 800]);
    expect(near.enter.x).toBe(-ENTER_PADDING);
    expect(near.retain.x).toBe(-RETAIN_PADDING);
    const far = visibilityRanges({ x: 0, y: 0, zoom: 0.5 }, W, H);
    expect(far.enter.x).toBe(-ENTER_PADDING * 2);
    expect(far.retain.width).toBe(2000 + RETAIN_PADDING * 4);
  });

  it('budgets fewer mounted nodes the further out the zoom', () => {
    expect(renderBudget(0.1)).toBe(280);
    expect(renderBudget(0.2)).toBe(420);
    expect(renderBudget(0.28)).toBe(720);
    expect(renderBudget(1)).toBe(720);
  });
});

describe('visible nodes', () => {
  it('keeps every on-screen node however many, and only cuts the off-screen buffer to the budget', () => {
    const onScreen = Array.from({ length: 30 }, (_, i) => node(`on${i}`, (i % 6) * 150, Math.floor(i / 6) * 150));
    const buffer = Array.from({ length: 10 }, (_, i) => node(`buf${i}`, 1050, i * 70, 50, 50));
    const nodes = [...buffer, ...onScreen];
    const index = indexOf(nodes);
    const tight = visibleNodeIds({ index, nodes, view: VIEW, width: W, height: H, budget: 10 });
    expect(tight).toEqual(onScreen.map(item => item.id));
    const roomy = visibleNodeIds({ index, nodes, view: VIEW, width: W, height: H, budget: 34 });
    expect(roomy).toEqual([...buffer.slice(0, 4), ...onScreen].map(item => item.id));
    expect(visibleNodeIds({ index, nodes, view: VIEW, width: W, height: H })).toHaveLength(40);
  });

  it('caps a dense zoomed-out canvas to the zoom budget', () => {
    // 100x100 nodes on a 600-unit grid; at zoom 0.1 the screen shows 10000x8000 world units.
    const nodes = Array.from({ length: 10_000 }, (_, i) => node(`n${i}`, (i % 100) * 600, Math.floor(i / 100) * 600));
    const index = indexOf(nodes);
    const view = { x: -500, y: -500, zoom: 0.1 };
    const ids = visibleNodeIds({ index, nodes, view, width: W, height: H });
    const onScreen = visibilityRanges(view, W, H).view;
    const inView = nodes.filter(item => item.x < onScreen.x + onScreen.width && item.x + item.width > onScreen.x && item.y < onScreen.y + onScreen.height && item.y + item.height > onScreen.y);
    expect(inView.length).toBeLessThan(280);
    expect(ids.length).toBe(280);
    expect(inView.every(item => ids.includes(item.id))).toBe(true);
  });

  it('keeps a mounted node until it leaves the retain range, but mounts a new one only inside the enter range', () => {
    // 250 px right of the screen: outside enter (192) but inside retain (384).
    const between = node('between', 1250, 100);
    const nodes = [node('on', 10, 10), between];
    const index = indexOf(nodes);
    const base = { index, nodes, view: VIEW, width: W, height: H };
    expect(visibleNodeIds(base)).toEqual(['on']);
    expect(visibleNodeIds({ ...base, mounted: new Set(['on', 'between']) })).toEqual(['on', 'between']);
    // 400 px out: past retain, dropped even though it was mounted.
    const gone = [nodes[0], node('between', 1400, 100)];
    expect(visibleNodeIds({ ...base, index: indexOf(gone), nodes: gone, mounted: new Set(['on', 'between']) })).toEqual(['on']);
  });

  it('gives mounted nodes buffer places before newcomers', () => {
    const nodes = [node('new', 1050, 0, 50, 50), node('old', 1300, 0, 50, 50), node('on', 0, 0)];
    const index = indexOf(nodes);
    expect(visibleNodeIds({ index, nodes, view: VIEW, width: W, height: H, budget: 2, mounted: new Set(['old']) })).toEqual(['old', 'on']);
  });

  it('always includes forced nodes, never hidden ones, and returns canvas order', () => {
    const nodes = [node('far', 50_000, 50_000), node('member', 100, 100), node('on', 300, 300), node('gone-forced', 0, 0)];
    const index = indexOf(nodes.slice(0, 3));
    const ids = visibleNodeIds({
      index, nodes: new Map(nodes.slice(0, 3).map(item => [item.id, item])), view: VIEW, width: W, height: H,
      forced: new Set(['far', 'missing']), hidden: new Set(['member']), budget: 1,
    });
    expect(ids).toEqual(['far', 'on']);
  });
});

describe('edges to draw', () => {
  const rects = new Map<string, Rect>([
    ['a', { x: 0, y: 0, width: 100, height: 100 }],
    ['b', { x: 400, y: 0, width: 100, height: 100 }],
    ['farL', { x: -50_000, y: 300, width: 100, height: 100 }],
    ['farR', { x: 50_000, y: 300, width: 100, height: 100 }],
    ['farA', { x: 50_000, y: 50_000, width: 100, height: 100 }],
    ['farB', { x: 60_000, y: 50_000, width: 100, height: 100 }],
  ]);

  it('draws edges of drawn nodes, edges crossing the screen, and nothing that lies off it', () => {
    const edges = [edge('ab', 'a', 'b'), edge('across', 'farL', 'farR'), edge('away', 'farA', 'farB'), edge('dangling', 'a', 'missing'), edge('out', 'b', 'farA')];
    const drawn = edgesToDraw(edges, new Set(['a', 'b']), rects, VIEW, W, H);
    expect(drawn.map(item => item.id)).toEqual(['ab', 'across', 'out']);
  });

  it('caps the off-screen edges but never the ones touching a drawn node', () => {
    const edges = [
      ...Array.from({ length: 20 }, (_, i) => edge(`x${i}`, 'farL', 'farR')),
      ...Array.from({ length: 5 }, (_, i) => edge(`v${i}`, 'a', 'farA')),
    ];
    const drawn = edgesToDraw(edges, ['a'], id => rects.get(id), VIEW, W, H, { limit: 3 });
    expect(drawn.map(item => item.id)).toEqual(['x0', 'x1', 'x2', 'v0', 'v1', 'v2', 'v3', 'v4']);
  });
});
