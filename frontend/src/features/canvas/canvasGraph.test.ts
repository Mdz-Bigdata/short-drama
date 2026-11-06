import { describe, expect, it } from 'vitest';

import {
  connect, copySelection, createsCycle, deleteSelection, effectiveOutput, groupNodes, moveNodes, movingIds, newNode, outputType, pasteClip, roleChoices, ungroup, upstreamImageUrl,
} from './canvasGraph';
import { pushEdit, redo, startHistory, undo, HISTORY_LIMIT } from './canvasHistory';
import type { CanvasDoc, CanvasEdge, CanvasNode, NodeKind, NodeOutput } from './canvasTypes';

function node(id: string, kind: NodeKind, patch: Partial<CanvasNode> = {}): CanvasNode {
  return { ...newNode(kind, 0, 0), id, width: 100, height: 100, ...patch };
}

function edge(source: string, target: string, role?: string): CanvasEdge {
  return { id: `${source}-${target}`, source, target, kind: 'reference', payload: { role } };
}

const image: NodeOutput = { medium: 'image', url: '/media/a.png' };

describe('connection rules', () => {
  const doc: CanvasDoc = {
    nodes: [
      node('img', 'image_gen'), node('vid', 'video_gen'), node('aud', 'audio_gen'), node('txt', 'note'), node('cmp', 'video_compose'), node('sty', 'style_ref'), node('pano', 'panorama'),
      node('pv', 'previz'), node('grp', 'group'), node('empty', 'media'), node('up', 'media', { payload: { output: image } }),
    ],
    edges: [],
  };

  it('gives each kind a typed output', () => {
    const byId = (id: string) => doc.nodes.find(item => item.id === id)!;
    expect(['img', 'vid', 'aud', 'txt', 'sty', 'pv', 'grp', 'empty', 'up'].map(id => outputType(byId(id))))
      .toEqual(['image', 'video', 'audio', 'text', 'style', 'capture', null, null, 'image']);
  });

  it('turns image into video-generate into a reference input, and says what the edge means', () => {
    const made = connect(doc, 'img', 'vid');
    expect(made).toMatchObject({ ok: true, edge: { source: 'img', target: 'vid', kind: 'reference', payload: { role: 'ref_image' } } });
    expect(connect(doc, 'up', 'vid')).toMatchObject({ ok: true, edge: { kind: 'reference' } });
    expect(connect(doc, 'txt', 'vid')).toMatchObject({ ok: true, edge: { kind: 'dependency', payload: { role: 'prompt' } } });
    expect(connect(doc, 'vid', 'cmp')).toMatchObject({ ok: true, edge: { kind: 'dependency', payload: { role: 'clip' } } });
    expect(connect(doc, 'pv', 'vid')).toMatchObject({ ok: true, edge: { payload: { role: 'ref_capture' } } });
    expect(connect(doc, 'img', 'pv')).toMatchObject({ ok: true, edge: { payload: { role: 'blockout_image' } } });
    expect(connect(doc, 'img', 'sty')).toMatchObject({ ok: true });
    expect(connect(doc, 'img', 'pano')).toMatchObject({ ok: true });
  });

  it('refuses what makes no sense, and says why', () => {
    expect(connect(doc, 'img', 'img')).toEqual({ ok: false, reason: '自连' });
    expect(connect(doc, 'grp', 'vid')).toEqual({ ok: false, reason: '无输出' });
    expect(connect(doc, 'empty', 'vid')).toEqual({ ok: false, reason: '无输出' });
    expect(connect(doc, 'vid', 'img')).toEqual({ ok: false, reason: '不接受' });
    expect(connect(doc, 'img', 'txt')).toEqual({ ok: false, reason: '不接受' });
    const linked = { ...doc, edges: [edge('img', 'vid')] };
    expect(connect(linked, 'img', 'vid')).toEqual({ ok: false, reason: '已连接' });
    const chain: CanvasDoc = { nodes: [node('a', 'image_gen'), node('b', 'image_gen'), node('c', 'image_gen')], edges: [edge('a', 'b'), edge('b', 'c')] };
    expect(createsCycle(chain.edges, 'c', 'a')).toBe(true);
    expect(connect(chain, 'c', 'a')).toEqual({ ok: false, reason: '成环' });
  });

  it('lets only an image feeding a video choose its role', () => {
    const [img, vid, txt] = [node('i', 'image_gen'), node('v', 'video_gen'), node('t', 'note')];
    expect(roleChoices(img, vid)).toEqual(['ref_image', 'first_frame', 'last_frame']);
    const clip = { ...vid, id: 'clip' };
    expect(roleChoices(clip, vid)).toEqual(['ref_video', 'continue_from']);
    expect(roleChoices(txt, vid)).toEqual([]);
  });
});

