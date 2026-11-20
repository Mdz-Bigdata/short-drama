// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-selection.ts.
import { contains, intersects } from './canvasGeometry';
import type { CanvasNode, Rect } from './canvasTypes';

/** Dragged rightwards a marquee takes what it wholly holds; dragged leftwards, whatever it touches. */
export type MarqueeMode = 'contain' | 'intersect';

/** How a click or marquee changes what was selected when it began. */
export type SelectionStrategy = 'replace' | 'add' | 'toggle' | 'subtract';

export interface SelectionModifiers {
  shift?: boolean;
  alt?: boolean;
  meta?: boolean;
  ctrl?: boolean;
}

/** Anything that can narrow the nodes worth testing against a rectangle, such as a spatial index. */
export interface MarqueeIndex {
  candidates(rect: Rect): Iterable<CanvasNode>;
}

export function marqueeMode(startX: number, currentX: number): MarqueeMode {
  return currentX >= startX ? 'contain' : 'intersect';
}

/** Alt subtracts, ⌘/Ctrl toggles, Shift adds; with several held the stronger one wins in that order. */
export function selectionStrategy(modifiers: SelectionModifiers): SelectionStrategy {
  if (modifiers.alt) return 'subtract';
  if (modifiers.meta || modifiers.ctrl) return 'toggle';
  if (modifiers.shift) return 'add';
  return 'replace';
}

/** The selection after `hits`, worked out against the selection as it stood when the gesture began. */
export function applySelection(current: ReadonlySet<string>, hits: Iterable<string>, modifiers: SelectionModifiers | SelectionStrategy): Set<string> {
  const strategy = typeof modifiers === 'string' ? modifiers : selectionStrategy(modifiers);
  const list = [...hits];
  if (strategy === 'replace') return new Set(list);
  const next = new Set(current);
  for (const id of list) {
    if (strategy === 'add') next.add(id);
    else if (strategy === 'subtract') next.delete(id);
    else if (next.has(id)) next.delete(id);
    else next.add(id);
  }
  return next;
}

/** What a live marquee would add and drop, so the surface can preview it without rebuilding the selection. */
export function selectionPreview(current: ReadonlySet<string>, hits: ReadonlySet<string>, modifiers: SelectionModifiers | SelectionStrategy) {
  const next = applySelection(current, hits, modifiers);
  const adding = new Set([...next].filter(id => !current.has(id)));
  const removing = new Set([...current].filter(id => !next.has(id)));
  return { adding, removing };
}

export function marqueeHitsNode(rect: Rect, node: Rect & { kind?: CanvasNode['kind'] }, mode: MarqueeMode) {
  // A group frame is large and sits behind its contents: it joins only when wholly inside, in either mode,
  // so a marquee drawn within a frame means what the frame holds.
  if (mode === 'contain' || node.kind === 'group') return contains(rect, node);
  return intersects(rect, node);
}

/** Ids of the nodes a marquee takes, in drawing order; nodes in `hidden` (inside a collapsed group) never count. */
export function marqueeHits(source: readonly CanvasNode[] | MarqueeIndex, rect: Rect, mode: MarqueeMode, hidden?: ReadonlySet<string>): string[] {
  const nodes = Array.isArray(source) ? source : [...(source as MarqueeIndex).candidates(rect)];
  return (nodes as readonly CanvasNode[]).filter(node => !hidden?.has(node.id) && marqueeHitsNode(rect, node, mode)).map(node => node.id);
}
