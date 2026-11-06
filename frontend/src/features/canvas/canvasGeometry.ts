import type { CanvasNode, Rect, Viewport } from './canvasTypes';

export const MIN_ZOOM = 0.05;
export const MAX_ZOOM = 2.5;
/** Below this zoom a node's body is unreadable anyway: draw a shell instead. */
export const SHELL_ZOOM = 0.35;
export const SNAP_DISTANCE = 6;

export function clampZoom(zoom: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

export function screenToWorld(view: Viewport, screenX: number, screenY: number) {
  return { x: (screenX - view.x) / view.zoom, y: (screenY - view.y) / view.zoom };
}

/** New view after zooming so the world point under the cursor stays under the cursor. */
export function zoomAt(view: Viewport, screenX: number, screenY: number, factor: number): Viewport {
  const zoom = clampZoom(view.zoom * factor);
  const scale = zoom / view.zoom;
  return { zoom, x: screenX - (screenX - view.x) * scale, y: screenY - (screenY - view.y) * scale };
}

export function visibleRect(view: Viewport, width: number, height: number): Rect {
  return { x: -view.x / view.zoom, y: -view.y / view.zoom, width: width / view.zoom, height: height / view.zoom };
}

export function inflate(rect: Rect, ratio: number): Rect {
  const dx = rect.width * ratio;
  const dy = rect.height * ratio;
  return { x: rect.x - dx, y: rect.y - dy, width: rect.width + dx * 2, height: rect.height + dy * 2 };
}

export function intersects(a: Rect, b: Rect) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

export function contains(outer: Rect, inner: Rect) {
  return inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;
}

export function normalizeRect(ax: number, ay: number, bx: number, by: number): Rect {
  return { x: Math.min(ax, bx), y: Math.min(ay, by), width: Math.abs(ax - bx), height: Math.abs(ay - by) };
}

export function boundsOf(rects: readonly Rect[]): Rect | null {
  if (!rects.length) return null;
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const rect of rects) {
    left = Math.min(left, rect.x);
    top = Math.min(top, rect.y);
    right = Math.max(right, rect.x + rect.width);
    bottom = Math.max(bottom, rect.y + rect.height);
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** The view that shows `rect` whole, with a margin. */
export function fitView(rect: Rect, width: number, height: number, margin = 60, maxZoom = 1): Viewport {
  const zoom = clampZoom(Math.min((width - margin * 2) / Math.max(rect.width, 1), (height - margin * 2) / Math.max(rect.height, 1), maxZoom));
  return { zoom, x: (width - rect.width * zoom) / 2 - rect.x * zoom, y: (height - rect.height * zoom) / 2 - rect.y * zoom };
}

export function centerOn(rect: Rect, view: Viewport, width: number, height: number): Viewport {
  return { zoom: view.zoom, x: width / 2 - (rect.x + rect.width / 2) * view.zoom, y: height / 2 - (rect.y + rect.height / 2) * view.zoom };
}

/** The node under a world point: groups only count when nothing else is there, and later nodes sit on top. */
export function nodeAt(nodes: readonly CanvasNode[], x: number, y: number, ignore?: ReadonlySet<string>): CanvasNode | null {
  let group: CanvasNode | null = null;
  for (let index = nodes.length - 1; index >= 0; index -= 1) {
    const node = nodes[index];
    if (ignore?.has(node.id)) continue;
    if (x < node.x || x > node.x + node.width || y < node.y || y > node.y + node.height) continue;
    if (node.kind !== 'group') return node;
    group = group ?? node;
  }
  return group;
}

export interface SnapGuide {
  axis: 'x' | 'y';
  /** World coordinate of the guide line. */
  at: number;
  from: number;
  to: number;
}

export interface SnapResult {
  dx: number;
  dy: number;
  guides: SnapGuide[];
}

const STOPS = [0, 0.5, 1];

/**
 * Pull a moved box onto the left/centre/right and top/middle/bottom lines of its neighbours.
 * Only the closest line per axis wins, so two nearby neighbours cannot make the box jitter between them.
 */
export function snapMove(moving: Rect, others: readonly Rect[], threshold: number): SnapResult {
  let bestX: { delta: number; at: number } | null = null;
  let bestY: { delta: number; at: number } | null = null;
  for (const other of others) {
    for (const own of STOPS) {
      for (const theirs of STOPS) {
        const x = other.x + other.width * theirs;
        const deltaX = x - (moving.x + moving.width * own);
        if (Math.abs(deltaX) <= threshold && (!bestX || Math.abs(deltaX) < Math.abs(bestX.delta))) bestX = { delta: deltaX, at: x };
        const y = other.y + other.height * theirs;
        const deltaY = y - (moving.y + moving.height * own);
        if (Math.abs(deltaY) <= threshold && (!bestY || Math.abs(deltaY) < Math.abs(bestY.delta))) bestY = { delta: deltaY, at: y };
      }
    }
  }
  const dx = bestX?.delta ?? 0;
  const dy = bestY?.delta ?? 0;
  const snapped = { x: moving.x + dx, y: moving.y + dy, width: moving.width, height: moving.height };
  const guides: SnapGuide[] = [];
  if (bestX) {
    const along = others.filter(other => STOPS.some(stop => Math.abs(other.x + other.width * stop - bestX!.at) < 0.01));
    const span = boundsOf([snapped, ...along])!;
    guides.push({ axis: 'x', at: bestX.at, from: span.y, to: span.y + span.height });
  }
  if (bestY) {
    const along = others.filter(other => STOPS.some(stop => Math.abs(other.y + other.height * stop - bestY!.at) < 0.01));
    const span = boundsOf([snapped, ...along])!;
    guides.push({ axis: 'y', at: bestY.at, from: span.x, to: span.x + span.width });
  }
  return { dx, dy, guides };
}

export function edgePath(ax: number, ay: number, bx: number, by: number) {
  const bend = Math.max(40, Math.abs(bx - ax) * 0.5);
  return `M ${ax} ${ay} C ${ax + bend} ${ay}, ${bx - bend} ${by}, ${bx} ${by}`;
}

/** A point on a minimap (an SVG drawn "xMidYMid meet") back to the world it shows. */
export function minimapToWorld(box: { width: number; height: number }, viewBox: Rect, localX: number, localY: number) {
  const scale = Math.min(box.width / viewBox.width, box.height / viewBox.height);
  const offsetX = (box.width - viewBox.width * scale) / 2;
  const offsetY = (box.height - viewBox.height * scale) / 2;
  return { x: viewBox.x + (localX - offsetX) / scale, y: viewBox.y + (localY - offsetY) / scale };
}
