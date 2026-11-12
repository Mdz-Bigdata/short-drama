// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-node-lod.ts.
import { SHELL_ZOOM } from './canvasGeometry';
import type { CanvasNode } from './canvasTypes';

/**
 * How much of a node to render:
 * - 'full': the whole card, editors and players included;
 * - 'preview': the card's frame, title and still thumbnail, with no editor or player mounted;
 * - 'shell': the kind-coloured box drawn from far away (NodeShell).
 */
export type NodeLod = 'full' | 'preview' | 'shell';

/** Zoomed out below this, the canvas enters overview. */
export const OVERVIEW_ENTER_ZOOM = 0.23;
/** Zoomed back in to this, it leaves overview. The gap keeps editors from mounting and unmounting at the border. */
export const OVERVIEW_LEAVE_ZOOM = 0.27;

/** Whether the canvas is in overview now, given whether it was the frame before. */
export function overviewMode(zoom: number, overviewWas: boolean) {
  return overviewWas ? zoom < OVERVIEW_LEAVE_ZOOM : zoom < OVERVIEW_ENTER_ZOOM;
}

export interface LodContext {
  zoom: number;
  /** On screen. */
  inView: boolean;
  /** Within the mount buffer around the screen. */
  inEnter: boolean;
  /** Its text or settings are being edited: never taken away under the person's hands. */
  editing?: boolean;
  hovered?: boolean;
  /** Selected, dragged or resized. */
  active?: boolean;
  /** Whether the canvas was in overview the frame before (see overviewMode). */
  overviewWas?: boolean;
}

/**
 * The detail to render a node at. Above SHELL_ZOOM an on-screen node is full, as before. Between
 * overview and SHELL_ZOOM it is a preview, full again when hovered or active. In overview it is a
 * shell, a preview when hovered or active. Off screen it is a preview inside the mount buffer and a
 * shell beyond it (always a shell in overview); an active node is never less than a preview.
 */
export function lodFor(node: Pick<CanvasNode, 'id' | 'kind'>, context: LodContext): NodeLod {
  if (context.editing) return 'full';
  const overview = overviewMode(context.zoom, Boolean(context.overviewWas));
  const attention = Boolean(context.hovered || context.active);
  if (context.inView) {
    if (overview) return attention ? 'preview' : 'shell';
    if (context.zoom < SHELL_ZOOM) return attention ? 'full' : 'preview';
    return 'full';
  }
  if (context.active) return 'preview';
  if (overview) return 'shell';
  // A group is only an outline: a shell carries all it has to show off screen.
  return context.inEnter && node.kind !== 'group' ? 'preview' : 'shell';
}
