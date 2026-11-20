// The crop rectangle's arithmetic, with no DOM. Capability after NovaNova Studio's canvas crop (MIT);
// written for this project: the rectangle is in 0–1 units of the picture, which is what the server cuts by.

/** A rectangle in 0–1 units of the picture: `x`, `y` its top-left corner, `w`, `h` its size. */
export interface CropRect { x: number; y: number; w: number; h: number }

/** No edge of a crop is shorter than this share of the picture (the server refuses less). */
export const MIN_CROP_EDGE = 0.06;

export type CropHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
export const CROP_HANDLES: readonly CropHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

/** Shapes a crop can be held to; `ratio` is width over height in pixels, null for any shape. */
export const CROP_ASPECTS = [
  { id: 'free', ratio: null },
  { id: '1:1', ratio: 1 },
  { id: '9:16', ratio: 9 / 16 },
  { id: '16:9', ratio: 16 / 9 },
  { id: '4:3', ratio: 4 / 3 },
  { id: '3:4', ratio: 3 / 4 },
] as const;
export type CropAspectId = typeof CROP_ASPECTS[number]['id'];

export const DEFAULT_CROP: CropRect = { x: 0.1, y: 0.1, w: 0.8, h: 0.8 };

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), Math.max(low, high));
const tidy = (value: number) => Math.round(value * 1e6) / 1e6;

/** The same rectangle to six places: what is shown, compared and sent. */
export function roundRect(rect: CropRect): CropRect {
  return { x: tidy(rect.x), y: tidy(rect.y), w: tidy(rect.w), h: tidy(rect.h) };
}

/** Inside the picture and no smaller than the smallest crop. */
export function clampRect(rect: CropRect): CropRect {
  const w = clamp(rect.w, MIN_CROP_EDGE, 1);
  const h = clamp(rect.h, MIN_CROP_EDGE, 1);
  return roundRect({ x: clamp(rect.x, 0, 1 - w), y: clamp(rect.y, 0, 1 - h), w, h });
}

/** Slide the rectangle; it stops at the picture's edges and keeps its size. */
export function moveRect(rect: CropRect, dx: number, dy: number): CropRect {
  return roundRect({ ...rect, x: clamp(rect.x + dx, 0, 1 - rect.w), y: clamp(rect.y + dy, 0, 1 - rect.h) });
}

/**
 * A pixel shape as a ratio of the rectangle's own units: a 1:1 crop of a 2:1 picture is half as
 * wide (in units) as it is tall. Null when the picture's size is not known yet.
 */
export function unitRatio(ratio: number | null, natural: { width: number; height: number } | null): number | null {
  if (!ratio || !natural || !(natural.width > 0) || !(natural.height > 0)) return null;
  return ratio / (natural.width / natural.height);
}

/** Whether a crop of this shape can be at least the smallest crop on both sides. */
export function aspectFits(ratio: number | null): boolean {
  if (!ratio) return true;
  return Math.min(1, ratio) >= MIN_CROP_EDGE && Math.min(1, 1 / ratio) >= MIN_CROP_EDGE;
}

/** The narrowest a locked rectangle may be so that neither side goes under the smallest crop. */
function minWidth(ratio: number) {
  return Math.max(MIN_CROP_EDGE, MIN_CROP_EDGE * ratio);
}

/** Reshape to `ratio` (in units) about the rectangle's centre: the largest such shape inside it, grown to the minimum if need be. */
export function fitAspect(rect: CropRect, ratio: number | null): CropRect {
  if (!ratio || !aspectFits(ratio)) return clampRect(rect);
  const widest = Math.min(1, ratio);
  const w = clamp(Math.min(rect.w, rect.h * ratio), minWidth(ratio), widest);
  const h = w / ratio;
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  return roundRect({ x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h });
}

/**
 * Drag one handle by (dx, dy) units. The opposite edge or corner stays put; the rectangle stops at
 * the picture's edges and at the smallest crop. With `ratio` (in units) the shape is kept: a corner
 * follows the horizontal drag, a side handle grows the other dimension evenly about its middle.
 */
export function resizeRect(rect: CropRect, handle: CropHandle, dx: number, dy: number, ratio: number | null = null): CropRect {
  const west = handle.includes('w');
  const east = handle.includes('e');
  const north = handle.includes('n');
  const south = handle.includes('s');
  let left = rect.x;
  let right = rect.x + rect.w;
  let top = rect.y;
  let bottom = rect.y + rect.h;

  if (!ratio || !aspectFits(ratio)) {
    if (west) left = clamp(left + dx, 0, right - MIN_CROP_EDGE);
    if (east) right = clamp(right + dx, left + MIN_CROP_EDGE, 1);
    if (north) top = clamp(top + dy, 0, bottom - MIN_CROP_EDGE);
    if (south) bottom = clamp(bottom + dy, top + MIN_CROP_EDGE, 1);
    return roundRect({ x: left, y: top, w: right - left, h: bottom - top });
  }

  const least = minWidth(ratio);
  if ((west || east) && (north || south)) {
    // A corner: the opposite corner is the anchor, and the room from it to the picture's edge is the limit.
    const anchorX = west ? right : left;
    const anchorY = north ? bottom : top;
    const roomX = west ? anchorX : 1 - anchorX;
    const roomY = north ? anchorY : 1 - anchorY;
    const w = clamp(rect.w + (west ? -dx : dx), least, Math.min(roomX, roomY * ratio));
    const h = w / ratio;
    return roundRect({ x: west ? anchorX - w : anchorX, y: north ? anchorY - h : anchorY, w, h });
  }
  if (west || east) {
    const anchorX = west ? right : left;
    const cy = (top + bottom) / 2;
    const w = clamp(rect.w + (west ? -dx : dx), least, Math.min(west ? anchorX : 1 - anchorX, 2 * Math.min(cy, 1 - cy) * ratio));
    const h = w / ratio;
    return roundRect({ x: west ? anchorX - w : anchorX, y: cy - h / 2, w, h });
  }
  const anchorY = north ? bottom : top;
  const cx = (left + right) / 2;
  const h = clamp(rect.h + (north ? -dy : dy), least / ratio, Math.min(north ? anchorY : 1 - anchorY, (2 * Math.min(cx, 1 - cx)) / ratio));
  const w = h * ratio;
  return roundRect({ x: cx - w / 2, y: north ? anchorY - h : anchorY, w, h });
}

/** The crop in pixels of the picture, as the server will cut it. */
export function cropPixels(rect: CropRect, natural: { width: number; height: number }): { width: number; height: number } {
  const left = Math.round(rect.x * natural.width);
  const top = Math.round(rect.y * natural.height);
  return {
    width: Math.max(1, Math.round((rect.x + rect.w) * natural.width) - left),
    height: Math.max(1, Math.round((rect.y + rect.h) * natural.height) - top),
  };
}
