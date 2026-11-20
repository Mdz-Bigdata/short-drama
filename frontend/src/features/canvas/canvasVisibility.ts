// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-node-visibility.ts, canvas-render-budget.ts, canvas-connection-index.ts and web/src/pages/canvas/use-canvas-render-model.ts.
import { visibleRect } from './canvasGeometry';
import type { SpatialIndex } from './canvasSpatialIndex';
import type { CanvasEdge, CanvasNode, Rect, Viewport } from './canvasTypes';

/** Screen pixels around the view in which an off-screen node starts mounting. */
export const ENTER_PADDING = 192;
/** Screen pixels around the view in which a node already mounted stays mounted. */
export const RETAIN_PADDING = 384;
/** Off-screen edges drawn at most (edges touching a drawn node are always drawn). */
export const MAX_OFFSCREEN_EDGES = 5000;

export interface VisibilityRanges {
  /** What is on screen. */
  view: Rect;
  /** Where an unmounted node starts mounting. */
  enter: Rect;
  /** Where a mounted node stays mounted, so a node at the border does not flicker in and out. */
  retain: Rect;
}

function grow(rect: Rect, by: number): Rect {
  return { x: rect.x - by, y: rect.y - by, width: rect.width + by * 2, height: rect.height + by * 2 };
}

function overlaps(a: Rect, b: Rect) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

export function visibilityRanges(view: Viewport, width: number, height: number): VisibilityRanges {
  const zoom = Math.max(view.zoom, 1e-3);
  const visible = visibleRect(view, width, height);
  return { view: visible, enter: grow(visible, ENTER_PADDING / zoom), retain: grow(visible, RETAIN_PADDING / zoom) };
}

/** How many nodes may be mounted at this zoom; only off-screen nodes are cut to fit it. */
export function renderBudget(zoom: number) {
  if (zoom < 0.14) return 280;
  if (zoom < 0.28) return 420;
  return 720;
}

/** The nodes as a list or an id map; either is read once per identity, so pass a fresh one after a change. */
type NodeSource = readonly CanvasNode[] | ReadonlyMap<string, CanvasNode>;

interface Lookup {
  byId: Map<string, CanvasNode>;
  order: Map<string, number>;
}

const lookups = new WeakMap<object, Lookup>();

function lookup(nodes: NodeSource): Lookup {
  let cached = lookups.get(nodes);
  if (!cached) {
    const list: readonly CanvasNode[] = Array.isArray(nodes) ? nodes : [...(nodes as ReadonlyMap<string, CanvasNode>).values()];
    cached = { byId: new Map(list.map(node => [node.id, node])), order: new Map(list.map((node, index) => [node.id, index])) };
    lookups.set(nodes, cached);
  }
  return cached;
}

export interface VisibleNodesInput {
  index: SpatialIndex;
  nodes: NodeSource;
  view: Viewport;
  /** Surface size in screen pixels. */
  width: number;
  height: number;
  /** Nodes mounted last time: they are kept while inside the retain range. */
  mounted?: ReadonlySet<string>;
  /** Nodes that must stay mounted wherever they are (selected, being dragged or resized). */
  forced?: ReadonlySet<string>;
  /** Nodes not to draw at all (members of a collapsed group). */
  hidden?: ReadonlySet<string>;
  /** Override the zoom budget. */
  budget?: number;
}

const EMPTY = new Set<string>();

/**
 * The ids to mount, in canvas order. Every on-screen and forced node is kept; the budget only cuts
 * the off-screen buffer, and nodes already mounted win buffer places before newcomers.
 */
export function visibleNodeIds(input: VisibleNodesInput): string[] {
  const { index, view, width, height } = input;
  const mounted = input.mounted ?? EMPTY;
  const forced = input.forced ?? EMPTY;
  const hidden = input.hidden ?? EMPTY;
  const budget = input.budget ?? renderBudget(view.zoom);
  const { byId, order } = lookup(input.nodes);
  const ranges = visibilityRanges(view, width, height);

  const onScreen: string[] = [];
  const keptBuffer: string[] = [];
  const newBuffer: string[] = [];
  const consider = (id: string, isForced: boolean) => {
    if (hidden.has(id)) return;
    const node = byId.get(id);
    if (!node) return;
    if (isForced || overlaps(node, ranges.view)) onScreen.push(id);
    else if (mounted.has(id)) keptBuffer.push(id);
    else if (overlaps(node, ranges.enter)) newBuffer.push(id);
  };
  const candidates = index.query(ranges.retain);
  const seen = new Set<string>();
  for (const id of candidates) {
    seen.add(id);
    consider(id, forced.has(id));
  }
  for (const id of forced) if (!seen.has(id)) consider(id, true);

  const room = Math.max(0, budget - onScreen.length);
  const buffer = [...keptBuffer, ...newBuffer].slice(0, room);
  const ids = [...onScreen, ...buffer];
  return ids.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
}

type RectSource = ReadonlyMap<string, Rect> | ((id: string) => Rect | undefined);

/**
 * The edges worth drawing: every edge with an end on a drawn node, then up to `limit` others whose
 * box crosses the view (a long edge passing over the screen), in edge order.
 */
export function edgesToDraw(
  edges: readonly CanvasEdge[],
  visibleIds: ReadonlySet<string> | readonly string[],
  nodeRects: RectSource,
  view: Viewport,
  width: number,
  height: number,
  options: { limit?: number } = {},
): CanvasEdge[] {
  const visible = visibleIds instanceof Set ? visibleIds : new Set(visibleIds as readonly string[]);
  const rectOf = typeof nodeRects === 'function' ? nodeRects : (id: string) => nodeRects.get(id);
  const limit = options.limit ?? MAX_OFFSCREEN_EDGES;
  const range = visibilityRanges(view, width, height).enter;
  const drawn: CanvasEdge[] = [];
  let offscreen = 0;
  for (const edge of edges) {
    const source = rectOf(edge.source);
    const target = rectOf(edge.target);
    if (!source || !target) continue;
    if (visible.has(edge.source) || visible.has(edge.target)) {
      drawn.push(edge);
      continue;
    }
    if (offscreen >= limit) continue;
    const left = Math.min(source.x, target.x);
    const top = Math.min(source.y, target.y);
    const box = {
      x: left,
      y: top,
      width: Math.max(source.x + source.width, target.x + target.width) - left,
      height: Math.max(source.y + source.height, target.y + target.height) - top,
    };
    if (!overlaps(box, range)) continue;
    drawn.push(edge);
    offscreen += 1;
  }
  return drawn;
}
