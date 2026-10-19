import type { StageProgress, StageProgressCall } from '../../types';

/** A call longer than this gets a line saying the model is slow, not stuck. */
export const SLOW_CALL_MS = 120_000;

/** 820ms · 12秒 · 7分32秒 — milliseconds only below a second, where they still mean something. */
export function formatDuration(ms: number): string {
  const value = Math.max(0, Math.round(ms));
  if (value < 1000) return `${value}ms`;
  const seconds = Math.floor(value / 1000);
  if (seconds < 60) return `${seconds}秒`;
  return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
}

function startOf(item: { started_at?: string; startedAt?: string }): number | null {
  const stamp = item.started_at ?? item.startedAt;
  const time = stamp ? Date.parse(stamp) : NaN;
  return Number.isFinite(time) ? time : null;
}

/**
 * The server only stamps elapsed time when a step changes, so a long model call would read
 * "8ms" for minutes. While the stage runs, both clocks are worked out from the start stamps.
 */
export function liveElapsed(progress: StageProgress, now: number): number | null {
  const recorded = progress.elapsed_ms ?? progress.elapsedMs;
  const started = startOf(progress);
  if (progress.status === 'running' && started !== null) return Math.max(recorded ?? 0, now - started);
  return recorded ?? null;
}

export function callElapsed(call: StageProgressCall, now: number): number | null {
  const recorded = call.duration_ms ?? call.durationMs;
  if (recorded !== undefined) return recorded;
  const started = startOf(call);
  return call.status === 'running' && started !== null ? now - started : null;
}
