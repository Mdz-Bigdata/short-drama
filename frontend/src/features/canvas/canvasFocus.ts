// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/agent-canvas-focus.ts.
//
// When something other than the person's own hand changes the canvas (an agent, an import, another
// tab's save), find what changed and, only if it is out of sight, move the view to show it.
import { boundsOf, contains, fitView, visibleRect } from './canvasGeometry';
import type { CanvasDoc, CanvasNode, Rect, Viewport } from './canvasTypes';

/** How long changed nodes stay highlighted after the view moves to them. */
export const flashDurationMs = 1200;
/** Screen pixels a node must stay inside the edge to count as visible. */
export const FOCUS_MARGIN = 24;
/** Screen pixels around the framed nodes when the view has to move. */
export const FIT_MARGIN = 60;

/** JSON with sorted keys: a payload that comes back from the server with its keys reordered is unchanged. */
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function moved(before: CanvasNode, after: CanvasNode) {
  return before.x !== after.x || before.y !== after.y || before.width !== after.width || before.height !== after.height;
}

/** Nodes in `after` that are new, or whose place, size or payload differ from `before`. Deleted nodes do not count. */
export function changedNodeIds(before: CanvasDoc, after: CanvasDoc): string[] {
  const previous = new Map(before.nodes.map(node => [node.id, node]));
  const changed: string[] = [];
  for (const node of after.nodes) {
    const old = previous.get(node.id);
    if (!old) changed.push(node.id);
    else if (old !== node && (moved(old, node) || stable(old.payload) !== stable(node.payload))) changed.push(node.id);
  }
  return changed;
}

/**
 * The view that shows `rects`, or null when they are already wholly in sight (then the view is left
 * alone). The view never zooms in: past the current zoom, or past 100%.
 */
export function focusPlan(rects: readonly Rect[], view: Viewport, width: number, height: number): Viewport | null {
  const box = boundsOf(rects);
  if (!box || width <= 0 || height <= 0) return null;
  const inset = FOCUS_MARGIN / view.zoom;
  const seen = visibleRect(view, width, height);
  const safe: Rect = { x: seen.x + inset, y: seen.y + inset, width: seen.width - inset * 2, height: seen.height - inset * 2 };
  if (contains(safe, box)) return null;
  return fitView(box, width, height, FIT_MARGIN, Math.min(1, view.zoom));
}
