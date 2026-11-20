import { describe, expect, it } from 'vitest';

import { batchSources, canBatchConnect, planBatchConnect, planBatchConnectNew, videoTargets } from './canvasBatchConnect';
import { CANVAS_MAX_EDGES } from './canvasGeometry';
import { connect } from './canvasGraph';
import { pushEdit, startHistory, undo } from './canvasHistory';
import type { CanvasDoc, CanvasEdge, CanvasNode, NodeKind, NodePayload } from './canvasTypes';

const node = (id: string, kind: NodeKind, x: number, y: number, payload: NodePayload = {}): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width: 200, height: 100, artifact_id: null, payload,
});
const picture = (id: string, x: number, y: number) => node(id, 'media', x, y, { output: { medium: 'image', url: `/media/${id}.png` } });
const clip = (id: string, x: number, y: number) => node(id, 'media', x, y, { output: { medium: 'video', url: `/media/${id}.mp4` } });
const edge = (source: string, target: string, role: string): CanvasEdge => ({ id: `${source}-${target}`, source, target, kind: 'reference', payload: { role } });

const BOARD: CanvasDoc = {
  nodes: [
    picture('right', 600, 0), picture('left', 0, 300), picture('left-top', 0, 0), clip('clip', 300, 50),
    node('gen', 'image_gen', 300, 400, { prompt: '雨夜' }), node('words', 'note', 100, 100, { text: '雨夜' }), node('empty', 'media', 50, 50),
    node('frame', 'group', -40, -40), node('vid', 'video_gen', 1000, 0, { label: '成片' }), node('vid2', 'video_gen', 1000, 600),
  ],
  edges: [],
};
const ALL = BOARD.nodes.map(item => item.id);

describe('what a batch connect takes', () => {
  it('takes the selected pictures and clips, left to right and then top to bottom', () => {
    expect(batchSources(BOARD, ALL).map(item => item.id)).toEqual(['left-top', 'left', 'clip', 'gen', 'right', 'vid', 'vid2']);
    expect(batchSources(BOARD, ['right', 'words', 'empty', 'frame', 'left']).map(item => item.id)).toEqual(['left', 'right']);
  });

  it('is offered for two or more of them', () => {
    expect(canBatchConnect(BOARD, ['left', 'right'])).toBe(true);
    expect(canBatchConnect(BOARD, ['left', 'clip', 'words'])).toBe(true);
    expect(canBatchConnect(BOARD, ['left'])).toBe(false);
    expect(canBatchConnect(BOARD, ['left', 'words', 'empty', 'frame'])).toBe(false);
    expect(canBatchConnect(BOARD, [])).toBe(false);
  });

  it('lists the video nodes on the board with what already comes into them', () => {
    const doc = { ...BOARD, edges: [edge('left', 'vid2', 'ref_image')] };
    expect(videoTargets(doc)).toEqual([{ id: 'vid', label: '成片', inputs: 0 }, { id: 'vid2', label: '视频生成', inputs: 1 }]);
    expect(videoTargets({ nodes: [picture('a', 0, 0)], edges: [] })).toEqual([]);
  });
});

