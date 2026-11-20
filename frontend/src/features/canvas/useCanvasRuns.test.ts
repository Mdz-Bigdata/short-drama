// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CanvasOutputs } from './canvasTypes';
import { useCanvasPresence } from './useCanvasPresence';
import { useCanvasRuns } from './useCanvasRuns';

const fetchOutputs = vi.hoisted(() => vi.fn());
vi.mock('./canvasApi', () => ({ fetchOutputs }));

const BUSY_MS = 2500;
const IDLE_MS = 20000;

function outputs(status: 'running' | 'done' | null, version = 1): CanvasOutputs {
  return {
    version,
    outputs: status === 'done' ? { n1: { run_id: 'r1', medium: 'image', url: '/media/a.png' } as CanvasOutputs['outputs'][string] } : {},
    latest: status ? { n1: { run_id: 'r1', status, error: null, batch_id: 'b1' } } : {},
    history_counts: status ? { n1: 1 } : {},
    running: status === 'running' ? 1 : 0,
  };
}

/** Every read waits until the test answers it, so "in flight" is something a test can hold on to. */
interface Pending {
  signal?: AbortSignal;
  resolve: (value: CanvasOutputs) => void;
  reject: (reason: unknown) => void;
}
let pending: Pending[] = [];

function held() {
  fetchOutputs.mockImplementation((_project: string, _canvas: string, signal?: AbortSignal) => new Promise<CanvasOutputs>((resolve, reject) => {
    pending.push({ signal, resolve, reject });
  }));
}

