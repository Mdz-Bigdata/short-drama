// Several pictures and clips wired to one video node in a single edit. Capability after NovaNova Studio's
// canvas batch connect (MIT); the plan is made with this project's own connection rules, which decide
// every edge and its role: nothing is connected that a hand-drawn connection would be refused.
import { CONNECTED_GAP, findFreeSpot } from './canvasConnectedPlacement';
import { CANVAS_MAX_EDGES, CANVAS_MAX_NODES, boundsOf, clampCoord } from './canvasGeometry';
import { connect, newNode, outputType, type ConnectResult } from './canvasGraph';
import { nodeTitle } from './canvasLabels';
import type { CanvasDoc, CanvasEdge, CanvasNode } from './canvasTypes';

export type SkipReason = Extract<ConnectResult, { ok: false }>['reason'] | '连线上限';

export interface BatchConnectPlan {
  doc: CanvasDoc;
  targetId: string;
  /** The edges added, in the order the sources were taken: left to right, then top to bottom. */
  connected: CanvasEdge[];
  skipped: Array<{ sourceId: string; reason: SkipReason }>;
  /** Set when the target was made by this plan. */
  created?: CanvasNode;
}

/** The selected nodes that hand on a picture or a clip, left to right and then top to bottom. */
export function batchSources(doc: CanvasDoc, ids: Iterable<string>): CanvasNode[] {
  const chosen = new Set(ids);
  return doc.nodes
    .filter(node => {
      if (!chosen.has(node.id)) return false;
      const produced = outputType(node);
      return produced === 'image' || produced === 'video';
    })
    .sort((a, b) => a.x - b.x || a.y - b.y || a.id.localeCompare(b.id));
}

/** Whether the selection is one to offer the action for: two or more pictures or clips. */
export function canBatchConnect(doc: CanvasDoc, ids: Iterable<string>): boolean {
  return batchSources(doc, ids).length >= 2;
}

export interface VideoTarget {
  id: string;
  label: string;
  /** How many connections already come into it. */
  inputs: number;
}

/** The video nodes on the board, as the picker lists them: top to bottom, then left to right. */
export function videoTargets(doc: CanvasDoc): VideoTarget[] {
  return doc.nodes
    .filter(node => node.kind === 'video_gen')
    .sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id))
    .map(node => ({ id: node.id, label: nodeTitle(node), inputs: doc.edges.filter(edge => edge.target === node.id).length }));
}

/**
 * Connect every source to `targetId`, in order. A connection the rules refuse (already there, a loop,
 * the target itself, nothing to hand on) is skipped and named; the rest are made with the roles the
 * rules give them. Each connection is checked against the document as the earlier ones left it.
 */
export function planBatchConnect(doc: CanvasDoc, sourceIds: Iterable<string>, targetId: string): BatchConnectPlan {
  let next = doc;
  const connected: CanvasEdge[] = [];
  const skipped: BatchConnectPlan['skipped'] = [];
  for (const source of batchSources(doc, sourceIds)) {
    // A selected video node picked as the target is the target, not one more source.
    if (source.id === targetId) continue;
    if (next.edges.length >= CANVAS_MAX_EDGES) {
      skipped.push({ sourceId: source.id, reason: '连线上限' });
      continue;
    }
    const wired = connect(next, source.id, targetId);
    if (!wired.ok) {
      skipped.push({ sourceId: source.id, reason: wired.reason });
      continue;
    }
    connected.push(wired.edge);
    next = { ...next, edges: [...next.edges, wired.edge] };
  }
  return { doc: next, targetId, connected, skipped };
}

/** The same, to a video node made for it: to the right of the selection, level with its middle, clear of what is there. */
export function planBatchConnectNew(doc: CanvasDoc, sourceIds: Iterable<string>, label?: string): BatchConnectPlan | null {
  const sources = batchSources(doc, sourceIds);
  const box = boundsOf(sources);
  if (!box || doc.nodes.length >= CANVAS_MAX_NODES) return null;
  const draft = newNode('video_gen', 0, 0, label ? { label } : {});
  const preferred = { x: box.x + box.width + CONNECTED_GAP, y: box.y + box.height / 2 - draft.height / 2 };
  const at = findFreeSpot(doc.nodes.filter(node => node.kind !== 'group'), preferred, draft, ['right']);
  const created: CanvasNode = { ...draft, x: clampCoord(Math.round(at.x)), y: clampCoord(Math.round(at.y)) };
  const plan = planBatchConnect({ ...doc, nodes: [...doc.nodes, created] }, sources.map(node => node.id), created.id);
  return { ...plan, created };
}
