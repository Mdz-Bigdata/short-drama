// Frame geometry for the DOM overlay on the lens view. Aspect-frame maths ported from
// jiguang132/storyai-3d-director-desk (MIT (c) 2026 YZ): fit the delivery frame inside the view,
// mask what falls outside, and hang the guides off the frame rather than off the view.

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export const ASPECT_PRESETS = ['9:16', '16:9', '1:1', '4:3', '3:4', '21:9', '2.39:1'] as const;
export const SAFE_MARGIN = 0.09;

/** "16:9", "2.39:1", "16：9", "1080x1920" → width / height; `null` when it is not a usable ratio. */
export function parseAspectRatio(value: string): number | null {
  const parts = value.trim().replace(/[：xX×/]/g, ':').split(':');
  if (parts.length !== 2) return null;
  const [w, h] = parts.map(Number);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
  const ratio = w / h;
  return ratio >= 0.1 && ratio <= 10 ? ratio : null;
}

/** The largest frame of `aspect` centred inside the view. */
export function fitFrame(viewWidth: number, viewHeight: number, aspect: number): Rect {
  if (!(viewWidth > 0) || !(viewHeight > 0) || !(aspect > 0)) return { x: 0, y: 0, width: 0, height: 0 };
  const wide = viewWidth / viewHeight > aspect;
  const width = wide ? viewHeight * aspect : viewWidth;
  const height = wide ? viewHeight : viewWidth / aspect;
  return { x: (viewWidth - width) / 2, y: (viewHeight - height) / 2, width, height };
}

/** The bars that mask everything outside the frame: pillar-boxes or letter-boxes, never both. */
export function letterboxBars(viewWidth: number, viewHeight: number, frame: Rect): Rect[] {
  const bars: Rect[] = [
    { x: 0, y: 0, width: viewWidth, height: frame.y },
    { x: 0, y: frame.y + frame.height, width: viewWidth, height: viewHeight - frame.y - frame.height },
    { x: 0, y: frame.y, width: frame.x, height: frame.height },
    { x: frame.x + frame.width, y: frame.y, width: viewWidth - frame.x - frame.width, height: frame.height },
  ];
  return bars.filter(bar => bar.width > 0.5 && bar.height > 0.5);
}

export function thirdsLines(frame: Rect): Segment[] {
  return [1 / 3, 2 / 3].flatMap(t => [
    { x1: frame.x + frame.width * t, y1: frame.y, x2: frame.x + frame.width * t, y2: frame.y + frame.height },
    { x1: frame.x, y1: frame.y + frame.height * t, x2: frame.x + frame.width, y2: frame.y + frame.height * t },
  ]);
}

export function safeFrame(frame: Rect, margin = SAFE_MARGIN): Rect {
  return {
    x: frame.x + frame.width * margin, y: frame.y + frame.height * margin,
    width: frame.width * (1 - margin * 2), height: frame.height * (1 - margin * 2),
  };
}

export function centerCross(frame: Rect, arm = 0.04): Segment[] {
  const cx = frame.x + frame.width / 2;
  const cy = frame.y + frame.height / 2;
  const reach = Math.min(frame.width, frame.height) * arm;
  return [{ x1: cx - reach, y1: cy, x2: cx + reach, y2: cy }, { x1: cx, y1: cy - reach, x2: cx, y2: cy + reach }];
}
