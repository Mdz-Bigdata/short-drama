import { describe, expect, it } from 'vitest';

import {
  align, applyPositions, arrange, arrangeByEdges, arrangeColumn, arrangeGrid, arrangeRow, distribute, spreadOut,
  ARRANGE_GAP, FLOW_COLUMN_GAP, FLOW_ROW_GAP, type PositionPatch,
} from './canvasLayout';
import type { CanvasDoc, CanvasEdge, CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 100, height = 100, groupId?: string, kind: CanvasNode['kind'] = 'note'): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: groupId ? { groupId } : {},
});
const edge = (source: string, target: string): CanvasEdge => ({ id: `${source}-${target}`, source, target, kind: 'dependency', payload: {} });

function placed(nodes: CanvasNode[], patch: PositionPatch) {
  return applyPositions({ nodes, edges: [] }, patch).nodes;
}

function overlapping(nodes: readonly CanvasNode[], gap = 0) {
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      if (a.x < b.x + b.width + gap - 0.01 && b.x < a.x + a.width + gap - 0.01 && a.y < b.y + b.height + gap - 0.01 && b.y < a.y + a.height + gap - 0.01) return [a.id, b.id];
    }
  }
  return null;
}

describe('align', () => {
  const nodes = [node('a', 0, 0, 100, 50), node('b', 200, 100, 50, 100), node('c', 50, 300, 200, 20)];
  const ids = ['a', 'b', 'c'];

  it('lines edges and centres up on the selection bounds', () => {
    expect(align(nodes, ids, 'left')).toEqual({ b: { x: 0, y: 100 }, c: { x: 0, y: 300 } });
    expect(align(nodes, ids, 'right')).toEqual({ a: { x: 150, y: 0 } });
    expect(align(nodes, ids, 'hcenter')).toEqual({ a: { x: 75, y: 0 }, b: { x: 100, y: 100 }, c: { x: 25, y: 300 } });
    expect(align(nodes, ids, 'top')).toEqual({ b: { x: 200, y: 0 }, c: { x: 50, y: 0 } });
    expect(align(nodes, ids, 'bottom')).toEqual({ a: { x: 0, y: 270 }, b: { x: 200, y: 220 } });
    expect(align(nodes, ids, 'vcenter').a).toEqual({ x: 0, y: 135 });
  });

  it('needs two, and does not move nodes outside the selection', () => {
    expect(align(nodes, ['a'], 'left')).toEqual({});
    expect(Object.keys(align(nodes, ['a', 'b'], 'top'))).toEqual(['b']);
  });

  it('moves a group with its members, and members of a selected group only through it', () => {
    const grouped = [node('g', 100, 100, 300, 300, undefined, 'group'), node('m', 150, 200, 50, 50, 'g'), node('x', 0, 0)];
    expect(align(grouped, ['g', 'm', 'x'], 'left')).toEqual({ g: { x: 0, y: 100 }, m: { x: 50, y: 200 } });
  });

  it('carries nested members too', () => {
    const nested = [
      node('outer', 100, 0, 500, 500, undefined, 'group'), node('inner', 150, 50, 300, 300, 'outer', 'group'), node('deep', 200, 100, 50, 50, 'inner'), node('x', 0, 600),
    ];
    expect(align(nested, ['outer', 'x'], 'left')).toEqual({ outer: { x: 0, y: 0 }, inner: { x: 50, y: 50 }, deep: { x: 100, y: 100 } });
  });
});

describe('distribute', () => {
  it('spaces neighbours equally and keeps the outermost two', () => {
    const nodes = [node('a', 0, 0, 100), node('b', 120, 50, 50), node('c', 400, 10, 100)];
    expect(distribute(nodes, ['c', 'a', 'b'], 'horizontal')).toEqual({ b: { x: 225, y: 50 } });
    const column = [node('a', 0, 0, 10, 100), node('b', 0, 110, 10, 10), node('c', 0, 500, 10, 100)];
    expect(distribute(column, ['a', 'b', 'c'], 'vertical')).toEqual({ b: { x: 0, y: 295 } });
  });

  it('needs three', () => {
    expect(distribute([node('a', 0, 0), node('b', 500, 0)], ['a', 'b'], 'horizontal')).toEqual({});
  });
});

