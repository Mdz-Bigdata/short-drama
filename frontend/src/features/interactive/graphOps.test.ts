import { describe, expect, it } from 'vitest';

import {
  addChoice, addRoute, addSegment, addVariable, autoLayout, blankChoice, blankSegment, connectEdge, deleteChoice, deleteSegment, deleteVariable,
  edgePath, ensureLayout, graphBounds, graphEdges, inPort, moveChoice, moveRoute, NODE_WIDTH, nodeAt, nodeHeight, outPort, setKind, starterGraph, updateChoice,
  updateVariable, variableUses,
} from './graphOps';
import type { StoryGraph } from './storyTypes';

function fixture(): StoryGraph {
  return {
    title: '', synopsis: '', outline: [], start: 'a', variables: [{ id: 'x', label: 'x', kind: 'number', initial: 0, min: null, max: null }],
    segments: [
      { ...blankSegment('a', 'scene', 'A', { x: 0, y: 0 }), choices: [blankChoice('c1', '去 B', 'b'), blankChoice('c2', '去 C', 'c')], timer: { seconds: 5, default_choice: 'c2' } },
      { ...blankSegment('b', 'scene', 'B', { x: 300, y: 0 }), choices: [blankChoice('c3', '回 A', 'a')], routes: [{ id: 'r1', condition: { var: 'x', op: 'gte', value: 1 }, target: 'c' }] },
      blankSegment('c', 'ending', 'C', { x: 600, y: 0 }),
    ],
  };
}

