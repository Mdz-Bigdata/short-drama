// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-export.ts and web/src/types/canvas-export.ts.
//
// Upstream packs every referenced media file into a zip next to the manifest. This export is the
// manifest alone: pictures, clips and sound stay as the URLs the server already serves, so an import
// on another project still points at the original project's media (and shows nothing if that media
// is gone or not reachable from there).
import { t } from '../../i18n';
import { boundsOf } from './canvasGeometry';
import { DEFAULT_SIZES, makeId } from './canvasGraph';
import type { CanvasDoc, CanvasEdge, CanvasNode, EdgeKind, NodeKind, NodeOutput, NodePayload, Viewport } from './canvasTypes';

export const EXPORT_FORMAT = 'novara-canvas';
export const EXPORT_VERSION = 1;
/** Gap between what is on the canvas and what an import adds to its right. */
export const IMPORT_GAP = 120;

const NODE_KINDS: ReadonlySet<string> = new Set<NodeKind>([
  'artifact', 'candidate', 'media', 'note', 'group', 'image_gen', 'video_gen', 'audio_gen', 'video_compose', 'style_ref', 'panorama', 'previz', 'tool',
]);
const EDGE_KINDS: ReadonlySet<string> = new Set<EdgeKind>(['lineage', 'variant', 'continuity', 'dependency', 'reference']);

export interface CanvasExportManifest {
  format: typeof EXPORT_FORMAT;
  version: typeof EXPORT_VERSION;
  title: string;
  exported_at: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: Viewport | null;
}

export interface CanvasImport {
  title: string;
  doc: CanvasDoc;
  viewport: Viewport | null;
}

/**
 * The canvas as a JSON file. `outputs` (the board's current results) are written into each node, the
 * way a copy carries them, so the file shows what the canvas showed.
 */
export function exportCanvas(
  doc: CanvasDoc,
  options: { title: string; viewport?: Viewport | null; outputs?: Readonly<Record<string, NodeOutput>>; now?: Date },
): Blob {
  const outputs = options.outputs ?? {};
  const manifest: CanvasExportManifest = {
    format: EXPORT_FORMAT,
    version: EXPORT_VERSION,
    title: options.title,
    exported_at: (options.now ?? new Date()).toISOString(),
    nodes: doc.nodes.map(node => (outputs[node.id] ? { ...node, payload: { ...node.payload, output: outputs[node.id] } } : node)),
    edges: doc.edges,
    viewport: options.viewport ?? null,
  };
  return new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
}

