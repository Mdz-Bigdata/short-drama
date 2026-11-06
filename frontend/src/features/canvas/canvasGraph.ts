import type { CanvasDoc, CanvasEdge, CanvasNode, EdgeKind, NodeKind, NodeOutput, NodePayload, OutputType } from './canvasTypes';
import { boundsOf } from './canvasGeometry';
import { toolOf } from './canvasTools';

/** The same table as backend/app/core/studio_canvas.py: it decides; this refuses a drag at once. */
const INPUTS: Partial<Record<NodeKind, Partial<Record<OutputType, [EdgeKind, string]>>>> = {
  image_gen: { image: ['reference', 'ref_image'], style: ['reference', 'style'], text: ['dependency', 'prompt'], capture: ['reference', 'ref_capture'] },
  video_gen: {
    image: ['reference', 'ref_image'], video: ['reference', 'ref_video'], audio: ['reference', 'ref_audio'],
    style: ['reference', 'style'], text: ['dependency', 'prompt'], capture: ['reference', 'ref_capture'],
  },
  audio_gen: { text: ['dependency', 'prompt'] },
  video_compose: { video: ['dependency', 'clip'], capture: ['dependency', 'clip'], audio: ['dependency', 'soundtrack'] },
  style_ref: { image: ['reference', 'style_image'] },
  panorama: { image: ['reference', 'equirect'] },
  previz: { image: ['reference', 'blockout_image'] },
};

export const RUNNABLE_KINDS: ReadonlySet<NodeKind> = new Set(['image_gen', 'video_gen', 'audio_gen', 'video_compose', 'tool']);

export const DEFAULT_SIZES: Record<NodeKind, [number, number]> = {
  artifact: [260, 160], candidate: [260, 160], media: [260, 200], note: [240, 150], group: [480, 320], image_gen: [300, 320],
  video_gen: [320, 340], audio_gen: [280, 240], video_compose: [300, 240], style_ref: [240, 220], panorama: [340, 260], previz: [320, 300], tool: [300, 340],
};

export function makeId(prefix: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().replaceAll('-', '').slice(0, 16)
    : Math.random().toString(36).slice(2, 18);
  return `${prefix}_${random}`;
}

export function newNode(kind: NodeKind, x: number, y: number, payload: NodePayload = {}): CanvasNode {
  const [width, height] = DEFAULT_SIZES[kind];
  return { id: makeId('n'), kind, track: 'freezone', x, y, width, height, artifact_id: null, payload };
}

export function outputType(node: CanvasNode): OutputType | null {
  switch (node.kind) {
    case 'image_gen': case 'panorama': return 'image';
    case 'video_gen': case 'video_compose': return 'video';
    case 'audio_gen': return 'audio';
    case 'note': return 'text';
    case 'style_ref': return 'style';
    case 'previz': return 'capture';
    case 'group': return null;
    case 'tool': return toolOf(node)?.output ?? null;
    default: return node.payload.output?.medium ?? node.payload.medium ?? null;
  }
}

function inputsOf(target: CanvasNode) {
  return target.kind === 'tool' ? toolOf(target)?.inputs : INPUTS[target.kind];
}

export function acceptsInput(target: CanvasNode) {
  return Boolean(inputsOf(target));
}

export function createsCycle(edges: readonly CanvasEdge[], source: string, target: string) {
  const forward = new Map<string, string[]>();
  for (const edge of edges) forward.set(edge.source, [...(forward.get(edge.source) ?? []), edge.target]);
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const current = stack.pop()!;
    if (current === source) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(forward.get(current) ?? []));
  }
  return false;
}

export type ConnectResult = { ok: true; edge: CanvasEdge } | { ok: false; reason: '自连' | '无输出' | '不接受' | '成环' | '已连接' };

export function connect(doc: CanvasDoc, sourceId: string, targetId: string): ConnectResult {
  if (sourceId === targetId) return { ok: false, reason: '自连' };
  const source = doc.nodes.find(node => node.id === sourceId);
  const target = doc.nodes.find(node => node.id === targetId);
  if (!source || !target) return { ok: false, reason: '不接受' };
  const produced = outputType(source);
  if (!produced) return { ok: false, reason: '无输出' };
  const rule = inputsOf(target)?.[produced];
  if (!rule) return { ok: false, reason: '不接受' };
  if (doc.edges.some(edge => edge.source === sourceId && edge.target === targetId)) return { ok: false, reason: '已连接' };
  if (createsCycle(doc.edges, sourceId, targetId)) return { ok: false, reason: '成环' };
  return { ok: true, edge: { id: makeId('e'), source: sourceId, target: targetId, kind: rule[0], payload: { role: rule[1] } } };
}

