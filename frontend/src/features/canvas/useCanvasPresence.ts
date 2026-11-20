import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, apiRequest } from '../../api/client';
import { t } from '../../i18n';

/**
 * The same person with one canvas open in several windows: each window sees where the others point,
 * what they drag and what they have selected, and hears about their saves at once instead of on the
 * next poll. Nothing here is stored; a window that goes away simply stops being shown.
 */

export interface PresencePeer {
  client_id: string;
  label: string;
  color: string;
}

export interface PresenceRect {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PresenceSaved {
  version: number;
  client_id: string | null;
}

/** A node run of this board changed state; with no run_id, its whole batch stopped (`finished`). Ids and status only. */
export interface PresenceRun {
  batch_id: string;
  run_id: string | null;
  node_id: string | null;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'skipped' | 'finished';
}

export interface CanvasPresence {
  clientId: string;
  /** The other windows on this canvas (this one left out). */
  peers: readonly PresencePeer[];
  /** Where each other window's pointer is, in world units. */
  cursors: ReadonlyMap<string, { x: number; y: number }>;
  /** The outlines each other window is dragging right now. */
  drags: ReadonlyMap<string, readonly PresenceRect[]>;
  selections: ReadonlyMap<string, readonly string[]>;
  sendCursor: (point: { x: number; y: number }) => void;
  /** `null` when the drag ends. */
  sendDrag: (rects: readonly PresenceRect[] | null) => void;
  sendSelection: (ids: readonly string[]) => void;
  /** Saves made somewhere other than this window; returns the unsubscribe. */
  onSaved: (listener: (saved: PresenceSaved) => void) => () => void;
  /** Runs changing state on this canvas, whichever window started them (this one included); returns the unsubscribe. */
  onRun: (listener: (run: PresenceRun) => void) => () => void;
}

type SendType = 'cursor' | 'drag' | 'selection';

export const PRESENCE_SEND_MS = 50;
export const PRESENCE_CURSOR_TTL_MS = 10_000;
export const PRESENCE_HIDDEN_STOP_MS = 60_000;
export const PRESENCE_RETRY_MAX_MS = 30_000;
const RETRY_BASE_MS = 1000;

const path = (projectId: string, canvasId: string) =>
  `/api/studio/projects/${encodeURIComponent(projectId)}/canvases/${encodeURIComponent(canvasId)}/presence`;

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch {
    // Some insecure origins have crypto without randomUUID.
  }
  return `w-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
}

// 每次打开页面一个新 id，按画布区分。不存 sessionStorage：浏览器「复制标签页」会把它一起复制过去，
// 两个标签页同一个 id 就互相看不见、还把对方的保存当成自己的回声。刷新后换 id，其他窗口会看到这个窗口离开又进来，无妨。
const pageIds = new Map<string, string>();

export function presenceClientId(canvasId: string): string {
  let id = pageIds.get(canvasId);
  if (!id) {
    id = randomId();
    pageIds.set(canvasId, id);
  }
  return id;
}

export function browserName(agent: string = typeof navigator === 'undefined' ? '' : navigator.userAgent): string {
  if (/Edg(e|A|iOS)?\//.test(agent)) return 'Edge';
  if (/OPR\/|Opera/.test(agent)) return 'Opera';
  if (/Firefox\/|FxiOS/.test(agent)) return 'Firefox';
  if (/Chrome\/|CriOS/.test(agent)) return 'Chrome';
  if (/Safari\//.test(agent)) return 'Safari';
  return t('浏览器');
}

export function presenceLabel(): string {
  return `${t('另一个窗口')} · ${browserName()}`;
}

function nextFrame(callback: () => void): () => void {
  if (typeof requestAnimationFrame === 'function') {
    const id = requestAnimationFrame(() => callback());
    return () => cancelAnimationFrame(id);
  }
  const id = setTimeout(callback, 16);
  return () => clearTimeout(id);
}

function parse<T>(event: Event): T | null {
  try {
    return JSON.parse((event as MessageEvent<string>).data) as T;
  } catch {
    return null;
  }
}

interface Slot {
  last: number;
  sent: string | null;
  pending: { body: Record<string, unknown>; key: string } | null;
  timer: ReturnType<typeof setTimeout> | null;
}

const EMPTY_PEERS: readonly PresencePeer[] = [];

export function useCanvasPresence({ projectId, canvasId, enabled }: { projectId: string; canvasId: string; enabled: boolean }): CanvasPresence {
  const [clientId] = useState(() => presenceClientId(canvasId));
  // jsdom and old browsers have no EventSource: then there is nothing to hear, and nothing is sent either.
  const live = enabled && typeof EventSource !== 'undefined';

  const [snapshot, setSnapshot] = useState<{
    peers: readonly PresencePeer[];
    cursors: ReadonlyMap<string, { x: number; y: number }>;
    drags: ReadonlyMap<string, readonly PresenceRect[]>;
    selections: ReadonlyMap<string, readonly string[]>;
  }>(() => ({ peers: EMPTY_PEERS, cursors: new Map(), drags: new Map(), selections: new Map() }));

  // What the stream has said so far; React hears about it at most once a frame.
  const state = useRef({
    peers: [] as PresencePeer[],
    cursors: new Map<string, { x: number; y: number }>(),
    drags: new Map<string, readonly PresenceRect[]>(),
    selections: new Map<string, readonly string[]>(),
  });
  const expiry = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const cancelFrame = useRef<(() => void) | null>(null);
  const savedListeners = useRef(new Set<(saved: PresenceSaved) => void>());
  const runListeners = useRef(new Set<(run: PresenceRun) => void>());
  const slots = useRef(new Map<SendType, Slot>());
  const liveRef = useRef(live);

  const publish = useCallback(() => {
    if (cancelFrame.current) return;
    cancelFrame.current = nextFrame(() => {
      cancelFrame.current = null;
      const current = state.current;
      setSnapshot({ peers: [...current.peers], cursors: new Map(current.cursors), drags: new Map(current.drags), selections: new Map(current.selections) });
    });
  }, []);

  const post = useCallback((body: Record<string, unknown>) => {
    if (!liveRef.current) return;
    apiRequest(path(projectId, canvasId), { method: 'POST', body: JSON.stringify({ client_id: clientId, ...body }) }).catch(() => undefined);
  }, [canvasId, clientId, projectId]);

  const flushSlot = useCallback((type: SendType) => {
    const slot = slots.current.get(type);
    if (!slot) return;
    slot.timer = null;
    const pending = slot.pending;
    slot.pending = null;
    if (!pending || pending.key === slot.sent) return;
    slot.sent = pending.key;
    slot.last = Date.now();
    post({ type, ...pending.body });
  }, [post]);

  /** At most one message of a kind every 50 ms, the latest one winning, and none that repeats the last. */
  const send = useCallback((type: SendType, body: Record<string, unknown>) => {
    if (!liveRef.current) return;
    let slot = slots.current.get(type);
    if (!slot) {
      slot = { last: 0, sent: null, pending: null, timer: null };
      slots.current.set(type, slot);
    }
    const key = JSON.stringify(body);
    if (key === slot.sent && !slot.pending) return;
    slot.pending = { body, key };
    if (slot.timer) return;
    const wait = PRESENCE_SEND_MS - (Date.now() - slot.last);
    if (wait <= 0) flushSlot(type);
    else slot.timer = setTimeout(() => flushSlot(type), wait);
  }, [flushSlot]);

  /** Say it again even though it has not changed: someone new is listening. */
  const resend = useCallback((type: SendType) => {
    const slot = slots.current.get(type);
    if (!slot?.sent) return;
    const body = JSON.parse(slot.sent) as Record<string, unknown>;
    slot.sent = null;
    send(type, body);
  }, [send]);

  const sendCursor = useCallback((point: { x: number; y: number }) => {
    send('cursor', { x: Math.round(point.x), y: Math.round(point.y) });
  }, [send]);

  const sendDrag = useCallback((rects: readonly PresenceRect[] | null) => {
    send('drag', {
      rects: (rects ?? []).map(rect => ({ id: rect.id, x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) })),
    });
  }, [send]);

  const sendSelection = useCallback((ids: readonly string[]) => {
    send('selection', { ids: [...ids] });
  }, [send]);

  const onSaved = useCallback((listener: (saved: PresenceSaved) => void) => {
    savedListeners.current.add(listener);
    return () => { savedListeners.current.delete(listener); };
  }, []);

  const onRun = useCallback((listener: (run: PresenceRun) => void) => {
    runListeners.current.add(listener);
    return () => { runListeners.current.delete(listener); };
  }, []);

  useEffect(() => {
    liveRef.current = live;
    if (!live) return undefined;
    const current = state.current;
    const timers = expiry.current;
    const sendSlots = slots.current;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let hiddenTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;
    let leftSent = false;

    const forget = (id: string) => {
      const timer = timers.get(id);
      if (timer) clearTimeout(timer);
      timers.delete(id);
      current.cursors.delete(id);
      current.drags.delete(id);
      current.selections.delete(id);
    };

    const handlers: Record<string, (event: Event) => void> = {
      peers: event => {
        const data = parse<{ peers?: PresencePeer[] }>(event);
        if (!data) return;
        const before = new Set(current.peers.map(peer => peer.client_id));
        current.peers = (data.peers ?? []).filter(peer => peer && peer.client_id && peer.client_id !== clientId);
        const now = new Set(current.peers.map(peer => peer.client_id));
        for (const id of new Set([...current.cursors.keys(), ...current.drags.keys(), ...current.selections.keys()])) if (!now.has(id)) forget(id);
        if ([...now].some(id => !before.has(id))) resend('selection');
        publish();
      },
      cursor: event => {
        const data = parse<{ client_id: string; x: number; y: number }>(event);
        if (!data || data.client_id === clientId || !Number.isFinite(data.x) || !Number.isFinite(data.y)) return;
        current.cursors.set(data.client_id, { x: data.x, y: data.y });
        const old = timers.get(data.client_id);
        if (old) clearTimeout(old);
        timers.set(data.client_id, setTimeout(() => {
          timers.delete(data.client_id);
          current.cursors.delete(data.client_id);
          publish();
        }, PRESENCE_CURSOR_TTL_MS));
        publish();
      },
      drag: event => {
        const data = parse<{ client_id: string; rects?: PresenceRect[] | null }>(event);
        if (!data || data.client_id === clientId) return;
        if (data.rects?.length) current.drags.set(data.client_id, data.rects);
        else current.drags.delete(data.client_id);
        publish();
      },
      selection: event => {
        const data = parse<{ client_id: string; ids?: string[] | null }>(event);
        if (!data || data.client_id === clientId) return;
        if (data.ids?.length) current.selections.set(data.client_id, data.ids);
        else current.selections.delete(data.client_id);
        publish();
      },
      left: event => {
        const data = parse<{ client_id: string }>(event);
        if (!data) return;
        forget(data.client_id);
        current.peers = current.peers.filter(peer => peer.client_id !== data.client_id);
        publish();
      },
      saved: event => {
        const data = parse<PresenceSaved>(event);
        // Our own save comes back too; that is not news.
        if (!data || data.client_id === clientId || !Number.isFinite(data.version)) return;
        for (const listener of [...savedListeners.current]) {
          try {
            listener(data);
          } catch {
            // One listener failing must not keep the save from the others.
          }
        }
      },
      run: event => {
        const data = parse<PresenceRun>(event);
        if (!data || typeof data.status !== 'string' || typeof data.batch_id !== 'string') return;
        for (const listener of [...runListeners.current]) {
          try {
            listener(data);
          } catch {
            // One listener failing must not keep the news from the others.
          }
        }
      },
    };

    const close = () => {
      if (retry) clearTimeout(retry);
      retry = null;
      source?.close();
      source = null;
    };

    const open = () => {
      close();
      if (stopped) return;
      const query = `client_id=${encodeURIComponent(clientId)}&label=${encodeURIComponent(presenceLabel())}`;
      const next = new EventSource(`${API_BASE}${path(projectId, canvasId)}/stream?${query}`, { withCredentials: true });
      source = next;
      for (const [type, handler] of Object.entries(handlers)) next.addEventListener(type, handler);
      next.addEventListener('open', () => { attempt = 0; });
      next.addEventListener('error', () => {
        if (source !== next) return;
        // The browser would retry on its own at its own pace; this one backs off and starts clean.
        close();
        const delay = Math.min(PRESENCE_RETRY_MAX_MS, RETRY_BASE_MS * 2 ** attempt);
        attempt += 1;
        retry = setTimeout(open, delay);
      });
    };

    const leave = () => {
      if (leftSent) return;
      leftSent = true;
      const url = `${API_BASE}${path(projectId, canvasId)}`;
      const body = JSON.stringify({ client_id: clientId, type: 'leave' });
      try {
        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function'
          && navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }))) return;
      } catch {
        // Fall through to a request that outlives the page.
      }
      try {
        void fetch(url, { method: 'POST', body, keepalive: true, credentials: 'include', headers: { 'Content-Type': 'application/json' } }).catch(() => undefined);
      } catch {
        // Leaving is a courtesy: the server notices the stream closing anyway.
      }
    };

    const clearPeers = () => {
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
      current.peers = [];
      current.cursors.clear();
      current.drags.clear();
      current.selections.clear();
      publish();
    };

    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        if (hiddenTimer) clearTimeout(hiddenTimer);
        hiddenTimer = setTimeout(() => {
          hiddenTimer = null;
          // A tab left in the background for a while stops listening; what it would show is stale anyway.
          close();
          clearPeers();
        }, PRESENCE_HIDDEN_STOP_MS);
        return;
      }
      if (hiddenTimer) clearTimeout(hiddenTimer);
      hiddenTimer = null;
      if (!source && !stopped) {
        attempt = 0;
        open();
      }
    };

    const onPageHide = () => {
      leave();
      close();
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted || stopped) return;
      leftSent = false;
      attempt = 0;
      open();
    };

    open();
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      stopped = true;
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
      if (hiddenTimer) clearTimeout(hiddenTimer);
      leave();
      close();
      for (const slot of sendSlots.values()) if (slot.timer) clearTimeout(slot.timer);
      sendSlots.clear();
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
      cancelFrame.current?.();
      cancelFrame.current = null;
      current.peers = [];
      current.cursors.clear();
      current.drags.clear();
      current.selections.clear();
    };
  }, [canvasId, clientId, live, projectId, publish, resend]);

  return useMemo(() => ({
    clientId, peers: snapshot.peers, cursors: snapshot.cursors, drags: snapshot.drags, selections: snapshot.selections,
    sendCursor, sendDrag, sendSelection, onSaved, onRun,
  }), [clientId, onRun, onSaved, sendCursor, sendDrag, sendSelection, snapshot]);
}
