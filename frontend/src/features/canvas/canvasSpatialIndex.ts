// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-spatial-index.ts and canvas-layout-snapshot.ts.
import type { CanvasNode, Rect } from './canvasTypes';

export interface SpatialItem {
  id: string;
  rect: Rect;
}

export interface SpatialQueryOptions {
  /**
   * Stop after this many hits. The hits are still returned in insertion order, but with a limit
   * they are the first ones met walking the grid cells, not necessarily the first ones inserted.
   */
  limit?: number;
  /** Filled with how many candidates the query examined (for tests and profiling). */
  stats?: { scanned: number };
}

export interface SpatialIndex {
  /** How many items were indexed (items with a non-finite or empty rect are skipped). */
  readonly size: number;
  /** Ids of the items that overlap `rect`, in insertion order. Touching edges do not count. */
  query(rect: Rect, options?: SpatialQueryOptions): string[];
  /** The indexed rect of an item. */
  rectOf(id: string): Rect | undefined;
}

export const SPATIAL_CELL_SIZE = 1024;
/** An item spanning more cells than this sits in a separate list that every query checks. */
export const MAX_ITEM_CELLS = 256;

interface Entry {
  id: string;
  left: number;
  top: number;
  right: number;
  bottom: number;
}

function toEntry(id: string, rect: Rect): Entry | null {
  const { x, y, width, height } = rect;
  if (!id || ![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  return { id, left: x, top: y, right: x + width, bottom: y + height };
}

function overlaps(entry: Entry, area: Entry) {
  return entry.right > area.left && entry.left < area.right && entry.bottom > area.top && entry.top < area.bottom;
}

/**
 * A uniform grid keeps a viewport query proportional to what is near the viewport rather than
 * to the whole canvas. Results come back in insertion order so stacking stays deterministic.
 */
export function buildSpatialIndex(items: readonly SpatialItem[], cellSize = SPATIAL_CELL_SIZE): SpatialIndex {
  const cell = Number.isFinite(cellSize) && cellSize > 0 ? cellSize : SPATIAL_CELL_SIZE;
  const entries: Entry[] = [];
  const byId = new Map<string, number>();
  const buckets = new Map<string, number[]>();
  const oversized: number[] = [];
  const span = (entry: Entry) => ({
    minColumn: Math.floor(entry.left / cell),
    maxColumn: Math.floor((entry.right - Number.EPSILON) / cell),
    minRow: Math.floor(entry.top / cell),
    maxRow: Math.floor((entry.bottom - Number.EPSILON) / cell),
  });

  for (const item of items) {
    const entry = toEntry(item.id, item.rect);
    if (!entry || byId.has(entry.id)) continue;
    const index = entries.push(entry) - 1;
    byId.set(entry.id, index);
    const { minColumn, maxColumn, minRow, maxRow } = span(entry);
    if ((maxColumn - minColumn + 1) * (maxRow - minRow + 1) > MAX_ITEM_CELLS) {
      oversized.push(index);
      continue;
    }
    for (let row = minRow; row <= maxRow; row += 1) {
      for (let column = minColumn; column <= maxColumn; column += 1) {
        const key = `${column}:${row}`;
        const bucket = buckets.get(key);
        if (bucket) bucket.push(index);
        else buckets.set(key, [index]);
      }
    }
  }

  return {
    size: entries.length,
    rectOf(id) {
      const index = byId.get(id);
      if (index === undefined) return undefined;
      const entry = entries[index];
      return { x: entry.left, y: entry.top, width: entry.right - entry.left, height: entry.bottom - entry.top };
    },
    query(rect, options) {
      const area = toEntry('query', rect);
      if (!area || !entries.length) return [];
      const limit = options?.limit !== undefined && Number.isFinite(options.limit) && options.limit > 0 ? Math.floor(options.limit) : Infinity;
      const seen = new Set<number>();
      let scanned = 0;
      const hits: number[] = [];
      const take = (index: number) => {
        if (seen.has(index)) return false;
        seen.add(index);
        scanned += 1;
        if (overlaps(entries[index], area)) hits.push(index);
        return hits.length >= limit;
      };
      const { minColumn, maxColumn, minRow, maxRow } = span(area);
      // A huge query (the whole canvas at 5%) walks fewer cells by walking the buckets instead.
      const cells = (maxColumn - minColumn + 1) * (maxRow - minRow + 1);
      let full = false;
      if (cells > buckets.size) {
        for (const [key, bucket] of buckets) {
          const split = key.indexOf(':');
          const column = Number(key.slice(0, split));
          const row = Number(key.slice(split + 1));
          if (column < minColumn || column > maxColumn || row < minRow || row > maxRow) continue;
          for (const index of bucket) if ((full = take(index))) break;
          if (full) break;
        }
      } else {
        outer: for (let row = minRow; row <= maxRow; row += 1) {
          for (let column = minColumn; column <= maxColumn; column += 1) {
            const bucket = buckets.get(`${column}:${row}`);
            if (!bucket) continue;
            for (const index of bucket) if ((full = take(index))) break outer;
          }
        }
      }
      if (!full) for (const index of oversized) if (take(index)) break;
      if (options?.stats) options.stats.scanned = scanned;
      return hits.sort((a, b) => a - b).map(index => entries[index].id);
    },
  };
}

/** True when two node lists have the same ids, order, kinds and boxes: only payloads may differ. */
export function sameGeometry(prev: readonly CanvasNode[], next: readonly CanvasNode[]) {
  if (prev === next) return true;
  if (prev.length !== next.length) return false;
  for (let index = 0; index < next.length; index += 1) {
    const a = prev[index];
    const b = next[index];
    if (a === b) continue;
    if (a.id !== b.id || a.kind !== b.kind || a.x !== b.x || a.y !== b.y || a.width !== b.width || a.height !== b.height) return false;
  }
  return true;
}

const nodeIndexes = new WeakMap<readonly CanvasNode[], SpatialIndex>();
let lastNodes: readonly CanvasNode[] | null = null;
let lastIndex: SpatialIndex | null = null;

/**
 * The spatial index of a node list, built once per array. A new array whose geometry matches the
 * last one built (a run finished, a prompt was edited) reuses that index instead of rebuilding it.
 */
export function buildNodeIndex(nodes: readonly CanvasNode[]): SpatialIndex {
  const cached = nodeIndexes.get(nodes);
  if (cached) return cached;
  const index = lastNodes && lastIndex && sameGeometry(lastNodes, nodes)
    ? lastIndex
    : buildSpatialIndex(nodes.map(node => ({ id: node.id, rect: node })));
  nodeIndexes.set(nodes, index);
  lastNodes = nodes;
  lastIndex = index;
  return index;
}