/** Roles a person may choose for a connection; only an image feeding a video has a choice. */
export function roleChoices(source: CanvasNode, target: CanvasNode): string[] {
  if (target.kind !== 'video_gen') return [];
  const produced = outputType(source);
  if (produced === 'image') return ['ref_image', 'first_frame', 'last_frame'];
  // A clip may be the part before this one of the same continuous shot: then this one opens on its last frame.
  if (produced === 'video') return ['ref_video', 'continue_from'];
  return [];
}

export function labelOf(node: CanvasNode) {
  return node.payload.label || node.payload.title || '';
}

/** What a node shows and hands on: its active generation, else what it holds, else (pass-through kinds) its input. */
export function effectiveOutput(
  node: CanvasNode, doc: CanvasDoc, outputs: Readonly<Record<string, NodeOutput>>, seen: ReadonlySet<string> = new Set(),
): NodeOutput | null {
  const own = outputs[node.id] ?? node.payload.output;
  if (own?.url || own?.text) return own;
  if (node.kind !== 'style_ref' && node.kind !== 'panorama') return null;
  const visited = new Set(seen).add(node.id);
  for (const edge of doc.edges) {
    if (edge.target !== node.id || visited.has(edge.source)) continue;
    const source = doc.nodes.find(item => item.id === edge.source);
    const upstream = source && effectiveOutput(source, doc, outputs, visited);
    if (upstream?.medium === 'image') return upstream;
  }
  return null;
}

/** The picture a previz node would hand the desk's 白模 tab: the first image connected to it. */
export function upstreamImageUrl(node: CanvasNode, doc: CanvasDoc, outputs: Readonly<Record<string, NodeOutput>>): string | null {
  for (const edge of doc.edges) {
    if (edge.target !== node.id) continue;
    const source = doc.nodes.find(item => item.id === edge.source);
    if (!source) continue;
    const output = effectiveOutput(source, doc, outputs);
    if (output?.medium === 'image' && output.url) return output.url;
  }
  return null;
}

// ---------------------------------------------------------------- moves and groups

/** Everything that moves when these nodes are dragged: a group brings its members. */
export function movingIds(nodes: readonly CanvasNode[], selected: ReadonlySet<string>): Set<string> {
  const moving = new Set<string>();
  const groups = new Set(nodes.filter(node => node.kind === 'group' && selected.has(node.id)).map(node => node.id));
  for (const node of nodes) {
    if (selected.has(node.id) || (node.payload.groupId && groups.has(node.payload.groupId))) moving.add(node.id);
  }
  return moving;
}

/** Commit a drag. A dropped node joins the group its centre landed in and leaves the one it was dragged out of. */
export function moveNodes(doc: CanvasDoc, ids: ReadonlySet<string>, dx: number, dy: number): CanvasDoc {
  const moved = doc.nodes.map(node => (ids.has(node.id) ? { ...node, x: node.x + dx, y: node.y + dy } : node));
  const groups = moved.filter(node => node.kind === 'group');
  const nodes = moved.map(node => {
    if (!ids.has(node.id) || node.kind === 'group') return node;
    // Dragged along with its group, it stays in it.
    if (node.payload.groupId && ids.has(node.payload.groupId)) return node;
    const centerX = node.x + node.width / 2;
    const centerY = node.y + node.height / 2;
    const home = groups.find(group => centerX >= group.x && centerX <= group.x + group.width && centerY >= group.y && centerY <= group.y + group.height);
    if ((home?.id ?? undefined) === node.payload.groupId) return node;
    const payload = { ...node.payload };
    if (home) payload.groupId = home.id;
    else delete payload.groupId;
    return { ...node, payload };
  });
  return { ...doc, nodes };
}