describe('arrange', () => {
  const nodes = [node('b', 300, 10, 100, 60), node('a', 0, 0, 50, 100), node('c', 100, 400, 80, 80)];

  it('lines up a row by x and a column by reading order, gap 40', () => {
    const row = placed(nodes, arrangeRow(nodes, ['a', 'b', 'c']));
    expect(row.map(item => [item.id, item.x, item.y])).toEqual([['b', 50 + ARRANGE_GAP + 80 + ARRANGE_GAP, 0], ['a', 0, 0], ['c', 90, 0]]);
    const column = placed(nodes, arrangeColumn(nodes, ['a', 'b', 'c']));
    expect(column.map(item => [item.id, item.x, item.y])).toEqual([['b', 0, 140], ['a', 0, 0], ['c', 0, 240]]);
  });

  it('makes a √n grid with columns as wide as their widest box', () => {
    const many = Array.from({ length: 5 }, (_, index) => node(`n${index}`, index * 10, index * 10, 100 + index * 10, 50 + index * 10));
    const grid = placed(many, arrangeGrid(many, many.map(item => item.id)));
    const at = Object.fromEntries(grid.map(item => [item.id, [item.x, item.y]]));
    expect(at).toEqual({
      n0: [0, 0], n1: [130 + ARRANGE_GAP, 0], n2: [130 + ARRANGE_GAP + 140 + ARRANGE_GAP, 0],
      n3: [0, 70 + ARRANGE_GAP], n4: [130 + ARRANGE_GAP, 70 + ARRANGE_GAP],
    });
    expect(overlapping(grid)).toBeNull();
    expect(arrangeGrid(many, many.map(item => item.id), 1).n1).toEqual({ x: 0, y: 50 + ARRANGE_GAP });
  });

  it('goes through one entry point', () => {
    const doc: CanvasDoc = { nodes, edges: [] };
    expect(arrange(doc, ['a', 'b', 'c'], 'row')).toEqual(arrangeRow(nodes, ['a', 'b', 'c']));
    expect(arrange(doc, ['a', 'b', 'c'], 'spread')).toEqual(spreadOut(nodes, ['a', 'b', 'c']));
  });
});

describe('arrange by edges', () => {
  it('flows a chain left to right by depth, centred on its parent', () => {
    const nodes = [node('video', 0, 0, 200, 100), node('image', 50, 50, 300, 200), node('text', 100, 100, 100, 100)];
    const edges = [edge('text', 'image'), edge('image', 'video')];
    const out = placed(nodes, arrangeByEdges(nodes, edges, ['video', 'image', 'text']));
    const at = Object.fromEntries(out.map(item => [item.id, item]));
    expect(at.text.x).toBe(0);
    expect(at.image.x).toBe(100 + FLOW_COLUMN_GAP);
    expect(at.video.x).toBe(100 + FLOW_COLUMN_GAP + 300 + FLOW_COLUMN_GAP);
    expect(at.image.y + 100).toBeCloseTo(at.text.y + 50);
    expect(at.video.y + 50).toBeCloseTo(at.image.y + 100);
    expect(overlapping(out)).toBeNull();
  });

  it('stacks siblings in a column with the row gap', () => {
    const nodes = [node('root', 0, 0), node('x', 0, 0), node('y', 0, 0)];
    const out = placed(nodes, arrangeByEdges(nodes, [edge('root', 'x'), edge('root', 'y')], ['root', 'x', 'y']));
    const [x, y] = [out[1], out[2]].sort((a, b) => a.y - b.y);
    expect(x.x).toBe(y.x);
    expect(y.y - (x.y + x.height)).toBe(FLOW_ROW_GAP);
  });

  it('tolerates cycles and places loose nodes below the connected piece', () => {
    const nodes = [node('a', 0, 0), node('b', 0, 0), node('c', 0, 0), node('loose', 0, 0)];
    const patch = arrangeByEdges(nodes, [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')], ['a', 'b', 'c', 'loose']);
    const out = placed(nodes, patch);
    expect(overlapping(out)).toBeNull();
    const xs = new Set(out.slice(0, 3).map(item => item.x));
    expect(xs.size).toBe(3);
    const piece = Math.max(...out.slice(0, 3).map(item => item.y + item.height));
    expect(out[3].y).toBeGreaterThanOrEqual(piece + FLOW_COLUMN_GAP);
  });

  it('treats an edge to a member of a selected group as an edge to the group', () => {
    const nodes = [node('src', 500, 500), node('g', 0, 0, 300, 300, undefined, 'group'), node('m', 50, 50, 100, 100, 'g')];
    const out = placed(nodes, arrangeByEdges(nodes, [edge('src', 'm')], ['src', 'g']));
    const at = Object.fromEntries(out.map(item => [item.id, item]));
    expect(at.g.x).toBeGreaterThan(at.src.x);
    expect(at.m.x - at.g.x).toBe(50);
    expect(at.m.y - at.g.y).toBe(50);
  });
});

describe('spread out', () => {
  it('pushes overlapping boxes apart along their least overlap, keeping the gap', () => {
    const nodes = [node('a', 0, 0, 100, 100), node('b', 90, 10, 100, 100)];
    const out = placed(nodes, spreadOut(nodes, ['a', 'b']));
    expect(out[0].y).toBe(0);
    expect(out[1].y).toBe(10);
    expect(out[1].x - (out[0].x + 100)).toBeCloseTo(ARRANGE_GAP);
    expect(out[0].x).toBeCloseTo(-25);
  });

  it('leaves well-spaced boxes where they are', () => {
    const nodes = [node('a', 0, 0), node('b', 500, 0)];
    expect(spreadOut(nodes, ['a', 'b'])).toEqual({});
  });

  it('untangles a pile', () => {
    const pile = Array.from({ length: 6 }, (_, index) => node(`p${index}`, index * 5, index * 3, 120, 80));
    expect(overlapping(placed(pile, spreadOut(pile, pile.map(item => item.id), 20)))).toBeNull();
  });
});
