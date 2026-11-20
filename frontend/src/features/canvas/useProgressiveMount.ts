// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/pages/canvas/use-canvas-progressive-node-mount.ts.
import { useEffect, useMemo, useRef, useState } from 'react';

import type { Rect } from './canvasTypes';

/** Off-screen nodes mounted per animation frame at most. */
export const MOUNT_BATCH_SIZE = 12;
/** Milliseconds of a frame spent mounting at most. */
export const MOUNT_FRAME_BUDGET_MS = 4;

export interface ProgressiveMountOptions {
  raf?: (callback: FrameRequestCallback) => number;
  cancelRaf?: (handle: number) => void;
  now?: () => number;
  batchSize?: number;
  frameBudgetMs?: number;
}

export interface ProgressiveMount {
  /** The candidates mounted so far, in candidate order. */
  ids: string[];
  mounted: ReadonlySet<string>;
}

/** Distance in world units from a rect to the view; zero when they overlap. */
export function distanceToView(rect: Rect, view: Rect) {
  const dx = rect.x + rect.width < view.x ? view.x - (rect.x + rect.width) : rect.x > view.x + view.width ? rect.x - (view.x + view.width) : 0;
  const dy = rect.y + rect.height < view.y ? view.y - (rect.y + rect.height) : rect.y > view.y + view.height ? rect.y - (view.y + view.height) : 0;
  return Math.hypot(dx, dy);
}

/** The candidates still to mount, nearest to the view first. */
export function mountQueue(
  candidates: readonly string[],
  skip: (id: string) => boolean,
  rectOf: (id: string) => Rect | undefined,
  view: Rect,
): string[] {
  return candidates
    .filter(id => !skip(id))
    .map(id => {
      const rect = rectOf(id);
      return { id, distance: rect ? distanceToView(rect, view) : Infinity };
    })
    .sort((a, b) => a.distance - b.distance)
    .map(item => item.id);
}

const defaultRaf = (callback: FrameRequestCallback) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(callback) : 0);
const defaultCancel = (handle: number) => { if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle); };
const defaultNow = () => performance.now();

/**
 * Mount `immediate` nodes (the on-screen ones) at once and the other candidates a few per frame,
 * nearest to the view first, so panning into a dense area never mounts hundreds of cards in one frame.
 * Pass memoised `candidates` and `immediate`: a new identity restarts the queue.
 */
export function useProgressiveMount(
  candidates: readonly string[],
  immediate: ReadonlySet<string>,
  rectOf: (id: string) => Rect | undefined,
  view: Rect,
  options: ProgressiveMountOptions = {},
): ProgressiveMount {
  const [mounted, setMounted] = useState<ReadonlySet<string>>(() => new Set());
  const mountedRef = useRef(mounted);
  const rectOfRef = useRef(rectOf);
  const optionsRef = useRef(options);
  useEffect(() => {
    mountedRef.current = mounted;
    rectOfRef.current = rectOf;
    optionsRef.current = options;
  });

  const { x, y, width, height } = view;
  useEffect(() => {
    const { raf = defaultRaf, cancelRaf = defaultCancel, now = defaultNow, batchSize = MOUNT_BATCH_SIZE, frameBudgetMs = MOUNT_FRAME_BUDGET_MS } = optionsRef.current;
    const already = mountedRef.current;
    const queue = mountQueue(candidates, id => immediate.has(id) || already.has(id), rectOfRef.current, { x, y, width, height });
    // On-screen nodes join the mounted set too, so leaving the screen later does not unmount them.
    const unsynced = [...immediate].some(id => !already.has(id));
    if (!queue.length && !unsynced) return undefined;
    const candidateIds = new Set(candidates);
    let cursor = 0;
    let handle = 0;
    let cancelled = false;
    const frame = () => {
      if (cancelled) return;
      const startedAt = now();
      const additions: string[] = [];
      while (cursor < queue.length && additions.length < batchSize && (additions.length === 0 || now() - startedAt < frameBudgetMs)) {
        additions.push(queue[cursor]);
        cursor += 1;
      }
      setMounted(current => {
        const next = new Set<string>();
        for (const id of current) if (candidateIds.has(id)) next.add(id);
        for (const id of immediate) if (candidateIds.has(id)) next.add(id);
        for (const id of additions) next.add(id);
        return next.size === current.size && [...next].every(id => current.has(id)) ? current : next;
      });
      if (cursor < queue.length) handle = raf(frame);
    };
    handle = raf(frame);
    return () => {
      cancelled = true;
      cancelRaf(handle);
    };
  }, [candidates, immediate, x, y, width, height]);

  return useMemo(() => {
    const ids = candidates.filter(id => immediate.has(id) || mounted.has(id));
    return { ids, mounted: new Set(ids) };
  }, [candidates, immediate, mounted]);
}