describe('outputs', () => {
  it('prefers the active generation, then what the node holds, then a pass-through input', () => {
    const held = node('m', 'media', { payload: { output: image } });
    const generated = node('g', 'image_gen');
    const style = node('s', 'style_ref');
    const doc: CanvasDoc = { nodes: [held, generated, style], edges: [edge('m', 's')] };
    expect(effectiveOutput(generated, doc, {})).toBeNull();
    expect(effectiveOutput(generated, doc, { g: image })).toBe(image);
    expect(effectiveOutput(held, doc, {})).toBe(image);
    expect(effectiveOutput(style, doc, {})).toBe(image);
  });

  it('does not recurse forever on a loop an older canvas may hold', () => {
    const [a, b] = [node('a', 'style_ref'), node('b', 'panorama')];
    expect(effectiveOutput(a, { nodes: [a, b], edges: [edge('a', 'b'), edge('b', 'a')] }, {})).toBeNull();
  });

  it('finds the picture a previz node hands the desk', () => {
    const pv = node('pv', 'previz');
    const doc: CanvasDoc = { nodes: [pv, node('n', 'note', { payload: { text: 'x' } }), node('g', 'image_gen')], edges: [edge('n', 'pv'), edge('g', 'pv')] };
    expect(upstreamImageUrl(pv, doc, {})).toBeNull();
    expect(upstreamImageUrl(pv, doc, { g: image })).toBe('/media/a.png');
  });
});

describe('moving and grouping', () => {
  const members = () => [node('a', 'note', { x: 10, y: 10 }), node('b', 'note', { x: 200, y: 10 }), node('c', 'note', { x: 900, y: 900 })];

  it('moves a group with its members, once each', () => {
    const made = groupNodes({ nodes: members(), edges: [] }, new Set(['a', 'b']), '组');
    expect(made).not.toBeNull();
    const { doc, groupId } = made!;
    expect(doc.nodes[0].id).toBe(groupId);
    expect(doc.nodes[0]).toMatchObject({ x: -22, y: -46 });
    const ids = movingIds(doc.nodes, new Set([groupId]));
    expect([...ids].sort()).toEqual(['a', 'b', groupId].sort());
    const moved = moveNodes(doc, ids, 100, 50);
    expect(moved.nodes.find(item => item.id === 'a')).toMatchObject({ x: 110, y: 60, payload: { groupId } });
    expect(moved.nodes.find(item => item.id === 'c')).toMatchObject({ x: 900, y: 900 });
  });

  it('needs two nodes to make a group and never nests one', () => {
    expect(groupNodes({ nodes: members(), edges: [] }, new Set(['a']), '组')).toBeNull();
    const { doc, groupId } = groupNodes({ nodes: members(), edges: [] }, new Set(['a', 'b']), '组')!;
    const again = groupNodes(doc, new Set([groupId, 'c']), '组');
    expect(again).toBeNull();
  });

  it('a node dragged out leaves its group, and one dropped in joins', () => {
    const { doc, groupId } = groupNodes({ nodes: members(), edges: [] }, new Set(['a', 'b']), '组')!;
    const out = moveNodes(doc, new Set(['a']), 5000, 0);
    expect(out.nodes.find(item => item.id === 'a')?.payload.groupId).toBeUndefined();
    const into = moveNodes(doc, new Set(['c']), -800, -880);
    expect(into.nodes.find(item => item.id === 'c')?.payload.groupId).toBe(groupId);
  });

  it('removing a frame frees what it held', () => {
    const { doc, groupId } = groupNodes({ nodes: members(), edges: [] }, new Set(['a', 'b']), '组')!;
    for (const result of [ungroup(doc, new Set([groupId])), deleteSelection(doc, new Set([groupId]))]) {
      expect(result.nodes.map(item => item.id).sort()).toEqual(['a', 'b', 'c']);
      expect(result.nodes.every(item => !item.payload.groupId)).toBe(true);
    }
  });

  it('deleting a node takes its edges along', () => {
    const doc: CanvasDoc = { nodes: members(), edges: [edge('a', 'b'), edge('b', 'c')] };
    expect(deleteSelection(doc, new Set(['a'])).edges.map(item => item.id)).toEqual(['b-c']);
    expect(deleteSelection(doc, new Set(), new Set(['a-b'])).edges.map(item => item.id)).toEqual(['b-c']);
  });
});