/** A download name from the board title: no path separators or characters file systems refuse. */
export function exportFileName(title: string) {
  const printable = [...title].map(char => (char.charCodeAt(0) < 32 ? ' ' : char)).join('');
  const stem = printable.replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || t('画布');
  return `${stem}.novara-canvas.json`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function viewportOf(value: unknown): Viewport | null {
  if (!isRecord(value) || !finite(value.x) || !finite(value.y) || !finite(value.zoom) || value.zoom <= 0) return null;
  return { x: value.x, y: value.y, zoom: value.zoom };
}

/**
 * Read an exported canvas. Every node and edge gets a fresh id, so importing the same file twice (or
 * into the board it came from) never collides; group membership follows the new ids. Throws an Error
 * with a message to show when the file is not a canvas export.
 */
export function parseCanvasImport(text: string): CanvasImport {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(t('导入失败：文件不是有效的 JSON。'));
  }
  if (!isRecord(parsed) || parsed.format !== EXPORT_FORMAT) throw new Error(t('导入失败：这不是画布导出文件。'));
  if (!finite(parsed.version) || parsed.version > EXPORT_VERSION || parsed.version < 1) {
    throw new Error(t('导入失败：不支持的导出版本 {0}。', [String(parsed.version)]));
  }
  if (!Array.isArray(parsed.nodes) || (parsed.edges !== undefined && !Array.isArray(parsed.edges))) {
    throw new Error(t('导入失败：文件里缺少节点或连线列表。'));
  }

  const mapping = new Map<string, string>();
  const raw = parsed.nodes.map((value, index) => {
    const position = index + 1;
    if (!isRecord(value) || typeof value.id !== 'string' || !value.id) throw new Error(t('导入失败：第 {0} 个节点缺少编号。', [position]));
    if (typeof value.kind !== 'string' || !NODE_KINDS.has(value.kind)) throw new Error(t('导入失败：不认识的节点类型「{0}」。', [String(value.kind)]));
    if (!finite(value.x) || !finite(value.y)) throw new Error(t('导入失败：第 {0} 个节点缺少位置。', [position]));
    if (mapping.has(value.id)) throw new Error(t('导入失败：节点编号「{0}」重复。', [value.id]));
    mapping.set(value.id, makeId('n'));
    return value as Record<string, unknown> & { id: string; kind: NodeKind; x: number; y: number };
  });

  const nodes: CanvasNode[] = raw.map(value => {
    const payload: NodePayload = isRecord(value.payload) ? { ...value.payload } : {};
    // A commit belongs to the board it was made on.
    delete payload.committed;
    if (payload.groupId !== undefined) {
      const group = typeof payload.groupId === 'string' ? mapping.get(payload.groupId) : undefined;
      if (group) payload.groupId = group;
      else delete payload.groupId;
    }
    const [width, height] = DEFAULT_SIZES[value.kind];
    const keepsArtifact = (value.kind === 'artifact' || value.kind === 'candidate') && typeof value.artifact_id === 'string';
    return {
      id: mapping.get(value.id)!,
      kind: value.kind,
      track: 'freezone',
      x: value.x,
      y: value.y,
      width: finite(value.width) && value.width > 0 ? value.width : width,
      height: finite(value.height) && value.height > 0 ? value.height : height,
      artifact_id: keepsArtifact ? value.artifact_id as string : null,
      payload,
    };
  });

  const edges: CanvasEdge[] = [];
  for (const value of (parsed.edges ?? []) as unknown[]) {
    if (!isRecord(value)) continue;
    if (typeof value.kind !== 'string' || !EDGE_KINDS.has(value.kind)) throw new Error(t('导入失败：不认识的连线类型「{0}」。', [String(value.kind)]));
    const source = typeof value.source === 'string' ? mapping.get(value.source) : undefined;
    const target = typeof value.target === 'string' ? mapping.get(value.target) : undefined;
    // An edge to a node that is not in the file has nothing to hang on.
    if (!source || !target || source === target) continue;
    edges.push({ id: makeId('e'), source, target, kind: value.kind as EdgeKind, payload: isRecord(value.payload) ? { ...value.payload } : {} });
  }

  const title = typeof parsed.title === 'string' ? parsed.title : '';
  return { title, doc: { nodes, edges }, viewport: viewportOf(parsed.viewport) };
}

/** How far to shift an import so it lands to the right of what the canvas holds, top-aligned with it. */
export function importOffset(existing: readonly CanvasNode[], imported: readonly CanvasNode[]): { dx: number; dy: number } {
  const here = boundsOf(existing);
  const there = boundsOf(imported);
  if (!here || !there) return { dx: 0, dy: 0 };
  return { dx: here.x + here.width + IMPORT_GAP - there.x, dy: here.y - there.y };
}

/** Add an import (ids already fresh) to a canvas, shifted; groups go first so their frames stay behind. */
export function mergeImport(doc: CanvasDoc, imported: CanvasDoc, offset: { dx: number; dy: number }): { doc: CanvasDoc; ids: string[] } {
  const moved = imported.nodes.map(node => ({ ...node, x: node.x + offset.dx, y: node.y + offset.dy }));
  const groups = moved.filter(node => node.kind === 'group');
  const rest = moved.filter(node => node.kind !== 'group');
  return { doc: { nodes: [...groups, ...doc.nodes, ...rest], edges: [...doc.edges, ...imported.edges] }, ids: moved.map(node => node.id) };
}
