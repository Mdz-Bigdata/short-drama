import { describe, expect, it } from 'vitest';

import {
  canNest, carriedIds, collapseGroup, descendantIds, drawingOrder, dropIntoGroup, dropTarget, edgeEnds, expandGroup, fitGroupToMembers,
  groupDepth, groupNodes2, hiddenMemberIds, layoutUnits, snapTargets, toggleGroupCollapsed, visibleNodes,
  COLLAPSED_HEIGHT, COLLAPSED_WIDTH, FRAME_HEADER, FRAME_PADDING,
} from './canvasFrames';
import { movingIds } from './canvasGraph';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 100, height = 100, groupId?: string, kind: CanvasNode['kind'] = 'note'): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: groupId ? { groupId } : {},
});
const group = (id: string, x: number, y: number, width: number, height: number, groupId?: string) => node(id, x, y, width, height, groupId, 'group');
const find = (doc: CanvasDoc, id: string) => doc.nodes.find(item => item.id === id)!;

/** outer holds a and inner; inner holds b. */
function nested(): CanvasDoc {
  return {
    nodes: [
      group('outer', 0, 0, 800, 600),
      group('inner', 300, 100, 400, 400, 'outer'),
      node('a', 40, 80, 100, 100, 'outer'),
      node('b', 340, 200, 100, 100, 'inner'),
      node('free', 1000, 0),
    ],
    edges: [{ id: 'e1', source: 'b', target: 'free', kind: 'dependency', payload: {} }, { id: 'e2', source: 'a', target: 'b', kind: 'dependency', payload: {} }],
  };
}

describe('collapsing groups', () => {
  it('folds to a card, keeps its size, and unfolds back', () => {
    const doc: CanvasDoc = { nodes: [group('g', 0, 0, 600, 400), node('a', 30, 60, 100, 100, 'g')], edges: [] };
    const folded = collapseGroup(doc, 'g');
    expect(find(folded, 'g')).toMatchObject({ width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT, payload: { collapsed: true, expandedSize: { width: 600, height: 400 } } });
    expect(collapseGroup(folded, 'g')).toBe(folded);
    expect(hiddenMemberIds(folded)).toEqual(new Set(['a']));
    expect(visibleNodes(folded).map(item => item.id)).toEqual(['g']);
    const unfolded = expandGroup(folded, 'g');
    expect(find(unfolded, 'g')).toMatchObject({ width: 600, height: 400, payload: { collapsed: false } });
    expect(find(unfolded, 'g').payload).not.toHaveProperty('expandedSize');
    expect(toggleGroupCollapsed(toggleGroupCollapsed(doc, 'g'), 'g').nodes[0]).toMatchObject({ width: 600, height: 400 });
    expect(collapseGroup(doc, 'a')).toBe(doc);
  });

  it('hides what a collapsed outer group holds, nested members too, and reroutes their edges', () => {
    const folded = collapseGroup(nested(), 'outer');
    expect(hiddenMemberIds(folded)).toEqual(new Set(['inner', 'a', 'b']));
    expect(edgeEnds(folded, folded.edges[0])).toEqual({ source: 'outer', target: 'free' });
    expect(edgeEnds(folded, folded.edges[1])).toBeNull();
    const innerFolded = collapseGroup(nested(), 'inner');
    expect(edgeEnds(innerFolded, innerFolded.edges[1])).toEqual({ source: 'a', target: 'inner' });
    expect(snapTargets(folded, new Set(['free'])).map(item => item.id)).toEqual(['outer']);
  });
});

describe('fitting a group', () => {
  it('wraps its direct members with padding and the title bar', () => {
    const doc: CanvasDoc = { nodes: [group('g', 0, 0, 50, 50), node('a', 100, 100, 100, 50, 'g'), node('b', 300, 200, 50, 50, 'g')], edges: [] };
    expect(find(fitGroupToMembers(doc, 'g'), 'g')).toMatchObject({
      x: 100 - FRAME_PADDING, y: 100 - FRAME_HEADER - FRAME_PADDING, width: 250 + FRAME_PADDING * 2, height: 150 + FRAME_HEADER + FRAME_PADDING * 2,
    });
    expect(find(fitGroupToMembers(doc, 'g', 10, 20), 'g')).toMatchObject({ x: 90, y: 70, width: 270, height: 190 });
  });

  it('leaves an empty or collapsed group alone', () => {
    const empty: CanvasDoc = { nodes: [group('g', 0, 0, 50, 50)], edges: [] };
    expect(fitGroupToMembers(empty, 'g')).toBe(empty);
    const folded = collapseGroup({ nodes: [group('g', 0, 0, 500, 500), node('a', 100, 100, 100, 100, 'g')], edges: [] }, 'g');
    expect(fitGroupToMembers(folded, 'g')).toBe(folded);
  });
});