async function answer(index: number, value: CanvasOutputs) {
  await act(async () => {
    pending[index].resolve(value);
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  closed = false;
  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

describe('useCanvasRuns', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    pending = [];
    fetchOutputs.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('polls on its own with no events: every 20 s when idle, every 2.5 s while something runs', async () => {
    const replies = [outputs(null), outputs('running'), outputs('running'), outputs('done'), outputs('done')];
    fetchOutputs.mockImplementation(async () => replies[Math.min(fetchOutputs.mock.calls.length, replies.length) - 1]);
    const onRemoteVersion = vi.fn();
    const { result, unmount } = renderHook(() => useCanvasRuns('p1', 'c1', onRemoteVersion));
    await advance(0);
    expect(fetchOutputs).toHaveBeenCalledTimes(1);
    expect(fetchOutputs.mock.calls[0].slice(0, 2)).toEqual(['p1', 'c1']);
    await advance(IDLE_MS - 1);
    expect(fetchOutputs).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fetchOutputs).toHaveBeenCalledTimes(2);
    expect(result.current.data.running).toBe(1);
    await advance(BUSY_MS - 1);
    expect(fetchOutputs).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(fetchOutputs).toHaveBeenCalledTimes(3);
    await advance(BUSY_MS);
    expect(fetchOutputs).toHaveBeenCalledTimes(4);
    expect(result.current.data.latest.n1.status).toBe('done');
    // Nothing runs any more: back to the slow read.
    await advance(BUSY_MS);
    expect(fetchOutputs).toHaveBeenCalledTimes(4);
    await advance(IDLE_MS - BUSY_MS);
    expect(fetchOutputs).toHaveBeenCalledTimes(5);
    expect(onRemoteVersion).toHaveBeenCalledWith(1);
    unmount();
    await advance(IDLE_MS * 2);
    expect(fetchOutputs).toHaveBeenCalledTimes(5);
  });

  it('reads once, at once, when told a run changed, and leaves the poll at its own pace', async () => {
    held();
    const { result, unmount } = renderHook(() => useCanvasRuns('p1', 'c1', () => undefined));
    await answer(0, outputs(null));
    expect(pending).toHaveLength(1);
    await advance(5000);
    expect(pending).toHaveLength(1);

    act(() => { result.current.refreshSoon(); });
    expect(pending).toHaveLength(2);
    await answer(1, outputs('done'));
    expect(result.current.data.latest.n1.status).toBe('done');
    expect(result.current.data.outputs.n1.url).toBe('/media/a.png');
    expect(pending).toHaveLength(2);

    // The idle poll was armed 20 s after the first read came back and has not been moved.
    await advance(IDLE_MS - 5000 - 1);
    expect(pending).toHaveLength(2);
    await advance(1);
    expect(pending).toHaveLength(3);
    unmount();
  });

  it('answers a burst of events with one request in flight and one after it', async () => {
    held();
    const { result, unmount } = renderHook(() => useCanvasRuns('p1', 'c1', () => undefined));
    await answer(0, outputs(null));

    act(() => {
      for (let index = 0; index < 6; index += 1) result.current.refreshSoon();
    });
    expect(pending).toHaveLength(2);
    act(() => { result.current.refreshSoon(); });
    expect(pending).toHaveLength(2);

    await answer(1, outputs('running'));
    expect(pending).toHaveLength(3);
    // More news while the trailing read is out: one more after it, not one each.
    act(() => {
      result.current.refreshSoon();
      result.current.refreshSoon();
    });
    expect(pending).toHaveLength(3);
    await answer(2, outputs('running'));
    expect(pending).toHaveLength(4);
    await answer(3, outputs('done'));
    expect(pending).toHaveLength(4);
    expect(result.current.data.latest.n1.status).toBe('done');

    // Quiet again: the next event reads straight away.
    act(() => { result.current.refreshSoon(); });
    expect(pending).toHaveLength(5);
    unmount();
  });

  it('reads again after a read that failed, and stops when the canvas goes away', async () => {
    held();
    const { result, unmount } = renderHook(() => useCanvasRuns('p1', 'c1', () => undefined));
    await answer(0, outputs(null));

    act(() => { result.current.refreshSoon(); });
    await act(async () => {
      pending[1].reject(new Error('offline'));
      await Promise.resolve();
    });
    act(() => { result.current.refreshSoon(); });
    expect(pending).toHaveLength(3);
    act(() => { result.current.refreshSoon(); });

    unmount();
    expect(pending[2].signal?.aborted).toBe(true);
    await act(async () => {
      pending[2].reject(new DOMException('aborted', 'AbortError'));
      await Promise.resolve();
    });
    // The trailing read that was owed is not sent for a canvas nobody is looking at.
    expect(pending).toHaveLength(3);
  });

  it('does not let a slow older read undo what a later one already showed', async () => {
    held();
    const { result, unmount } = renderHook(() => useCanvasRuns('p1', 'c1', () => undefined));
    // The first poll is still out when the run finishes and the event-driven read overtakes it.
    act(() => { result.current.refreshSoon(); });
    expect(pending).toHaveLength(2);
    await answer(1, outputs('done'));
    expect(result.current.data.latest.n1.status).toBe('done');
    await answer(0, outputs('running'));
    expect(result.current.data.latest.n1.status).toBe('done');
    expect(result.current.data.running).toBe(0);
    unmount();
  });

  it('reads the outputs when the presence stream says a run changed (the glue in CanvasWorkspace)', async () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 204, json: async () => ({}) }) as unknown as Response));
    FakeEventSource.instances = [];
    held();
    const { result, unmount } = renderHook(() => {
      const presence = useCanvasPresence({ projectId: 'p1', canvasId: 'c1', enabled: true });
      const runs = useCanvasRuns('p1', 'c1', () => undefined);
      const { onRun } = presence;
      const { refreshSoon } = runs;
      useEffect(() => onRun(() => refreshSoon()), [onRun, refreshSoon]);
      return runs;
    });
    await answer(0, outputs(null));
    const source = FakeEventSource.instances[FakeEventSource.instances.length - 1];

    act(() => {
      source.emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'queued' });
      source.emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'running' });
    });
    expect(pending).toHaveLength(2);
    await answer(1, outputs('running'));
    expect(pending).toHaveLength(3);
    await answer(2, outputs('running'));
    expect(result.current.data.running).toBe(1);

    act(() => { source.emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'done' }); });
    expect(pending).toHaveLength(4);
    await answer(3, outputs('done'));
    expect(result.current.data.outputs.n1.url).toBe('/media/a.png');
    // Other presence traffic is not a reason to read.
    act(() => {
      source.emit('cursor', { client_id: 'w2', x: 1, y: 1 });
      source.emit('saved', { version: 1, client_id: 'w2' });
    });
    expect(pending).toHaveLength(4);
    unmount();
  });
});
