import { describe, expect, it } from 'vitest';

import { changedNodeIds, flashDurationMs, focusPlan } from './canvasFocus';
import { newNode } from './canvasGraph';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

function node(id: string, patch: Partial<CanvasNode> = {}): CanvasNode {
  return { ...newNode('note', 0, 0), id, width: 100, height: 100, ...patch };
}

describe('changedNodeIds', () => {
  const a = node('a', { payload: { label: 'A', params: { model: 'm', size: 's' } } });
  const b = node('b');
  const before: CanvasDoc = { nodes: [a, b, node('gone')], edges: [] };

  it('finds added, moved, resized and edited nodes but not deleted ones', () => {
    const after: CanvasDoc = {
      nodes: [a, { ...b, x: 10 }, node('new'), { ...node('c'), id: 'c' }],
      edges: [],
    };
    expect(changedNodeIds({ ...before, nodes: [...before.nodes, node('c')] }, after)).toEqual(['b', 'new']);
    expect(changedNodeIds(before, { nodes: [{ ...a, height: 120 }, { ...b, payload: { text: 'x' } }], edges: [] })).toEqual(['a', 'b']);
  });

  it('ignores a payload that only came back with its keys reordered', () => {
    const reordered = { ...a, payload: { params: { size: 's', model: 'm' }, label: 'A' } };
    expect(changedNodeIds(before, { nodes: [reordered, b], edges: [] })).toEqual([]);
  });
});

describe('focusPlan', () => {
  const view = { x: 0, y: 0, zoom: 1 };

  it('leaves the view alone when the nodes are in sight', () => {
    expect(focusPlan([{ x: 100, y: 100, width: 200, height: 100 }], view, 800, 600)).toBeNull();
    expect(focusPlan([], view, 800, 600)).toBeNull();
  });

  it('moves to frame nodes out of sight or at the edge, never zooming past 100%', () => {
    const far = focusPlan([{ x: 2000, y: 1000, width: 200, height: 100 }], view, 800, 600)!;
    expect(far.zoom).toBe(1);
    // Centred: the box's centre lands in the middle of the screen.
    expect(2100 * far.zoom + far.x).toBeCloseTo(400);
    expect(1050 * far.zoom + far.y).toBeCloseTo(300);
    expect(focusPlan([{ x: 10, y: 100, width: 100, height: 100 }], view, 800, 600)).not.toBeNull();
    expect(focusPlan([{ x: 0, y: 0, width: 100, height: 100 }], { x: 0, y: 0, zoom: 2 }, 800, 600)!.zoom).toBe(1);
  });

  it('zooms out to fit a big change but does not zoom in on a small one', () => {
    const big = focusPlan([{ x: 0, y: 0, width: 3000, height: 1000 }], view, 800, 600)!;
    expect(big.zoom).toBeCloseTo((800 - 120) / 3000);
    const zoomedOut = { x: 0, y: 0, zoom: 0.25 };
    expect(focusPlan([{ x: 5000, y: 0, width: 100, height: 100 }], zoomedOut, 800, 600)!.zoom).toBe(0.25);
  });

  it('flashes for 1.2s', () => {
    expect(flashDurationMs).toBe(1200);
  });
});