describe('editing the graph', () => {
  it('connects, disconnects and re-targets an edge of either kind', () => {
    let graph = connectEdge(fixture(), 'a', 'c1', 'c');
    expect(graph.segments[0].choices[0].target).toBe('c');
    graph = connectEdge(graph, 'a', 'c1', null);
    expect(graph.segments[0].choices[0].target).toBeNull();
    expect(graphEdges(graph).some(edge => edge.id === 'c1')).toBe(false);
    graph = connectEdge(graph, 'b', 'r1', 'a');
    expect(graph.segments[1].routes[0].target).toBe('a');
  });

  it('adds segments with fresh ids, and the first one becomes the start of an empty story', () => {
    const added = addSegment(fixture(), 'scene', '新', { x: 1, y: 2 });
    expect(added.graph.segments).toHaveLength(4);
    expect(new Set(added.graph.segments.map(item => item.id)).size).toBe(4);
    expect(added.graph.start).toBe('a');
    const first = addSegment({ ...fixture(), segments: [], start: '' }, 'scene', '新', { x: 0, y: 0 });
    expect(first.graph.start).toBe(first.id);
  });

  it('gives new edges ids unique across the whole story', () => {
    const graph = addChoice(addChoice(fixture(), 'c', 'x').graph, 'c', 'y').graph;
    const routed = addRoute(graph, 'a', 'c').graph;
    const ids = routed.segments.flatMap(segment => [...segment.choices, ...segment.routes].map(edge => edge.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('deleting a segment leaves what pointed at it visibly unconnected', () => {
    const graph = deleteSegment(fixture(), 'c');
    expect(graph.segments[0].choices[1].target).toBeNull();
    expect(graph.segments[1].routes[0].target).toBeNull();
  });

  it('deleting the start moves the start', () => {
    expect(deleteSegment(fixture(), 'a').start).toBe('b');
    expect(deleteSegment({ ...fixture(), segments: [fixture().segments[0]] }, 'a').start).toBe('');
  });

  it('deleting the default choice clears the timer default', () => {
    expect(deleteChoice(fixture(), 'a', 'c2').segments[0].timer).toEqual({ seconds: 5, default_choice: '' });
  });

  it('reorders choices and routes and stays put at the ends', () => {
    const moved = moveChoice(fixture(), 'a', 'c2', -1);
    expect(moved.segments[0].choices.map(item => item.id)).toEqual(['c2', 'c1']);
    expect(moveChoice(moved, 'a', 'c2', -1).segments[0].choices.map(item => item.id)).toEqual(['c2', 'c1']);
    expect(moveRoute(fixture(), 'b', 'r1', 1).segments[1].routes).toHaveLength(1);
  });

  it('turning a scene into an ending drops its exits', () => {
    const segment = setKind(fixture(), 'a', 'ending').segments[0];
    expect([segment.kind, segment.choices, segment.routes, segment.timer]).toEqual(['ending', [], [], null]);
  });

  it('counts where a variable is used, in nested conditions and effects', () => {
    let graph = updateChoice(fixture(), 'a', 'c1', {
      condition: { all: [{ any: [{ var: 'x', op: 'eq', value: 1 }, { var: 'x', op: 'eq', value: 2 }] }] },
      effects: [{ var: 'x', op: 'add', value: 1 }],
    });
    expect(variableUses(graph, 'x')).toBe(4);
    expect(variableUses(graph, 'y')).toBe(0);
    graph = deleteVariable(graph, 'x');
    expect(graph.variables).toEqual([]);
    expect(graph.segments[0].choices[0].effects).toHaveLength(1);
  });

  it('adds variables with fresh ids and the right starting value', () => {
    const flag = addVariable(fixture(), 'flag', '钥匙');
    expect(flag.graph.variables[1]).toMatchObject({ kind: 'flag', initial: false, label: '钥匙' });
    expect(updateVariable(flag.graph, flag.id, { label: '门卡' }).variables[1].label).toBe('门卡');
    expect(addVariable(fixture(), 'number', '好感').graph.variables[1].initial).toBe(0);
  });
});

describe('geometry', () => {
  it('derives node height from its rows', () => {
    const [a, b, c] = fixture().segments;
    expect(nodeHeight(b)).toBe(nodeHeight(a));
    expect(nodeHeight(c)).toBeLessThan(nodeHeight(a));
  });

  it('finds the node under a point, the later one on top', () => {
    const graph = fixture();
    expect(nodeAt(graph, { x: 10, y: 10 })).toBe('a');
    expect(nodeAt(graph, { x: 310, y: 10 })).toBe('b');
    expect(nodeAt(graph, { x: 250, y: 10 })).toBeNull();
    const stacked: StoryGraph = { ...graph, segments: [graph.segments[0], { ...graph.segments[1], position: { x: 0, y: 0 } }] };
    expect(nodeAt(stacked, { x: 10, y: 10 })).toBe('b');
  });

  it('routes an edge from its row to the target', () => {
    const from = outPort({ x: 0, y: 0 }, 1);
    const to = inPort({ x: 300, y: 0 });
    expect(from.x).toBe(NODE_WIDTH);
    expect(edgePath(from, to).startsWith(`M ${from.x} ${from.y} C`)).toBe(true);
    expect(edgePath(from, to).endsWith(`${to.x} ${to.y}`)).toBe(true);
  });

  it('lists only edges that lead somewhere, and marks gates and timer defaults', () => {
    const edges = graphEdges(connectEdge(fixture(), 'a', 'c1', 'ghost'));
    expect(edges.map(edge => edge.id)).toEqual(['c2', 'c3', 'r1']);
    expect(edges.find(edge => edge.id === 'c2')?.isDefault).toBe(true);
    expect(edges.find(edge => edge.id === 'r1')).toMatchObject({ gated: true, kind: 'route', row: 1 });
  });

  it('lays out columns by distance from the start and sets the unreachable aside', () => {
    const graph = autoLayout({ ...fixture(), segments: [...fixture().segments, blankSegment('orphan', 'scene', '孤', null)] });
    const x = Object.fromEntries(graph.segments.map(item => [item.id, item.position!.x]));
    expect(x.a).toBe(0);
    expect(x.b).toBeGreaterThan(x.a);
    expect(x.c).toBe(x.b);
    expect(x.orphan).toBeGreaterThan(x.c);
  });

  it('never overlaps nodes in a column', () => {
    const graph = autoLayout({ ...fixture(), segments: [...fixture().segments, blankSegment('d', 'ending', 'D', null)] });
    const positions = graph.segments.filter(item => item.position!.x === graph.segments[3].position!.x);
    expect(new Set(positions.map(item => item.position!.y)).size).toBe(positions.length);
  });

  it('keeps an arranged graph and places a draft that has no layout', () => {
    const arranged = fixture();
    expect(ensureLayout(arranged)).toBe(arranged);
    const draft = { ...arranged, segments: arranged.segments.map(item => ({ ...item, position: null })) };
    expect(ensureLayout(draft).segments.every(item => item.position)).toBe(true);
  });

  it('has bounds even when empty', () => {
    expect(graphBounds({ ...fixture(), segments: [] }).right).toBe(NODE_WIDTH);
  });

  it('starts with a story that already plays', () => {
    const graph = starterGraph('开场', '结局', '继续');
    expect(graph.start).toBe('s1');
    expect(graph.segments[0].choices[0].target).toBe('end1');
  });
});
