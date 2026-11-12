// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-connected-node-placement.ts
// and web/src/lib/canvas/canvas-generation-layout.ts (free-spot search).
import { connect, newNode, type ConnectResult } from './canvasGraph';
import type { CanvasDoc, CanvasNode, NodeKind, NodePayload, Rect } from './canvasTypes';

/** Which side of the source the new node goes: right when dragged out of an output, left out of an input. */
export type ConnectSide = 'right' | 'left';

/** Room kept between a placed node and what it would otherwise touch. */
export const NODE_CLEARANCE = 36;
/** Distance from the source when no drop point is given. */
export const CONNECTED_GAP = 120;

type Point = { x: number; y: number };
type Size = { width: number; height: number };

/**
 * Top-left corner for a node made by dropping a connection: its near edge (left when it goes right of the
 * source, right when it goes left) sits on the drop point, vertically centred on it. A drop over the source
 * itself, or no drop at all, places it beside the source instead.
 */
export function placeConnectedNode(sourceRect: Rect, dropPoint: Point | null | undefined, size: Size, side: ConnectSide = 'right'): Point {
  const fallback = side === 'right' ? sourceRect.x + sourceRect.width + CONNECTED_GAP : sourceRect.x - CONNECTED_GAP;
  const point = dropPoint ?? { x: fallback, y: sourceRect.y + sourceRect.height / 2 };
  let nearX = point.x;
  if (side === 'right') nearX = Math.max(nearX, sourceRect.x + sourceRect.width + NODE_CLEARANCE);
  else nearX = Math.min(nearX, sourceRect.x - NODE_CLEARANCE);
  return { x: side === 'right' ? nearX : nearX - size.width, y: point.y - size.height / 2 };
}

function overlaps(at: Point, size: Size, other: Rect) {
  return !(at.x + size.width + NODE_CLEARANCE <= other.x || at.x >= other.x + other.width + NODE_CLEARANCE
    || at.y + size.height + NODE_CLEARANCE <= other.y || at.y >= other.y + other.height + NODE_CLEARANCE);
}

function slide(others: readonly Rect[], preferred: Point, size: Size, direction: 'down' | 'right'): Point {
  const at = { ...preferred };
  for (let attempt = 0; attempt <= others.length; attempt += 1) {
    const hits = others.filter(other => overlaps(at, size, other));
    if (!hits.length) return at;
    if (direction === 'down') at.y = Math.max(...hits.map(other => other.y + other.height + NODE_CLEARANCE));
    else at.x = Math.max(...hits.map(other => other.x + other.width + NODE_CLEARANCE));
  }
  return at;
}

/** The nearest clear spot at or below / right of `preferred`, whichever is the shorter move. */
export function findFreeSpot(others: readonly Rect[], preferred: Point, size: Size, directions: ReadonlyArray<'down' | 'right'> = ['down', 'right']): Point {
  const down = directions.includes('down') ? slide(others, preferred, size, 'down') : null;
  const right = directions.includes('right') ? slide(others, preferred, size, 'right') : null;
  if (!down || !right) return down ?? right ?? preferred;
  return down.y - preferred.y <= right.x - preferred.x ? down : right;
}

export type CreateConnectedResult =
  | { ok: true; doc: CanvasDoc; nodeId: string; node: CanvasNode }
  | { ok: false; reason: Extract<ConnectResult, { ok: false }>['reason'] };

/**
 * Make a node of `kind` where a connection was dropped and wire it to the source: source → new on the right,
 * new → source on the left. Refused (nothing added) for the same reasons canvasGraph.connect refuses.
 * Without a drop point the node goes beside the source, moved clear of what is already there.
 */
export function createConnectedNode(
  doc: CanvasDoc, sourceId: string, kind: NodeKind, dropPoint?: Point | null, side: ConnectSide = 'right', payload: NodePayload = {},
): CreateConnectedResult {
  const source = doc.nodes.find(node => node.id === sourceId);
  if (!source) return { ok: false, reason: '不接受' };
  const draft = newNode(kind, 0, 0, payload);
  let at = placeConnectedNode(source, dropPoint, draft, side);
  // Sliding right from the left side would run into the source, so that side only moves down.
  if (!dropPoint) at = findFreeSpot(doc.nodes.filter(node => node.kind !== 'group'), at, draft, side === 'right' ? ['down', 'right'] : ['down']);
  const node: CanvasNode = { ...draft, x: at.x, y: at.y };
  const withNode: CanvasDoc = { ...doc, nodes: [...doc.nodes, node] };
  const wired = side === 'right' ? connect(withNode, sourceId, node.id) : connect(withNode, node.id, sourceId);
  if (!wired.ok) return { ok: false, reason: wired.reason };
  return { ok: true, doc: { ...withNode, edges: [...doc.edges, wired.edge] }, nodeId: node.id, node };
}
