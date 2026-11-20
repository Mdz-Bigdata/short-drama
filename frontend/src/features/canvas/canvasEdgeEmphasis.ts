import type { CanvasEdge } from './canvasTypes';

/**
 * How strongly one connection is drawn, given what is selected.
 *
 * With a node selected, the connections that touch it stand out and every other one recedes, so what
 * feeds a node and what it feeds can be read at a glance on a crowded canvas; with nothing selected (or
 * only connections selected) every line is drawn as usual. The idea of lifting the active node's
 * connections and dimming the rest follows AID Studio's workflow canvas (MIT); the code is this project's.
 */
export type EdgeEmphasis = 'plain' | 'linked' | 'dim';

export function edgeEmphasis(edge: Pick<CanvasEdge, 'id' | 'source' | 'target'>, selection: ReadonlySet<string>, edgeSelection: ReadonlySet<string>): EdgeEmphasis {
  if (!selection.size) return 'plain';
  if (selection.has(edge.source) || selection.has(edge.target)) return 'linked';
  // A connection picked by hand stays readable even when it touches none of the selected nodes.
  return edgeSelection.has(edge.id) ? 'plain' : 'dim';
}

/** The arrowhead a connection ends in: one per colour the line itself may take. */
export function edgeMarker(kind: CanvasEdge['kind'], selected: boolean): string {
  if (selected) return 'cn-arrow-selected';
  if (kind === 'reference') return 'cn-arrow-reference';
  if (kind === 'dependency') return 'cn-arrow-dependency';
  return 'cn-arrow';
}

export const EDGE_MARKERS = ['cn-arrow', 'cn-arrow-reference', 'cn-arrow-dependency', 'cn-arrow-selected'] as const;
