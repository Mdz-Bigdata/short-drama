// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Rect } from './canvasTypes';
import { distanceToView, mountQueue, useProgressiveMount, MOUNT_BATCH_SIZE } from './useProgressiveMount';

function fakeFrames() {
  let next = 1;
  const pending = new Map<number, FrameRequestCallback>();
  let clock = 0;
  let tick = 0;
  return {
    raf: (callback: FrameRequestCallback) => { const id = next++; pending.set(id, callback); return id; },
    cancelRaf: (id: number) => { pending.delete(id); },
    /** Each read of the clock advances it by `tick` ms. */
    now: () => (clock += tick),
    setTick: (ms: number) => { tick = ms; },
    pending: () => pending.size,
    step() {
      const callbacks = [...pending.values()];
      pending.clear();
      act(() => { for (const callback of callbacks) callback(clock); });
    },
  };
}

const VIEW: Rect = { x: 0, y: 0, width: 1000, height: 800 };
// Candidate i sits i * 100 world units right of the view.
const rects = new Map<string, Rect>(Array.from({ length: 40 }, (_, i) => [`n${i}`, { x: 1000 + i * 100, y: 0, width: 50, height: 50 }]));
rects.set('on1', { x: 10, y: 10, width: 50, height: 50 });
rects.set('on2', { x: 200, y: 10, width: 50, height: 50 });
const rectOf = (id: string) => rects.get(id);

describe('progressive mount', () => {
  it('measures distance to the view and queues the nearest first', () => {
    expect(distanceToView({ x: 10, y: 10, width: 5, height: 5 }, VIEW)).toBe(0);
    expect(distanceToView({ x: 1300, y: 1200, width: 5, height: 5 }, VIEW)).toBe(500);
    expect(mountQueue(['n5', 'on1', 'n1', 'gone', 'n3'], id => id === 'on1', rectOf, VIEW)).toEqual(['n1', 'n3', 'n5', 'gone']);
  });

  it('mounts on-screen nodes at once and off-screen ones at most 12 a frame, nearest first', () => {
    const frames = fakeFrames();
    const offscreen = Array.from({ length: 30 }, (_, i) => `n${29 - i}`);
    const candidates = ['on1', ...offscreen, 'on2'];
    const immediate = new Set(['on1', 'on2']);
    const { result } = renderHook(() => useProgressiveMount(candidates, immediate, rectOf, VIEW, frames));

    expect(result.current.ids).toEqual(['on1', 'on2']);
    frames.step();
    expect(result.current.ids).toHaveLength(2 + MOUNT_BATCH_SIZE);
    expect(result.current.mounted.has('n0')).toBe(true);
    expect(result.current.mounted.has('n11')).toBe(true);
    expect(result.current.mounted.has('n12')).toBe(false);
    frames.step();
    expect(result.current.ids).toHaveLength(2 + 24);
    frames.step();
    expect(result.current.ids).toHaveLength(32);
    expect(result.current.ids).toEqual(candidates);
    expect(frames.pending()).toBe(0);
  });

  it('stops a frame early once 4ms are spent', () => {
    const frames = fakeFrames();
    frames.setTick(1.5);
    const candidates = Array.from({ length: 20 }, (_, i) => `n${i}`);
    const { result } = renderHook(() => useProgressiveMount(candidates, new Set<string>(), rectOf, VIEW, frames));
    frames.step();
    // The first node is always taken; the clock then reads 1.5ms on per check: +1.5 and +3 pass, +4.5 stops.
    expect(result.current.ids).toEqual(['n0', 'n1', 'n2']);
  });

  it('keeps nodes that were on screen mounted after they scroll off, and drops ones no longer candidates', () => {
    const frames = fakeFrames();
    let props = { candidates: ['on1', 'n0'], immediate: new Set(['on1', 'n0']) };
    const { result, rerender } = renderHook(() => useProgressiveMount(props.candidates, props.immediate, rectOf, VIEW, frames));
    frames.step();
    props = { candidates: ['on1', 'n0', 'n1'], immediate: new Set(['on1']) };
    rerender();
    expect(result.current.ids).toEqual(['on1', 'n0']);
    frames.step();
    expect(result.current.ids).toEqual(['on1', 'n0', 'n1']);
    props = { candidates: ['on1'], immediate: new Set(['on1']) };
    rerender();
    expect(result.current.ids).toEqual(['on1']);
  });

  it('cancels its pending frame on unmount', () => {
    const frames = fakeFrames();
    const { unmount } = renderHook(() => useProgressiveMount(['n0'], new Set<string>(), rectOf, VIEW, frames));
    expect(frames.pending()).toBe(1);
    unmount();
    expect(frames.pending()).toBe(0);
  });
});
