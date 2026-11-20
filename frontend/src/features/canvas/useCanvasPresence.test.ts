// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  PRESENCE_CURSOR_TTL_MS, PRESENCE_HIDDEN_STOP_MS, PRESENCE_RETRY_MAX_MS, browserName, useCanvasPresence,
} from './useCanvasPresence';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  withCredentials: boolean;
  closed = false;
  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = Boolean(init?.withCredentials);
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

  emit(type: string, data?: unknown) {
    const event = data === undefined ? new Event(type) : new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  static last() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }
}

const PROPS = { projectId: 'p1', canvasId: 'c1', enabled: true };
let fetchMock: ReturnType<typeof vi.fn>;

function posts() {
  return fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
    .map(([url, init]) => ({ url: String(url), body: JSON.parse(String((init as RequestInit).body)) as Record<string, unknown> }));
}

function frame() {
  act(() => { vi.advanceTimersByTime(20); });
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('useCanvasPresence', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
    fetchMock = vi.fn(async () => ({ ok: true, status: 204, json: async () => { throw new SyntaxError('empty'); } }) as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    setVisibility('visible');
  });

  it('touches no network when disabled', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence({ ...PROPS, enabled: false }));
    act(() => {
      result.current.sendCursor({ x: 1, y: 2 });
      result.current.sendSelection(['a']);
    });
    vi.advanceTimersByTime(1000);
    unmount();
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps one client id per window and canvas, and names the stream with it and a label', () => {
    const first = renderHook(() => useCanvasPresence(PROPS));
    const id = first.result.current.clientId;
    first.unmount();
    const again = renderHook(() => useCanvasPresence(PROPS));
    expect(again.result.current.clientId).toBe(id);
    const source = FakeEventSource.last();
    expect(source.withCredentials).toBe(true);
    const url = new URL(source.url);
    expect(url.origin + url.pathname).toBe('http://localhost:8000/api/studio/projects/p1/canvases/c1/presence/stream');
    expect(url.searchParams.get('client_id')).toBe(id);
    expect(url.searchParams.get('label')).toMatch(/^另一个窗口 · /);
    again.unmount();
  });

  it('sends at most one message of a kind per 50 ms, the latest winning, and never the same one twice', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence(PROPS));
    act(() => {
      result.current.sendCursor({ x: 1, y: 1 });
      result.current.sendCursor({ x: 2, y: 2 });
      result.current.sendCursor({ x: 3, y: 3 });
      result.current.sendSelection(['n1']);
    });
    expect(posts().map(item => item.body)).toEqual([
      { client_id: result.current.clientId, type: 'cursor', x: 1, y: 1 },
      { client_id: result.current.clientId, type: 'selection', ids: ['n1'] },
    ]);
    expect(posts()[0].url).toBe('http://localhost:8000/api/studio/projects/p1/canvases/c1/presence');
    act(() => { vi.advanceTimersByTime(50); });
    expect(posts().map(item => item.body.x)).toEqual([1, undefined, 3]);
    // The same point again, and the same selection again: nothing goes out.
    act(() => {
      result.current.sendCursor({ x: 3, y: 3 });
      result.current.sendSelection(['n1']);
    });
    act(() => { vi.advanceTimersByTime(200); });
    expect(posts()).toHaveLength(3);
    // A drag, then its end.
    act(() => { result.current.sendDrag([{ id: 'n1', x: 10.4, y: 20.6, width: 200, height: 100 }]); });
    act(() => { vi.advanceTimersByTime(60); });
    act(() => { result.current.sendDrag(null); });
    expect(posts().slice(3).map(item => item.body.rects)).toEqual([[{ id: 'n1', x: 10, y: 21, width: 200, height: 100 }], []]);
    unmount();
  });

  it('shows the other windows, not itself, once a frame, and lets a quiet cursor go after 10 s', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence(PROPS));
    const me = result.current.clientId;
    const source = FakeEventSource.last();
    act(() => {
      source.emit('peers', { peers: [{ client_id: me, label: 'me', color: '#000' }, { client_id: 'w2', label: '另一个窗口 · Firefox', color: '#f00' }] });
      source.emit('cursor', { client_id: 'w2', x: 5, y: 6 });
      source.emit('cursor', { client_id: me, x: 9, y: 9 });
      source.emit('drag', { client_id: 'w2', rects: [{ id: 'a', x: 0, y: 0, width: 10, height: 10 }] });
      source.emit('selection', { client_id: 'w2', ids: ['a', 'b'] });
    });
    expect(result.current.peers).toEqual([]);
    frame();
    expect(result.current.peers.map(peer => peer.client_id)).toEqual(['w2']);
    expect([...result.current.cursors]).toEqual([['w2', { x: 5, y: 6 }]]);
    expect(result.current.drags.get('w2')).toHaveLength(1);
    expect(result.current.selections.get('w2')).toEqual(['a', 'b']);
    act(() => { source.emit('drag', { client_id: 'w2', rects: [] }); });
    frame();
    expect(result.current.drags.size).toBe(0);
    act(() => { vi.advanceTimersByTime(PRESENCE_CURSOR_TTL_MS); });
    frame();
    expect(result.current.cursors.size).toBe(0);
    expect(result.current.selections.size).toBe(1);
    act(() => { source.emit('left', { client_id: 'w2' }); });
    frame();
    expect(result.current.peers).toEqual([]);
    expect(result.current.selections.size).toBe(0);
    unmount();
  });

  it('tells about saves from elsewhere and ignores its own echo', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence(PROPS));
    const heard = vi.fn();
    const off = result.current.onSaved(heard);
    const source = FakeEventSource.last();
    act(() => {
      source.emit('saved', { version: 4, client_id: result.current.clientId });
      source.emit('saved', { version: 5, client_id: 'w2' });
      source.emit('saved', { version: 6, client_id: null });
    });
    expect(heard.mock.calls.map(([saved]) => saved.version)).toEqual([5, 6]);
    off();
    act(() => { source.emit('saved', { version: 7, client_id: 'w2' }); });
    expect(heard).toHaveBeenCalledTimes(2);
    unmount();
  });

  it('tells about runs changing state, whoever started them, until unsubscribed', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence(PROPS));
    const heard = vi.fn();
    const broken = vi.fn(() => { throw new Error('listener failed'); });
    result.current.onRun(broken);
    const off = result.current.onRun(heard);
    const source = FakeEventSource.last();
    act(() => {
      source.emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'running' });
      source.emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'done' });
      source.emit('run', { batch_id: 'b1', run_id: null, node_id: null, status: 'finished' });
      // Not a run event at all: ignored rather than passed on.
      source.emit('run', { version: 3 });
      source.emit('run');
    });
    expect(heard.mock.calls.map(([run]) => [run.node_id, run.status])).toEqual([['n1', 'running'], ['n1', 'done'], [null, 'finished']]);
    expect(broken).toHaveBeenCalledTimes(3);
    // Hearing about a run posts nothing and changes nothing that is drawn.
    expect(posts()).toEqual([]);
    off();
    act(() => { source.emit('run', { batch_id: 'b2', run_id: 'r2', node_id: 'n2', status: 'queued' }); });
    expect(heard).toHaveBeenCalledTimes(3);
    unmount();
  });

  it('keeps hearing about runs on the stream opened after an error', () => {
    const { result, unmount } = renderHook(() => useCanvasPresence(PROPS));
    const heard = vi.fn();
    result.current.onRun(heard);
    act(() => { FakeEventSource.last().emit('error'); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => { FakeEventSource.last().emit('run', { batch_id: 'b1', run_id: 'r1', node_id: 'n1', status: 'done' }); });
    expect(heard).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('starts the stream again after an error, backing off to 30 s, and from the start once it opens', () => {
    const { unmount } = renderHook(() => useCanvasPresence(PROPS));
    const delays: number[] = [];
    for (let attempt = 0; attempt < 7; attempt += 1) {
      const source = FakeEventSource.last();
      const count = FakeEventSource.instances.length;
      act(() => { source.emit('error'); });
      expect(source.closed).toBe(true);
      let waited = 0;
      while (FakeEventSource.instances.length === count) {
        act(() => { vi.advanceTimersByTime(500); });
        waited += 500;
      }
      delays.push(waited);
    }
    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, PRESENCE_RETRY_MAX_MS, PRESENCE_RETRY_MAX_MS]);
    act(() => { FakeEventSource.last().emit('open'); });
    const count = FakeEventSource.instances.length;
    act(() => { FakeEventSource.last().emit('error'); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(FakeEventSource.instances).toHaveLength(count + 1);
    unmount();
  });

  it('stops listening after a minute in the background and picks up again when shown', () => {
    const { unmount } = renderHook(() => useCanvasPresence(PROPS));
    const source = FakeEventSource.last();
    act(() => { setVisibility('hidden'); });
    act(() => { vi.advanceTimersByTime(PRESENCE_HIDDEN_STOP_MS - 1); });
    expect(source.closed).toBe(false);
    act(() => { vi.advanceTimersByTime(1); });
    expect(source.closed).toBe(true);
    act(() => { setVisibility('visible'); });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.last().closed).toBe(false);
    unmount();
  });

  it('says it is leaving with a beacon on unmount, and with a keepalive request when there is no beacon', async () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: beacon });
    const first = renderHook(() => useCanvasPresence(PROPS));
    const id = first.result.current.clientId;
    first.unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(beacon).toHaveBeenCalledTimes(1);
    const [url, blob] = beacon.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe('http://localhost:8000/api/studio/projects/p1/canvases/c1/presence');
    expect(JSON.parse(await blob.text())).toEqual({ client_id: id, type: 'leave' });

    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: undefined });
    const second = renderHook(() => useCanvasPresence(PROPS));
    act(() => { window.dispatchEvent(new Event('pagehide')); });
    const leave = posts().find(item => item.body.type === 'leave');
    expect(leave?.body).toEqual({ client_id: id, type: 'leave' });
    expect((fetchMock.mock.calls.find(([, init]) => (init as RequestInit).keepalive)?.[1] as RequestInit).credentials).toBe('include');
    second.unmount();
    // Already said on pagehide: not twice.
    expect(posts().filter(item => item.body.type === 'leave')).toHaveLength(1);
  });

  it('names the browser shortly', () => {
    expect(browserName('Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130.0 Safari/537.36')).toBe('Chrome');
    expect(browserName('Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0')).toBe('Edge');
    expect(browserName('Mozilla/5.0 (Macintosh; rv:131.0) Gecko/20100101 Firefox/131.0')).toBe('Firefox');
    expect(browserName('Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15')).toBe('Safari');
  });
});
