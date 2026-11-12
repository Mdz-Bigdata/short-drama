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
    expect(result.current.frame).toBe(48);             // the end of 2 s at 24 fps, where a move's last key sits
    expect(result.current.time).toBe(2);
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
    expect(result.current.frame).toBe(25);
    act(() => result.current.step(-1));
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
    expect(result.current.frame).toBe(48);
    rerender({ duration: 2, shot: 'b' });
    expect(result.current.frame).toBe(0);
    // The running clock went back with it: a step counts from the new shot's first frame.
    act(() => result.current.step(1));
    expect(result.current.frame).toBe(1);
  });

  it('reaches the end key of a shot that is not a whole number of frames long', () => {
    const { result } = renderHook(() => useDeskPlayback(2.5, 25, 'shot-1'));
    // A key at 2.5 s rounds to frame 63; a click on it seeks to that frame's time, just past the end.
    act(() => result.current.seek(63 / 25));
    expect([result.current.frame, result.current.time]).toEqual([63, 2.5]);
    act(() => result.current.step(-1));
    expect(result.current.frame).toBe(62);
    act(() => result.current.step(1));
    expect([result.current.frame, result.current.time]).toEqual([63, 2.5]);
  });

  it('stands on the end itself when the last frame starts short of it', () => {
    // 3.3 s at 24 fps: the end rounds to frame 79, which starts at 3.2917 s, before a key written at 3.3 s.
    const { result } = renderHook(() => useDeskPlayback(3.3, 24, 'shot-1'));
    act(() => result.current.seek(79 / 24));
    expect([result.current.frame, result.current.time]).toEqual([79, 3.3]);
    act(() => result.current.step(-1));
    expect(result.current.frame).toBe(78);
    expect(result.current.time).toBeCloseTo(78 / 24);
    act(() => result.current.step(1));
    expect([result.current.frame, result.current.time]).toEqual([79, 3.3]);
    // Played out, it stops there, and play starts over.
    act(() => result.current.seek(3));
    act(() => result.current.play());
    tick(0);
    for (let index = 0; index < 6; index += 1) tick(100);
    expect([result.current.frame, result.current.time, result.current.playing]).toEqual([79, 3.3, false]);
    act(() => result.current.seek(79 / 24));
    act(() => result.current.play());
    expect([result.current.frame, result.current.playing]).toEqual([0, true]);
  });

  it('redraws once per frame of the shot, not once per frame of the display', () => {
    let renders = 0;
    const { result } = renderHook(() => { renders += 1; return useDeskPlayback(2, 24, 'shot-1'); });
    act(() => result.current.play());
    tick(0);
    const before = renders;
    for (let index = 0; index < 12; index += 1) tick(1000 / 120);   // 0.1 s on a 120 Hz display
    expect(result.current.frame).toBe(2);
    expect(renders - before).toBe(2);
    // Paused between two frames, the clock keeps what it had run: 25 ms more reaches frame 3, 42 ms after frame 2.
    act(() => result.current.pause());
    act(() => result.current.play());
    tick(0);
    tick(25);
    expect(result.current.frame).toBe(3);
  });

  it('stays stopped after playing out, whatever changes afterwards', () => {
    const { result, rerender } = renderHook(({ duration }) => useDeskPlayback(duration, 24, 'shot-1'), { initialProps: { duration: 1 } });
    act(() => result.current.play());
    tick(0);
    for (let index = 0; index < 12; index += 1) tick(100);
    expect([result.current.frame, result.current.playing]).toEqual([24, false]);
    rerender({ duration: 3 });
    tick(100);
    expect([result.current.frame, result.current.playing]).toEqual([24, false]);
    act(() => result.current.setLoop(true));
    tick(100);
    expect([result.current.frame, result.current.playing]).toEqual([24, false]);
    // Asked to play, it goes on from where it stands now that the shot is longer.
    act(() => result.current.play());
    tick(0);
    tick(100);
    expect([result.current.frame, result.current.playing]).toEqual([26, true]);
  });
});