describe('connecting them to one video node', () => {
  it('connects each in order with the role the rules give it', () => {
    const plan = planBatchConnect(BOARD, ['right', 'clip', 'left', 'left-top', 'gen'], 'vid');
    expect(plan.connected.map(item => [item.source, item.target, item.kind, item.payload.role])).toEqual([
      ['left-top', 'vid', 'reference', 'ref_image'],
      ['left', 'vid', 'reference', 'ref_image'],
      ['clip', 'vid', 'reference', 'ref_video'],
      ['gen', 'vid', 'reference', 'ref_image'],
      ['right', 'vid', 'reference', 'ref_image'],
    ]);
    expect(plan.skipped).toEqual([]);
    expect(plan.doc.edges).toEqual(plan.connected);
    expect(plan.doc.nodes).toBe(BOARD.nodes);
    expect(BOARD.edges).toEqual([]);
    // Each is the edge a hand-drawn connection would have made.
    const byHand = connect(BOARD, 'clip', 'vid');
    expect(byHand.ok && [byHand.edge.kind, byHand.edge.payload.role]).toEqual(['reference', 'ref_video']);
  });

  it('skips what is already connected and what the rules refuse, and says which', () => {
    // vid already feeds vid2, so vid2 → vid would be a loop; left → vid is there already.
    const doc: CanvasDoc = { ...BOARD, edges: [edge('left', 'vid', 'first_frame'), edge('vid', 'vid2', 'ref_video')] };
    const plan = planBatchConnect(doc, ['left', 'right', 'vid2', 'words', 'empty'], 'vid');
    expect(plan.connected.map(item => item.source)).toEqual(['right']);
    expect(plan.skipped).toEqual([{ sourceId: 'left', reason: '已连接' }, { sourceId: 'vid2', reason: '成环' }]);
    // The edge that was there keeps the role somebody chose for it.
    expect(plan.doc.edges.find(item => item.source === 'left')?.payload.role).toBe('first_frame');
    expect(plan.doc.edges).toHaveLength(3);
  });

  it('a selected video node picked as the target is the target, not a source', () => {
    const plan = planBatchConnect(BOARD, ['left', 'right', 'vid'], 'vid');
    expect(plan.connected.map(item => item.source)).toEqual(['left', 'right']);
    expect(plan.skipped).toEqual([]);
  });

  it('with nothing to connect the document is the same document', () => {
    const doc: CanvasDoc = { ...BOARD, edges: [edge('left', 'vid', 'ref_image'), edge('right', 'vid', 'ref_image')] };
    const plan = planBatchConnect(doc, ['left', 'right'], 'vid');
    expect(plan.connected).toEqual([]);
    expect(plan.skipped).toHaveLength(2);
    expect(plan.doc).toBe(doc);
    // Nothing for the undo stack to hold.
    expect(pushEdit(startHistory(doc), plan.doc).past).toHaveLength(0);
  });

  it('stops at the canvas\'s edge limit', () => {
    const filler = Array.from({ length: CANVAS_MAX_EDGES - 1 }, (_, index) => edge(`x${index}`, `y${index}`, 'ref_image'));
    const plan = planBatchConnect({ ...BOARD, edges: filler }, ['left', 'right'], 'vid');
    expect(plan.connected.map(item => item.source)).toEqual(['left']);
    expect(plan.skipped).toEqual([{ sourceId: 'right', reason: '连线上限' }]);
  });

  it('is one edit: one undo takes every new connection back', () => {
    const plan = planBatchConnect(BOARD, ['left', 'right', 'clip'], 'vid');
    const history = pushEdit(startHistory(BOARD), plan.doc);
    expect(history.past).toHaveLength(1);
    expect(undo(history).doc).toBe(BOARD);
  });
});

describe('connecting them to a new video node', () => {
  it('makes one to the right of the selection, clear of what is there, and connects to it', () => {
    const plan = planBatchConnectNew(BOARD, ['left', 'left-top', 'clip'], '新视频');
    if (!plan?.created) throw new Error('no node made');
    const made = plan.created;
    expect([made.kind, made.payload.label]).toEqual(['video_gen', '新视频']);
    expect(plan.targetId).toBe(made.id);
    expect(plan.doc.nodes).toHaveLength(BOARD.nodes.length + 1);
    expect(plan.connected.map(item => [item.source, item.target, item.payload.role])).toEqual([
      ['left-top', made.id, 'ref_image'], ['left', made.id, 'ref_image'], ['clip', made.id, 'ref_video'],
    ]);
    // Right of the three selected nodes (they end at x = 500), and on top of nothing.
    expect(made.x).toBeGreaterThanOrEqual(500);
    for (const other of BOARD.nodes.filter(item => item.kind !== 'group')) {
      const apart = made.x + made.width <= other.x || other.x + other.width <= made.x || made.y + made.height <= other.y || other.y + other.height <= made.y;
      expect(apart, other.id).toBe(true);
    }
    const history = pushEdit(startHistory(BOARD), plan.doc);
    expect(undo(history).doc).toBe(BOARD);
  });

  it('makes nothing when there is nothing to connect', () => {
    expect(planBatchConnectNew(BOARD, ['words', 'frame'])).toBeNull();
    expect(planBatchConnectNew(BOARD, [])).toBeNull();
  });
});