export function groupNodes(doc: CanvasDoc, ids: ReadonlySet<string>, label: string): { doc: CanvasDoc; groupId: string } | null {
  const members = doc.nodes.filter(node => ids.has(node.id) && node.kind !== 'group');
  const box = boundsOf(members);
  if (!box || members.length < 2) return null;
  const group: CanvasNode = {
    ...newNode('group', box.x - 32, box.y - 56, { label }),
    width: box.width + 64,
    height: box.height + 88,
  };
  const nodes = doc.nodes.map(node => (ids.has(node.id) && node.kind !== 'group' ? { ...node, payload: { ...node.payload, groupId: group.id } } : node));
  // Groups draw first, so their frame stays behind what they hold.
  return { doc: { ...doc, nodes: [group, ...nodes] }, groupId: group.id };
}

export function ungroup(doc: CanvasDoc, groupIds: ReadonlySet<string>): CanvasDoc {
  const nodes = doc.nodes.filter(node => !(node.kind === 'group' && groupIds.has(node.id))).map(node => {
    if (!node.payload.groupId || !groupIds.has(node.payload.groupId)) return node;
    const payload = { ...node.payload };
    delete payload.groupId;
    return { ...node, payload };
  });
  return { ...doc, nodes };
}

export function deleteSelection(doc: CanvasDoc, nodeIds: ReadonlySet<string>, edgeIds: ReadonlySet<string> = new Set()): CanvasDoc {
  // Deleting a group frame frees what it held; those nodes are only deleted if they were selected too.
  const nodes = doc.nodes.filter(node => !nodeIds.has(node.id)).map(node => {
    if (!node.payload.groupId || !nodeIds.has(node.payload.groupId)) return node;
    const payload = { ...node.payload };
    delete payload.groupId;
    return { ...node, payload };
  });
  const edges = doc.edges.filter(edge => !edgeIds.has(edge.id) && !nodeIds.has(edge.source) && !nodeIds.has(edge.target));
  return { nodes, edges };
}

// ---------------------------------------------------------------- copy and paste

export interface CanvasClip {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

/** What a copy holds: the selection, its groups' members, the edges among them, and each result as it stands now. */
export function copySelection(doc: CanvasDoc, selected: ReadonlySet<string>, outputs: Readonly<Record<string, NodeOutput>>): CanvasClip | null {
  const ids = movingIds(doc.nodes, selected);
  if (!ids.size) return null;
  const nodes = doc.nodes.filter(node => ids.has(node.id)).map(node => {
    const output = outputs[node.id];
    return output ? { ...node, payload: { ...node.payload, output } } : node;
  });
  return { nodes, edges: doc.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)) };
}

/** Fresh ids throughout, so a paste never shares generation history or a commit with what it was copied from. */
export function pasteClip(doc: CanvasDoc, clip: CanvasClip, dx: number, dy: number): { doc: CanvasDoc; ids: string[] } {
  const mapping = new Map(clip.nodes.map(node => [node.id, makeId('n')]));
  const pasted = clip.nodes.map(node => {
    const payload: NodePayload = { ...node.payload };
    delete payload.committed;
    if (payload.groupId) {
      const group = mapping.get(payload.groupId);
      if (group) payload.groupId = group;
      else delete payload.groupId;
    }
    const keepsArtifact = node.kind === 'artifact' || node.kind === 'candidate';
    return { ...node, id: mapping.get(node.id)!, x: node.x + dx, y: node.y + dy, track: 'freezone' as const, artifact_id: keepsArtifact ? node.artifact_id : null, payload };
  });
  const edges = clip.edges.map(edge => ({ ...edge, id: makeId('e'), source: mapping.get(edge.source)!, target: mapping.get(edge.target)! }));
  const groups = pasted.filter(node => node.kind === 'group');
  const rest = pasted.filter(node => node.kind !== 'group');
  return { doc: { nodes: [...groups, ...doc.nodes, ...rest], edges: [...doc.edges, ...edges] }, ids: pasted.map(node => node.id) };
}

export function patchNode(doc: CanvasDoc, id: string, patch: Partial<CanvasNode>, payload?: Partial<NodePayload>): CanvasDoc {
  return {
    ...doc,
    nodes: doc.nodes.map(node => (node.id === id
      ? { ...node, ...patch, payload: payload ? { ...node.payload, ...payload } : node.payload }
      : node)),
  };
}
