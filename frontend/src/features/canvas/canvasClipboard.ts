// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/pages/canvas/use-canvas-node-operations.ts.
//
// Upstream keeps the copied nodes in sessionStorage and puts only a marker on the system clipboard, so a
// paste prefers the canvas copy over a stale image left there. Here the clipboard text carries the whole
// clip behind a marker, so a copy also reaches another tab; sessionStorage is the fallback when the
// system clipboard is unavailable or refused.
import { connect, type CanvasClip } from './canvasGraph';
import type { CanvasDoc, CanvasEdge, CanvasNode } from './canvasTypes';

export const CLIP_STORAGE_KEY = 'novara.canvas.clip';
export const CLIP_MARKER = 'novara-canvas-clip';

const PASTABLE_MEDIA = /^(image|video|audio)\//;

export type PastePlan =
  | { kind: 'clip'; clip: CanvasClip }
  | { kind: 'files'; files: File[] }
  | { kind: 'text'; text: string };

export function serializeClip(clip: CanvasClip): string {
  return JSON.stringify({ [CLIP_MARKER]: 1, nodes: clip.nodes, edges: clip.edges });
}

/** Remember a copy in this tab and on the system clipboard; either may fail without the other. */
export function writeClip(clip: CanvasClip): void {
  const text = serializeClip(clip);
  try {
    window.sessionStorage.setItem(CLIP_STORAGE_KEY, text);
  } catch {
    // Large clips may exceed the storage quota; the system clipboard still carries them.
  }
  try {
    const pending = navigator.clipboard?.writeText(text);
    if (pending) pending.catch(() => undefined);
  } catch {
    // No clipboard permission or no secure context: sessionStorage keeps the copy for this tab.
  }
}

/** The clip this tab copied last, when the system clipboard could not be read. */
export function readStoredClip(): CanvasClip | null {
  try {
    return readClip(window.sessionStorage.getItem(CLIP_STORAGE_KEY));
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNode(value: unknown): value is CanvasNode {
  if (!isRecord(value)) return false;
  return typeof value.id === 'string' && typeof value.kind === 'string' && isRecord(value.payload)
    && [value.x, value.y, value.width, value.height].every(number => typeof number === 'number' && Number.isFinite(number));
}

function isEdge(value: unknown): value is CanvasEdge {
  return isRecord(value) && typeof value.id === 'string' && typeof value.source === 'string' && typeof value.target === 'string' && typeof value.kind === 'string';
}

/** A clip from our own marker text (or a paste event's data); anything else is not ours. */
export function readClip(source: DataTransfer | string | null | undefined): CanvasClip | null {
  const text = typeof source === 'string' ? source : source?.getData('text/plain');
  if (!text || !text.includes(CLIP_MARKER)) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(parsed) || parsed[CLIP_MARKER] !== 1 || !Array.isArray(parsed.nodes)) return null;
  const nodes = parsed.nodes.filter(isNode);
  if (!nodes.length) return null;
  const ids = new Set(nodes.map(node => node.id));
  const edges = (Array.isArray(parsed.edges) ? parsed.edges : [])
    .filter(isEdge)
    .map(edge => ({ ...edge, payload: isRecord(edge.payload) ? edge.payload : {} }))
    .filter(edge => ids.has(edge.source) && ids.has(edge.target));
  return { nodes, edges };
}

function pastedFiles(data: DataTransfer): File[] {
  const files = [...(data.files ?? [])];
  if (!files.length) {
    for (const item of [...(data.items ?? [])]) {
      if (item.kind !== 'file') continue;
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  return files.filter(file => PASTABLE_MEDIA.test(file.type));
}

/** What a paste should do: our own copy first, then pasted pictures, video or sound, then plain text. */
export function pastePlan(data: DataTransfer | null | undefined): PastePlan | null {
  if (!data) return null;
  const text = data.getData('text/plain');
  const clip = readClip(text);
  if (clip) return { kind: 'clip', clip };
  const files = pastedFiles(data);
  if (files.length) return { kind: 'files', files };
  if (text.trim()) return { kind: 'text', text };
  return null;
}

/** Old id → pasted id, from a clip and the ids `pasteClip` returned (same order). */
export function pasteIdMap(clip: CanvasClip, pastedIds: readonly string[]): Map<string, string> {
  return new Map(clip.nodes.map((node, index) => [node.id, pastedIds[index]]));
}

/**
 * Pasting on the canvas it was copied from: hang the copies on the same upstream nodes that fed the
 * originals but were not copied (copying just a result is the common case). An edge `connect` would
 * refuse is left out. On another canvas the upstream nodes are not there, so nothing is added.
 */
export function reconnectInbound(doc: CanvasDoc, clip: CanvasClip, idMap: ReadonlyMap<string, string>): CanvasDoc {
  const copied = new Set(clip.nodes.map(node => node.id));
  const present = new Set(doc.nodes.map(node => node.id));
  let next = doc;
  for (const edge of doc.edges) {
    if (!copied.has(edge.target) || copied.has(edge.source) || !present.has(edge.source)) continue;
    const target = idMap.get(edge.target);
    if (!target || !present.has(target)) continue;
    const result = connect(next, edge.source, target);
    if (!result.ok) continue;
    // Keep the original's kind and role (a first frame stays a first frame).
    const added: CanvasEdge = { ...result.edge, kind: edge.kind, payload: { ...edge.payload } };
    next = { ...next, edges: [...next.edges, added] };
  }
  return next;
}