describe('nesting', () => {
  it('measures depth and walks descendants, surviving a cycle', () => {
    const doc = nested();
    expect(groupDepth(doc, 'outer')).toBe(0);
    expect(groupDepth(doc, 'inner')).toBe(1);
    expect(groupDepth(doc, 'b')).toBe(2);
    expect(descendantIds(doc, 'outer')).toEqual(new Set(['inner', 'a', 'b']));
    const looped: CanvasDoc = { nodes: [group('x', 0, 0, 10, 10, 'y'), group('y', 0, 0, 10, 10, 'x')], edges: [] };
    expect(descendantIds(looped, 'x')).toEqual(new Set(['y']));
    expect(groupDepth(looped, 'x')).toBe(1);
  });

  it('carries nested members along, agreeing with movingIds when nothing is nested', () => {
    const doc = nested();
    expect(carriedIds(doc.nodes, new Set(['outer']))).toEqual(new Set(['outer', 'inner', 'a', 'b']));
    expect(movingIds(doc.nodes, new Set(['outer']))).toEqual(new Set(['outer', 'inner', 'a']));
    const flat = [group('g', 0, 0, 300, 300), node('a', 10, 50, 50, 50, 'g'), node('c', 500, 0)];
    expect(carriedIds(flat, new Set(['g', 'c']))).toEqual(movingIds(flat, new Set(['g', 'c'])));
    expect(layoutUnits(doc.nodes, ['outer', 'a', 'b', 'free']).map(item => item.id)).toEqual(['outer', 'free']);
  });

  it('allows one level only, never into itself or what it holds', () => {
    const doc: CanvasDoc = { nodes: [group('p', 0, 0, 900, 900), group('c', 0, 0, 100, 100), node('n', 0, 0)], edges: [] };
    expect(canNest(doc, 'c', 'p')).toBe(true);
    expect(canNest(doc, 'p', 'p')).toBe(false);
    expect(canNest(doc, 'n', 'p')).toBe(false);
    const deep = nested();
    expect(canNest(deep, 'outer', 'inner')).toBe(false);
    deep.nodes.push(group('third', 0, 0, 50, 50));
    expect(canNest(deep, 'third', 'inner')).toBe(false);
    expect(canNest(deep, 'outer', 'third')).toBe(false);
    expect(canNest(deep, 'inner', 'third')).toBe(true);
  });

  it('groups groups one level deep and nests a group of plain nodes inside their group', () => {
    const doc: CanvasDoc = { nodes: [group('g', 0, 0, 300, 300), node('a', 30, 60, 100, 100, 'g'), node('c', 500, 0), node('d', 700, 0)], edges: [] };
    const wrapped = groupNodes2(doc, new Set(['g', 'a', 'c']), '外层')!;
    expect(wrapped).not.toBeNull();
    expect(find(wrapped.doc, 'g').payload.groupId).toBe(wrapped.groupId);
    expect(find(wrapped.doc, 'c').payload.groupId).toBe(wrapped.groupId);
    expect(find(wrapped.doc, 'a').payload.groupId).toBe('g');
    expect(wrapped.doc.nodes[0].id).toBe(wrapped.groupId);
    expect(find(wrapped.doc, wrapped.groupId)).toMatchObject({ x: -FRAME_PADDING, y: -FRAME_HEADER - FRAME_PADDING, payload: { label: '外层' } });

    const inner: CanvasDoc = { nodes: [group('g', 0, 0, 600, 300), node('a', 30, 60, 100, 100, 'g'), node('b', 200, 60, 100, 100, 'g')], edges: [] };
    const made = groupNodes2(inner, new Set(['a', 'b']), '内层')!;
    expect(find(made.doc, made.groupId).payload.groupId).toBe('g');
    expect(made.doc.nodes.map(item => item.id).slice(0, 2)).toEqual(['g', made.groupId]);
    // The nested group rides with its parent: that leaves one member, too few to group.
    expect(groupNodes2(made.doc, new Set([made.groupId, 'g']), 'x')).toBeNull();
    expect(groupNodes2(made.doc, new Set(['g', 'free']), 'x')).toBeNull();

    // A group that already holds a group cannot go one level deeper.
    expect(groupNodes2(wrapped.doc, new Set([wrapped.groupId, 'd']), 'too deep')).toBeNull();
    expect(groupNodes2(doc, new Set(['c']), 'one')).toBeNull();
  });

  it('draws outer frames before nested ones, both before their contents', () => {
    const order = drawingOrder([node('a', 0, 0, 10, 10, 'inner'), group('inner', 0, 0, 10, 10, 'outer'), group('outer', 0, 0, 10, 10), node('z', 0, 0)]);
    expect(order.map(item => item.id)).toEqual(['outer', 'inner', 'a', 'z']);
  });
});

