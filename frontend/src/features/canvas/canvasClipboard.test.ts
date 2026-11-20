// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CLIP_MARKER, CLIP_STORAGE_KEY, pasteIdMap, pastePlan, readClip, readStoredClip, reconnectInbound, serializeClip, writeClip } from './canvasClipboard';
import { copySelection, newNode, pasteClip, type CanvasClip } from './canvasGraph';
import type { CanvasDoc, CanvasEdge, CanvasNode, NodeKind } from './canvasTypes';

function node(id: string, kind: NodeKind, patch: Partial<CanvasNode> = {}): CanvasNode {
  return { ...newNode(kind, 0, 0), id, width: 100, height: 100, ...patch };
}

function edge(source: string, target: string, role?: string, kind: CanvasEdge['kind'] = 'reference'): CanvasEdge {
  return { id: `${source}-${target}`, source, target, kind, payload: { role } };
}

function transfer({ text = '', files = [] as File[], items = [] as File[] } = {}): DataTransfer {
  return {
    getData: (type: string) => (type === 'text/plain' ? text : ''),
    files,
    items: items.map(file => ({ kind: 'file', type: file.type, getAsFile: () => file })),
  } as unknown as DataTransfer;
}

const clip: CanvasClip = { nodes: [node('a', 'note', { payload: { text: 'hi' } }), node('b', 'image_gen')], edges: [edge('a', 'b', 'prompt', 'dependency')] };

afterEach(() => {
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe('writing and reading a clip', () => {
  it('stores the clip in this tab and on the system clipboard behind the marker', () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    writeClip(clip);
    const stored = window.sessionStorage.getItem(CLIP_STORAGE_KEY)!;
    expect(JSON.parse(stored)[CLIP_MARKER]).toBe(1);
    expect(writeText).toHaveBeenCalledWith(stored);
    expect(readStoredClip()).toEqual(clip);
  });

  it('swallows a refused or missing system clipboard', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: () => Promise.reject(new Error('denied')) } });
    expect(() => writeClip(clip)).not.toThrow();
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
    expect(() => writeClip(clip)).not.toThrow();
    expect(readStoredClip()?.nodes).toHaveLength(2);
  });

  it('keeps the system copy when this tab cannot store it', () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    expect(() => writeClip(clip)).not.toThrow();
    expect(writeText).toHaveBeenCalled();
    setItem.mockRestore();
  });

  it('only recognises our own marker', () => {
    expect(readClip(serializeClip(clip))).toEqual(clip);
    expect(readClip(transfer({ text: serializeClip(clip) }))).toEqual(clip);
    expect(readClip('hello')).toBeNull();
    expect(readClip(JSON.stringify({ nodes: clip.nodes }))).toBeNull();
    expect(readClip(JSON.stringify({ [CLIP_MARKER]: 2, nodes: clip.nodes }))).toBeNull();
    expect(readClip(`{"${CLIP_MARKER}": 1, broken`)).toBeNull();
    expect(readClip(null)).toBeNull();
  });

  it('drops malformed nodes and edges that point outside the clip', () => {
    const text = JSON.stringify({ [CLIP_MARKER]: 1, nodes: [...clip.nodes, { id: 'x' }], edges: [...clip.edges, edge('a', 'gone')] });
    const read = readClip(text)!;
    expect(read.nodes.map(item => item.id)).toEqual(['a', 'b']);
    expect(read.edges.map(item => item.id)).toEqual(['a-b']);
  });
});

describe('what a paste does', () => {
  const png = new File(['x'], 'a.png', { type: 'image/png' });
  const mp4 = new File(['x'], 'a.mp4', { type: 'video/mp4' });
  const pdf = new File(['x'], 'a.pdf', { type: 'application/pdf' });

  it('prefers our clip over files and text', () => {
    expect(pastePlan(transfer({ text: serializeClip(clip), files: [png] }))).toEqual({ kind: 'clip', clip });
  });

  it('takes pasted media and leaves other files out', () => {
    expect(pastePlan(transfer({ text: 'https://x/a.png', files: [png, pdf, mp4] }))).toEqual({ kind: 'files', files: [png, mp4] });
    expect(pastePlan(transfer({ items: [png] }))).toEqual({ kind: 'files', files: [png] });
  });

  it('falls back to text, and to nothing', () => {
    expect(pastePlan(transfer({ text: '  a line  ', files: [pdf] }))).toEqual({ kind: 'text', text: '  a line  ' });
    expect(pastePlan(transfer({ text: '   ' }))).toBeNull();
    expect(pastePlan(null)).toBeNull();
  });
});

describe('reconnecting pasted copies to their upstream', () => {
  const doc: CanvasDoc = {
    nodes: [node('img', 'image_gen'), node('prompt', 'note'), node('vid', 'video_gen'), node('sty', 'style_ref')],
    edges: [edge('img', 'vid', 'first_frame'), edge('prompt', 'vid', 'prompt', 'dependency'), edge('sty', 'img', 'style')],
  };

  it('hangs a copied result on the same upstream nodes, keeping the role', () => {
    const copied = copySelection(doc, new Set(['vid']), {})!;
    const pasted = pasteClip(doc, copied, 40, 40);
    const map = pasteIdMap(copied, pasted.ids);
    const next = reconnectInbound(pasted.doc, copied, map);
    const added = next.edges.slice(doc.edges.length);
    expect(added.map(item => [item.source, item.target, item.payload.role, item.kind])).toEqual([
      ['img', map.get('vid'), 'first_frame', 'reference'],
      ['prompt', map.get('vid'), 'prompt', 'dependency'],
    ]);
    expect(new Set(next.edges.map(item => item.id)).size).toBe(next.edges.length);
  });

  it('adds nothing for edges already inside the clip', () => {
    const copied = copySelection(doc, new Set(['img', 'vid']), {})!;
    const pasted = pasteClip(doc, copied, 40, 40);
    const next = reconnectInbound(pasted.doc, copied, pasteIdMap(copied, pasted.ids));
    const intoCopies = next.edges.filter(item => pasted.ids.includes(item.target));
    // img' -> vid' (from the clip), sty -> img' and prompt -> vid' (reconnected); not img -> vid'.
    expect(intoCopies.map(item => item.source).sort()).toEqual(['prompt', 'sty', pasted.ids[0]].sort());
  });

  it('adds nothing on another canvas, and skips what connect would refuse', () => {
    const copied = copySelection(doc, new Set(['vid']), {})!;
    const other = pasteClip({ nodes: [], edges: [] }, copied, 0, 0);
    expect(reconnectInbound(other.doc, copied, pasteIdMap(copied, other.ids)).edges).toEqual(other.doc.edges);

    // The upstream note became a group: a group has no output, so connect refuses and the edge is skipped.
    const changed: CanvasDoc = { ...doc, nodes: doc.nodes.map(item => (item.id === 'prompt' ? { ...item, kind: 'group' } : item)) };
    const pasted = pasteClip(changed, copied, 40, 40);
    const next = reconnectInbound(pasted.doc, copied, pasteIdMap(copied, pasted.ids));
    expect(next.edges.slice(changed.edges.length).map(item => item.source)).toEqual(['img']);
  });
});
