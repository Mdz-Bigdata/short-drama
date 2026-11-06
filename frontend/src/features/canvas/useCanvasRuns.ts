import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchOutputs } from './canvasApi';
import type { CanvasOutputs, LatestRun, NodeOutput } from './canvasTypes';

const EMPTY: CanvasOutputs = { version: 0, outputs: {}, latest: {}, history_counts: {}, running: 0 };
const BUSY_MS = 2500;
const IDLE_MS = 20000;

/** Keep an entry's identity when nothing in it changed, so a poll re-renders only the nodes it touched. */
function stable<T extends LatestRun | NodeOutput>(previous: Record<string, T>, next: Record<string, T>): Record<string, T> {
  let same = Object.keys(previous).length === Object.keys(next).length;
  const merged: Record<string, T> = {};
  for (const [key, value] of Object.entries(next)) {
    const before = previous[key];
    if (before && JSON.stringify(before) === JSON.stringify(value)) {
      merged[key] = before;
    } else {
      merged[key] = value;
      same = false;
    }
  }
  return same ? previous : merged;
}

/**
 * Generation results live beside the document, not in it (a job finishing must not bump the revision
 * being edited), so they are read on their own: quickly while something runs, slowly otherwise. The
 * slow read doubles as the check for someone else having changed this canvas.
 */
export function useCanvasRuns(projectId: string, canvasId: string, onRemoteVersion: (version: number) => void) {
  const [data, setData] = useState<CanvasOutputs>(EMPTY);
  const notify = useRef(onRemoteVersion);
  // Only the newest loop may go on: an older one still waiting on the network ends when it gets back.
  const loop = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => { notify.current = onRemoteVersion; }, [onRemoteVersion]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const next = await fetchOutputs(projectId, canvasId, signal);
    setData(previous => ({
      ...next,
      outputs: stable(previous.outputs, next.outputs),
      latest: stable(previous.latest, next.latest),
    }));
    notify.current(next.version);
    return next;
  }, [canvasId, projectId]);

  const start = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    loop.current += 1;
    const mine = loop.current;
    const signal = controller.current?.signal;
    const tick = async () => {
      let delay = BUSY_MS;
      try {
        const next = await refresh(signal);
        delay = next.running > 0 ? BUSY_MS : IDLE_MS;
      } catch {
        // A missed poll is not news; the next one will tell.
      }
      if (mine === loop.current) timer.current = setTimeout(() => { void tick(); }, delay);
    };
    void tick();
  }, [refresh]);

  useEffect(() => {
    controller.current = new AbortController();
    start();
    return () => {
      controller.current?.abort();
      loop.current += 1;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [start]);

  /** Read right after a run begins, without waiting out the idle delay. */
  return { data, refresh, kick: start };
}