describe('dropping into a group', () => {
  const doc = (): CanvasDoc => ({ nodes: [group('g', 0, 0, 400, 300), node('a', 600, 0), node('b', 700, 0), node('m', 50, 100, 100, 100, 'g')], edges: [] });

  it('joins when every dragged centre lies below the title bar, and grows the group', () => {
    const moved: CanvasDoc = { ...doc(), nodes: doc().nodes.map(item => (item.id === 'a' ? { ...item, x: 300, y: 150 } : item)) };
    expect(dropTarget(moved, new Set(['a']))).toBe('g');
    const next = dropIntoGroup(moved, new Set(['a']), { x: 350, y: 200 });
    expect(find(next, 'a').payload.groupId).toBe('g');
    expect(find(next, 'g').width).toBe(300 + 100 + FRAME_PADDING);
    // Grows only: the frame was already tall enough.
    expect(find(next, 'g').height).toBe(300);
  });

  it('does not join on the title bar or with the pointer outside', () => {
    const onTitle: CanvasDoc = { ...doc(), nodes: doc().nodes.map(item => (item.id === 'a' ? { ...item, x: 100, y: -40 } : item)) };
    expect(dropTarget(onTitle, new Set(['a']))).toBeNull();
    const inside: CanvasDoc = { ...doc(), nodes: doc().nodes.map(item => (item.id === 'a' ? { ...item, x: 200, y: 100 } : item)) };
    expect(dropTarget(inside, new Set(['a']), { x: 900, y: 900 })).toBeNull();
    expect(dropIntoGroup(inside, new Set(['a']), { x: 900, y: 900 })).toBe(inside);
  });

  it('leaves the group when dragged out of its frame', () => {
    const out: CanvasDoc = { ...doc(), nodes: doc().nodes.map(item => (item.id === 'm' ? { ...item, x: 900, y: 900 } : item)) };
    expect(find(dropIntoGroup(out, new Set(['m'])), 'm').payload).not.toHaveProperty('groupId');
  });

  it('nests a dropped group one level, refuses a second level, and lands a member leaving a nested group in the outer one', () => {
    const base = nested();
    const inside: CanvasDoc = { ...base, nodes: [...base.nodes, group('loose', 360, 320, 100, 100)] };
    expect(dropTarget(inside, new Set(['loose']))).toBe('outer');
    expect(find(dropIntoGroup(inside, new Set(['loose'])), 'loose').payload.groupId).toBe('outer');
    const plain: CanvasDoc = { ...base, nodes: [...base.nodes, node('p', 360, 320)] };
    expect(dropTarget(plain, new Set(['p']))).toBe('inner');

    const leaving: CanvasDoc = { ...base, nodes: base.nodes.map(item => (item.id === 'b' ? { ...item, x: 100, y: 400 } : item)) };
    expect(find(dropIntoGroup(leaving, new Set(['b'])), 'b').payload.groupId).toBe('outer');
    expect(dropTarget(base, new Set(['outer']))).toBeNull();
  });

  it('never drops into a collapsed group or into what is being dragged', () => {
    const base = nested();
    const folded = collapseGroup(base, 'inner');
    const p: CanvasDoc = { ...folded, nodes: [...folded.nodes, node('p', 320, 40, 20, 20)] };
    expect(dropTarget(p, new Set(['p']))).toBe('outer');
    expect(dropTarget(base, new Set(['inner', 'b']))).toBe('outer');
  });
});
