import { describe, expect, it } from 'vitest';

import { FRAME_HEADER } from './canvasFrames';
import { CANVAS_MAX_NODES } from './canvasGeometry';
import { connect, newNode } from './canvasGraph';
import { pushEdit, startHistory, undo } from './canvasHistory';
import { firstLastFrameTemplate } from './canvasTemplates';
import type { CanvasDoc } from './canvasTypes';

const LABELS = { group: '首尾帧生视频', first: '首帧', last: '尾帧' };
const EMPTY: CanvasDoc = { nodes: [], edges: [] };

describe('the first/last-frame template', () => {
  it('makes two frames stacked, a video node on their right, and the two role edges, all in one group', () => {
    const made = firstLastFrameTemplate(EMPTY, { x: 100, y: 200 }, LABELS);
    if (!made.ok) throw new Error('refused');
    const byId = new Map(made.doc.nodes.map(node => [node.id, node]));
    const [group, first, last, video] = [made.groupId, made.firstId, made.lastId, made.videoId].map(id => byId.get(id)!);

    expect(made.doc.nodes).toHaveLength(4);
    expect([group.kind, first.kind, last.kind, video.kind]).toEqual(['group', 'image_gen', 'image_gen', 'video_gen']);
    expect([group.payload.label, first.payload.label, last.payload.label]).toEqual(['首尾帧生视频', '首帧', '尾帧']);
    // The frame's corner is where the click was; the frames are one above the other, the video to their right.
    expect([group.x, group.y]).toEqual([100, 200]);
    expect(first.x).toBe(last.x);
    expect(last.y).toBeGreaterThanOrEqual(first.y + first.height);
    expect(video.x).toBeGreaterThanOrEqual(first.x + first.width);
    expect(first.y).toBeGreaterThanOrEqual(group.y + FRAME_HEADER);
    for (const node of [first, last, video]) {
      expect(node.payload.groupId).toBe(group.id);
      expect(node.x).toBeGreaterThanOrEqual(group.x);
      expect(node.y).toBeGreaterThanOrEqual(group.y);
      expect(node.x + node.width).toBeLessThanOrEqual(group.x + group.width);
      expect(node.y + node.height).toBeLessThanOrEqual(group.y + group.height);
    }
    // Groups draw first, so the frame stays behind what it holds.
    expect(made.doc.nodes[0].id).toBe(group.id);

    expect(made.doc.edges.map(edge => [edge.source, edge.target, edge.kind, edge.payload.role])).toEqual([
      [first.id, video.id, 'reference', 'first_frame'],
      [last.id, video.id, 'reference', 'last_frame'],
    ]);
  });

  it('is what the connection rules themselves allow', () => {
    const made = firstLastFrameTemplate(EMPTY, { x: 0, y: 0 }, LABELS);
    if (!made.ok) throw new Error('refused');
    // Drawn by hand the same two connections are legal, and a third copy of either is not.
    const bare: CanvasDoc = { nodes: made.doc.nodes, edges: [] };
    expect(connect(bare, made.firstId, made.videoId).ok).toBe(true);
    expect(connect(made.doc, made.firstId, made.videoId)).toEqual({ ok: false, reason: '已连接' });
    expect(connect(made.doc, made.videoId, made.firstId).ok).toBe(false);
  });

  it('leaves what is already on the canvas alone and is undone in one step', () => {
    const note = newNode('note', 0, 0, { text: '雨夜' });
    const before: CanvasDoc = { nodes: [note], edges: [] };
    const made = firstLastFrameTemplate(before, { x: 500.4, y: 20.6 }, LABELS);
    if (!made.ok) throw new Error('refused');
    expect(made.doc.nodes.find(node => node.id === note.id)).toBe(note);
    expect(made.doc.nodes).toHaveLength(5);
    expect(before.nodes).toHaveLength(1);
    expect(made.doc.nodes.every(node => Number.isInteger(node.x) && Number.isInteger(node.y))).toBe(true);
    // The whole template is one entry in the undo stack.
    const history = pushEdit(startHistory(before), made.doc, null);
    expect(history.past).toHaveLength(1);
    expect(undo(history).doc).toBe(before);
  });

  it('adds nothing when the canvas is full', () => {
    const full: CanvasDoc = { nodes: Array.from({ length: CANVAS_MAX_NODES - 3 }, (_, index) => newNode('note', index, 0)), edges: [] };
    expect(firstLastFrameTemplate(full, { x: 0, y: 0 }, LABELS)).toEqual({ ok: false, reason: 'limit' });
  });
});
