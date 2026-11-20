import type { CanvasDoc, CanvasNode } from './canvasTypes';

export interface VersionDiff {
  added: CanvasNode[];
  removed: CanvasNode[];
  changed: CanvasNode[];
  edgesAdded: number;
  edgesRemoved: number;
}

function same(a: CanvasNode, b: CanvasNode): boolean {
  return a.kind === b.kind && a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
    && JSON.stringify(a.payload ?? {}) === JSON.stringify(b.payload ?? {});
}

/** What restoring `older` would change on `current`: nodes it brings back, takes away and changes, and edges. */
export function diffVersions(current: CanvasDoc, older: CanvasDoc): VersionDiff {
  const now = new Map(current.nodes.map(node => [node.id, node]));
  const then = new Map(older.nodes.map(node => [node.id, node]));
  const edgeKey = (edge: CanvasDoc['edges'][number]) => `${edge.source}>${edge.target}>${edge.payload?.role ?? ''}`;
  const nowEdges = new Set(current.edges.map(edgeKey));
  const thenEdges = new Set(older.edges.map(edgeKey));
  return {
    added: older.nodes.filter(node => !now.has(node.id)),
    removed: current.nodes.filter(node => !then.has(node.id)),
    changed: older.nodes.filter(node => now.has(node.id) && !same(node, now.get(node.id)!)),
    edgesAdded: [...thenEdges].filter(key => !nowEdges.has(key)).length,
    edgesRemoved: [...nowEdges].filter(key => !thenEdges.has(key)).length,
  };
}

/** The box that holds every node, for drawing a version small. */
export function boundsOf(nodes: CanvasNode[]): { x: number; y: number; width: number; height: number } {
  if (!nodes.length) return { x: 0, y: 0, width: 1, height: 1 };
  const left = Math.min(...nodes.map(node => node.x));
  const top = Math.min(...nodes.map(node => node.y));
  const right = Math.max(...nodes.map(node => node.x + node.width));
  const bottom = Math.max(...nodes.map(node => node.y + node.height));
  return { x: left, y: top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) };
}
