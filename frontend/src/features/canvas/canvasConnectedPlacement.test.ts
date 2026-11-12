import { describe, expect, it } from 'vitest';

import { createConnectedNode, findFreeSpot, placeConnectedNode, NODE_CLEARANCE } from './canvasConnectedPlacement';
import { DEFAULT_SIZES } from './canvasGraph';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

const node = (id: string, kind: CanvasNode['kind'], x: number, y: number, width = 300, height = 200): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});

describe('connected node placement', () => {
  const source = { x: 0, y: 0, width: 300, height: 200 };

  it('puts the near edge on the drop point, vertically centred', () => {
    expect(placeConnectedNode(source, { x: 900, y: 320 }, { width: 720, height: 400 }, 'right')).toEqual({ x: 900, y: 120 });
    expect(placeConnectedNode(source, { x: -400, y: 100 }, { width: 340, height: 120 }, 'left')).toEqual({ x: -740, y: 40 });
  });

  it('keeps a drop over the source clear of it', () => {
    expect(placeConnectedNode(source, { x: 100, y: 100 }, { width: 200, height: 100 }, 'right').x).toBe(300 + NODE_CLEARANCE);
    expect(placeConnectedNode(source, { x: 100, y: 100 }, { width: 200, height: 100 }, 'left').x).toBe(-NODE_CLEARANCE - 200);
  });

  it('goes beside the source without a drop point', () => {
    expect(placeConnectedNode(source, null, { width: 200, height: 100 }, 'right')).toEqual({ x: 420, y: 50 });
    expect(placeConnectedNode(source, null, { width: 200, height: 100 }, 'left')).toEqual({ x: -320, y: 50 });
  });

  it('finds the nearer free spot, down or right', () => {
    const others = [{ x: 0, y: 0, width: 100, height: 300 }];
    expect(findFreeSpot(others, { x: 0, y: 0 }, { width: 100, height: 100 })).toEqual({ x: 136, y: 0 });
    expect(findFreeSpot(others, { x: 0, y: 0 }, { width: 100, height: 100 }, ['down'])).toEqual({ x: 0, y: 336 });
    expect(findFreeSpot([], { x: 5, y: 5 }, { width: 10, height: 10 })).toEqual({ x: 5, y: 5 });
  });

  it('creates and wires a node to the right of an output', () => {
    const doc: CanvasDoc = { nodes: [node('img', 'image_gen', 0, 0)], edges: [] };
    const result = createConnectedNode(doc, 'img', 'video_gen', { x: 600, y: 100 });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const [, height] = DEFAULT_SIZES.video_gen;
    expect(result.node).toMatchObject({ kind: 'video_gen', x: 600, y: 100 - height / 2 });
    expect(result.doc.nodes.map(item => item.id)).toEqual(['img', result.nodeId]);
    expect(result.doc.edges).toEqual([expect.objectContaining({ source: 'img', target: result.nodeId, kind: 'reference', payload: { role: 'ref_image' } })]);
    expect(doc.nodes).toHaveLength(1);
  });

  it('wires new → source when dropped to the left of an input', () => {
    const doc: CanvasDoc = { nodes: [node('vid', 'video_gen', 1000, 0)], edges: [] };
    const result = createConnectedNode(doc, 'vid', 'note', { x: 800, y: 100 }, 'left');
    expect(result.ok && result.doc.edges[0]).toMatchObject({ source: result.ok ? result.nodeId : '', target: 'vid', payload: { role: 'prompt' } });
  });

  it('refuses with the connect reason and adds nothing', () => {
    const doc: CanvasDoc = { nodes: [node('a', 'audio_gen', 0, 0)], edges: [] };
    expect(createConnectedNode(doc, 'a', 'style_ref', { x: 500, y: 0 })).toEqual({ ok: false, reason: '不接受' });
    expect(createConnectedNode(doc, 'missing', 'note', null)).toEqual({ ok: false, reason: '不接受' });
    const group: CanvasDoc = { nodes: [node('g', 'group', 0, 0)], edges: [] };
    expect(createConnectedNode(group, 'g', 'image_gen', null)).toEqual({ ok: false, reason: '无输出' });
  });

  it('moves clear of existing nodes when there is no drop point', () => {
    const doc: CanvasDoc = { nodes: [node('img', 'image_gen', 0, 0, 300, 200), node('busy', 'note', 420, -200, 300, 600)], edges: [] };
    const result = createConnectedNode(doc, 'img', 'video_gen', null);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const busy = doc.nodes[1];
    const placed = result.node;
    const clear = placed.x >= busy.x + busy.width + NODE_CLEARANCE || placed.y >= busy.y + busy.height + NODE_CLEARANCE;
    expect(clear).toBe(true);
  });
});
