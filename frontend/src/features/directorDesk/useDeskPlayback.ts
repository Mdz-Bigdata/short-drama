import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { lastPlayheadFrame, playheadFrame, snapToFrame } from './lib/sampling';

// A stalled tab comes back with one enormous frame delta; playing it out would jump the shot.
// Anything shorter is a slow frame, and is played in full: previs is watched for its timing, so
// a busy stage drops frames rather than running in slow motion.
const MAX_STEP_S = 0.25;
/** How fast the playhead runs against the wall clock. Slow shows a move frame by frame; fast skims a long shot. */
export const PLAYBACK_SPEEDS = [0.25, 0.5, 1, 2] as const;

export interface DeskPlayback {
  /** Seconds, always on a whole frame of the shot, or on its very end. */
  time: number;
  /** 0 … `lastPlayheadFrame`: the end of the shot is a frame the playhead can stand on. */
  frame: number;
  playing: boolean;
  loop: boolean;
  play: () => void;
  pause: () => void;
  stop: () => void;
  seek: (time: number) => void;
  step: (frames: number) => void;
  setLoop: (loop: boolean) => void;
  /** 1 is real time. Only how fast the shot is watched: nothing about the shot itself changes. */
  speed: number;
  setSpeed: (speed: number) => void;
}

/**
 * The playhead of one shot. It is only ever a number the desk samples the timeline at: playing,
 * scrubbing and stopping never touch the plan, the PATCH queue or the undo stack.
 */
export function useDeskPlayback(durationS: number, fps: number, shotKey: string): DeskPlayback {
  const [clock, setClock] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(false);
  const [speed, setSpeedState] = useState(1);
  const setSpeed = useCallback((next: number) => setSpeedState(PLAYBACK_SPEEDS.find(item => item === next) ?? 1), []);
  // Layout effects throughout: the clock must not tick between a commit and what follows from it.
  const limits = useRef({ durationS, fps, loop, speed });
  useLayoutEffect(() => { limits.current = { durationS, fps, loop, speed }; }, [durationS, fps, loop, speed]);
  // The clock as it runs. `clock` only takes it when the frame on screen changes: a display
  // refreshes two to five times per frame of a shot, and each commit redraws the whole desk.
  const exact = useRef(0);
  const setTime = useCallback((next: number) => { exact.current = next; setClock(next); }, []);

  // Another shot is another timeline.
  const [shownShot, setShownShot] = useState(shotKey);
  if (shownShot !== shotKey) {
    setShownShot(shotKey);
    setClock(0);
    setPlaying(false);
  }
  useLayoutEffect(() => { exact.current = 0; }, [shotKey]);

  // Reaching the end of a shot that does not loop stops it for good: a longer duration or a ticked
  // loop afterwards must not set it going again by itself.
  const running = playing && (loop || clock < durationS - 1e-6);
  if (playing && !running) setPlaying(false);

  useLayoutEffect(() => {
    if (!running) return undefined;
    let handle = 0;
    let last: number | null = null;
    const tick = (now: number) => {
      const { durationS: end, fps: rate, loop: around, speed: pace } = limits.current;
      const delta = last === null ? 0 : Math.min(MAX_STEP_S, Math.max(0, (now - last) / 1000)) * pace;
      last = now;
      const before = exact.current;
      const reached = before + delta >= end - 1e-6;
      const next = !reached ? before + delta : around ? (before + delta) % end : end;
      exact.current = next;
      // The end is committed even when it lands on the frame already shown: it is what stops the clock.
      if (reached || playheadFrame(next, rate, end) !== playheadFrame(before, rate, end)) setClock(next);
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, [running]);

  const time = snapToFrame(clock, fps, durationS);
  const frame = playheadFrame(clock, fps, durationS);

  const play = useCallback(() => {
    // Play from the end means play again. The last frame is the end, however little of the shot runs on after it.
    const { durationS: end, fps: rate } = limits.current;
    if (playheadFrame(exact.current, rate, end) === lastPlayheadFrame(end, rate)) setTime(0);
    setPlaying(true);
  }, [setTime]);
  const pause = useCallback(() => setPlaying(false), []);
  const stop = useCallback(() => { setPlaying(false); setTime(0); }, [setTime]);
  const seek = useCallback((next: number) => setTime(Math.min(Math.max(0, Number.isFinite(next) ? next : 0), limits.current.durationS)), [setTime]);
  const step = useCallback((frames: number) => {
    setPlaying(false);
    const last = lastPlayheadFrame(durationS, fps);
    const target = Math.min(last, Math.max(0, playheadFrame(exact.current, fps, durationS) + frames));
    setTime(target === last ? durationS : target / fps);
  }, [durationS, fps, setTime]);

  return useMemo(() => ({ time, frame, playing: running, loop, play, pause, stop, seek, step, setLoop, speed, setSpeed }),
    [frame, loop, pause, play, running, seek, setSpeed, speed, step, stop, time]);
}