describe('copy and paste', () => {
  const source: CanvasDoc = {
    nodes: [
      node('gen', 'image_gen', { artifact_id: 'art', track: 'mainline', payload: { committed: { marker: 'x' }, prompt: '雨夜' } }),
      node('vid', 'video_gen'), node('other', 'note'),
    ],
    edges: [edge('gen', 'vid'), edge('other', 'vid')],
  };

  it('fresh ids, internal edges only, the result along for the ride, nothing that belongs to the original', () => {
    const clip = copySelection(source, new Set(['gen', 'vid']), { gen: image });
    expect(clip?.edges.map(item => item.id)).toEqual(['gen-vid']);
    const { doc, ids } = pasteClip(source, clip!, 40, 40);
    expect(doc.nodes).toHaveLength(5);
    const copy = doc.nodes.find(item => ids.includes(item.id) && item.kind === 'image_gen')!;
    expect(copy.id).not.toBe('gen');
    expect(copy).toMatchObject({ x: 40, y: 40, track: 'freezone', artifact_id: null });
    expect(copy.payload.output).toBe(image);
    expect(copy.payload.committed).toBeUndefined();
    const pasted = doc.edges[doc.edges.length - 1];
    expect(pasted.source).toBe(copy.id);
    expect(ids).toContain(pasted.target);
  });

  it('copying a group brings its members and keeps them grouped', () => {
    const { doc, groupId } = groupNodes({ nodes: [node('a', 'note'), node('b', 'note')], edges: [] }, new Set(['a', 'b']), '组')!;
    const clip = copySelection(doc, new Set([groupId]), {})!;
    expect(clip.nodes).toHaveLength(3);
    const pasted = pasteClip(doc, clip, 0, 0);
    const group = pasted.doc.nodes.find(item => item.kind === 'group' && item.id !== groupId)!;
    expect(pasted.doc.nodes.filter(item => item.payload.groupId === group.id)).toHaveLength(2);
    expect(pasted.doc.nodes[0].kind).toBe('group');
  });

  it('copies nothing from an empty selection', () => {
    expect(copySelection(source, new Set(), {})).toBeNull();
  });
});

describe('undo history', () => {
  const docs = Array.from({ length: 4 }, (_, index): CanvasDoc => ({ nodes: [node(`n${index}`, 'note')], edges: [] }));

  it('undoes and redoes in order, and a new edit drops the redo tail', () => {
    let state = startHistory(docs[0]);
    state = pushEdit(state, docs[1]);
    state = pushEdit(state, docs[2]);
    state = undo(state);
    expect(state.doc).toBe(docs[1]);
    state = redo(state);
    expect(state.doc).toBe(docs[2]);
    state = undo(state);
    state = pushEdit(state, docs[3]);
    expect(state.future).toEqual([]);
    expect(undo(startHistory(docs[0])).doc).toBe(docs[0]);
    expect(redo(startHistory(docs[0])).doc).toBe(docs[0]);
  });

  it('typing in one field undoes as one step', () => {
    let state = startHistory(docs[0]);
    state = pushEdit(state, docs[1], 'prompt:n');
    state = pushEdit(state, docs[2], 'prompt:n');
    expect(state.past).toHaveLength(1);
    state = pushEdit(state, docs[3], 'label:n');
    expect(state.past).toHaveLength(2);
    expect(undo(undo(state)).doc).toBe(docs[0]);
  });

  it('ignores a change that changed nothing, and keeps a bounded past', () => {
    const state = startHistory(docs[0]);
    expect(pushEdit(state, docs[0])).toBe(state);
    let long = state;
    for (let index = 0; index < HISTORY_LIMIT + 20; index += 1) long = pushEdit(long, { nodes: [], edges: [] });
    expect(long.past).toHaveLength(HISTORY_LIMIT);
  });
});
