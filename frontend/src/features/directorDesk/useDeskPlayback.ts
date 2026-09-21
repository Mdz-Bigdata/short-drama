import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { frameCount, snapToFrame } from './lib/sampling';

// A stalled tab comes back with one enormous frame delta; playing it out would jump the shot.
// Anything shorter is a slow frame, and is played in full: previs is watched for its timing, so
// a busy stage drops frames rather than running in slow motion.
const MAX_STEP_S = 0.25;

export interface DeskPlayback {
  /** Seconds, always on a whole frame of the shot. */
  time: number;
  frame: number;
  playing: boolean;
  loop: boolean;
  play: () => void;
  pause: () => void;
  stop: () => void;
  seek: (time: number) => void;
  step: (frames: number) => void;
  setLoop: (loop: boolean) => void;
}

/**
 * The playhead of one shot. It is only ever a number the desk samples the timeline at: playing,
 * scrubbing and stopping never touch the plan, the PATCH queue or the undo stack.
 */
export function useDeskPlayback(durationS: number, fps: number, shotKey: string): DeskPlayback {
  const [clock, setClock] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(false);
  const limits = useRef({ durationS, loop });
  useEffect(() => { limits.current = { durationS, loop }; }, [durationS, loop]);

  // Another shot is another timeline.
  const [shownShot, setShownShot] = useState(shotKey);
  if (shownShot !== shotKey) {
    setShownShot(shotKey);
    setClock(0);
    setPlaying(false);
  }

  // Reaching the end of a shot that does not loop is what stops it; nothing has to notice and say so.
  const running = playing && (loop || clock < durationS - 1e-6);

  useEffect(() => {
    if (!running) return undefined;
    let handle = 0;
    let last: number | null = null;
    const tick = (now: number) => {
      const delta = last === null ? 0 : Math.min(MAX_STEP_S, Math.max(0, (now - last) / 1000));
      last = now;
      setClock(current => {
        const next = current + delta;
        if (next < limits.current.durationS) return next;
        return limits.current.loop ? next % limits.current.durationS : limits.current.durationS;
      });
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, [running]);

  const time = snapToFrame(Math.min(clock, durationS), fps, durationS);
  const last = (frameCount(durationS, fps) - 1) / fps;

  const play = useCallback(() => {
    // Play from the end means play again.
    setClock(current => (current >= limits.current.durationS - 1e-6 ? 0 : current));
    setPlaying(true);
  }, []);
  const pause = useCallback(() => setPlaying(false), []);
  const stop = useCallback(() => { setPlaying(false); setClock(0); }, []);
  const seek = useCallback((next: number) => setClock(Math.min(Math.max(0, Number.isFinite(next) ? next : 0), limits.current.durationS)), []);
  const step = useCallback((frames: number) => {
    setPlaying(false);
    setClock(current => Math.min(last, Math.max(0, (Math.floor(current * fps + 1e-6) + frames) / fps)));
  }, [fps, last]);

  return useMemo(() => ({ time, frame: Math.round(time * fps), playing: running, loop, play, pause, stop, seek, step, setLoop }),
    [fps, loop, pause, play, running, seek, step, stop, time]);
}
