// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDeskPlayback } from './useDeskPlayback';

describe('useDeskPlayback', () => {
  let frames: Array<(now: number) => void> = [];
  let now = 0;
  // One animation frame, `ms` after the last one.
  const tick = (ms: number) => act(() => {
    now += ms;
    const due = frames;
    frames = [];
    due.forEach(callback => callback(now));
  });

  beforeEach(() => {
    frames = [];
    now = 1000;
    vi.stubGlobal('requestAnimationFrame', (callback: (now: number) => void) => { frames.push(callback); return frames.length; });
    vi.stubGlobal('cancelAnimationFrame', () => { frames = []; });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('advances on whole frames, clamps a stalled frame, and stops at the end', () => {
    const { result } = renderHook(() => useDeskPlayback(2, 24, 'shot-1'));
    expect([result.current.time, result.current.playing]).toEqual([0, false]);
    act(() => result.current.play());
    tick(0);
    tick(50);
    expect(result.current.frame).toBe(1);             // 0.05 s is past frame 1 (0.0417 s) and short of frame 2
    expect(result.current.time).toBeCloseTo(1 / 24);
    tick(200);                                         // a slow frame is played in full: timing matters more than smoothness
    expect(result.current.frame).toBe(6);
    tick(5000);                                        // a tab that slept: worth a quarter of a second, not five
    expect(result.current.frame).toBe(12);
    for (let index = 0; index < 30; index += 1) tick(100);
    expect(result.current.playing).toBe(false);
    expect(result.current.frame).toBe(47);             // the last frame of 2 s at 24 fps
    // Play from the end starts over.
    act(() => result.current.play());
    expect([result.current.frame, result.current.playing]).toEqual([0, true]);
  });

  it('loops, steps, seeks and stops', () => {
    const { result } = renderHook(() => useDeskPlayback(1, 25, 'shot-1'));
    act(() => { result.current.setLoop(true); result.current.play(); });
    tick(0);
    for (let index = 0; index < 12; index += 1) tick(100);
    expect(result.current.playing).toBe(true);
    expect(result.current.time).toBeLessThan(1);
    act(() => result.current.pause());
    act(() => result.current.seek(0.5));
    expect(result.current.frame).toBe(12);
    act(() => result.current.step(1));
    expect(result.current.frame).toBe(13);
    act(() => result.current.step(-99));
    expect(result.current.frame).toBe(0);
    act(() => result.current.step(99));
    expect(result.current.frame).toBe(24);
    act(() => result.current.seek(Number.NaN));
    expect(result.current.time).toBe(0);
    act(() => result.current.stop());
    expect([result.current.time, result.current.playing]).toEqual([0, false]);
  });

  it('starts over on another shot and keeps the playhead inside a shortened one', () => {
    const { result, rerender } = renderHook(({ duration, shot }) => useDeskPlayback(duration, 24, shot), { initialProps: { duration: 5, shot: 'a' } });
    act(() => result.current.seek(4));
    rerender({ duration: 2, shot: 'a' });
    expect(result.current.frame).toBe(47);
    rerender({ duration: 2, shot: 'b' });
    expect(result.current.frame).toBe(0);
  });
});
