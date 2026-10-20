import { describe, expect, it } from 'vitest';

import type { StageProgress } from '../../types';
import { SLOW_CALL_MS, callElapsed, formatDuration, liveElapsed } from './stageProgress';

const started = '2026-10-15T03:32:49.249Z';
const base = Date.parse(started);
const running: StageProgress = {
  stage: 1, percent: 25, label: '调用 LLM', status: 'running', elapsed_ms: 8, started_at: started,
  calls: [
    { name: '初始化阶段上下文', status: 'done', duration_ms: 8, started_at: started },
    { name: '调用 LLM · 总导演定调与三幕大纲规划', status: 'running', started_at: '2026-10-15T03:32:49.257Z' },
  ],
};

describe('stage progress clocks', () => {
  it('formats short and long waits readably', () => {
    expect([formatDuration(8), formatDuration(12_400), formatDuration(452_000)]).toEqual(['8ms', '12秒', '7分32秒']);
  });

  it('counts a running stage and its running call from their start stamps', () => {
    const now = base + 452_000;
    expect(liveElapsed(running, now)).toBe(452_000);
    expect(callElapsed(running.calls![1], now)).toBe(451_992);
    expect(callElapsed(running.calls![0], now)).toBe(8);
    expect(callElapsed(running.calls![1], now)! > SLOW_CALL_MS).toBe(true);
  });

  it('keeps the server figure once the stage stops', () => {
    expect(liveElapsed({ ...running, status: 'success', elapsed_ms: 61_000 }, base + 999_000)).toBe(61_000);
    expect(liveElapsed({ ...running, started_at: undefined }, base + 999_000)).toBe(8);
  });
});
