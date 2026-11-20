// The canvas's "sync from project" (backend/app/core/canvas_project_sync.py): what it would change, and applying it.
// The idea of a canvas that follows its project is AID Studio's (MIT); here the canvas stays editable.
import { useCallback, useEffect, useRef, useState } from 'react';

/** The least time between two counts asked because the window came back into view. */
export const SYNC_COUNT_GAP_MS = 5000;

import { apiRequest } from '../../api/client';

export type SyncField = 'prompt' | 'duration' | 'picture';

/** One field of one node where the canvas and the project differ. */
export interface SyncItem {
  id: string;
  node_id: string;
  key: string;
  field: SyncField;
  /** `update`: the project changed and the canvas did not. `conflict`: both did, or the node predates syncing. */
  state: 'update' | 'conflict';
  label: string;
  scene: string;
  shot: number;
  canvas: string | number | null;
  project: string | number | null;
  /** Taken from the project unless the person says otherwise. */
  checked: boolean;
}

export interface SyncNote {
  kind: 'gone' | 'board_ready';
  node_id: string;
  label: string;
  scene: string;
  shot: number;
  url?: string;
}

export interface SyncScene {
  scene_id: string;
  shots: number;
  new: number;
  /** Part of the scene is on the canvas: its new shots join that row. */
  on_canvas: boolean;
  /** Fits in this sync; the rest wait for the next one. */
  this_time: boolean;
}

export interface SyncReview {
  storyboard: boolean;
  new: { shots: number; this_time: number; later: number; scenes: SyncScene[] };
  items: SyncItem[];
  notes: SyncNote[];
  followed: number;
  token: string;
  version: number;
}

export interface SyncResult {
  applied: boolean;
  version: number;
  shots: number;
  updated: number;
  kept: number;
  node_ids: string[];
}

const path = (projectId: string, canvasId: string) =>
  `/api/studio/projects/${encodeURIComponent(projectId)}/canvas/project-sync?canvas_id=${encodeURIComponent(canvasId)}`;

export function fetchSyncReview(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<SyncReview>(path(projectId, canvasId), { signal });
}

/** `clientId` names the window asking: it reloads the result itself, so the presence stream does not also tell it. */
export function applySync(projectId: string, canvasId: string, review: SyncReview, accept: string[], addNew: boolean, clientId?: string) {
  return apiRequest<SyncResult>(path(projectId, canvasId), {
    method: 'POST',
    ...(clientId ? { headers: { 'X-Canvas-Client': clientId } } : {}),
    body: JSON.stringify({ expected_version: review.version, token: review.token, accept, add_new: addNew }),
  });
}

/** How much a sync would bring: new shots plus differences. Notes only inform and are not counted. */
export function pendingCount(review: SyncReview | null) {
  return review ? review.new.shots + review.items.length : 0;
}

/**
 * The count on the sync button. Asked when the canvas opens, when the window comes back into view
 * (the person may have changed the storyboard meanwhile) and whenever `refreshKey` changes. A review
 * reads the project and the canvas and spends nothing.
 */
export function useSyncCount(projectId: string, canvasId: string, refreshKey: unknown) {
  const [count, setCount] = useState(0);
  const [tick, setTick] = useState(0);
  // Coming back to the window asks again, but not more often than this: focus events come in bursts.
  const asked = useRef(0);
  const again = useCallback(() => {
    if (Date.now() - asked.current < SYNC_COUNT_GAP_MS) return;
    asked.current = Date.now();
    setTick(value => value + 1);
  }, []);

  useEffect(() => {
    const visible = () => { if (document.visibilityState === 'visible') again(); };
    window.addEventListener('focus', again);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.removeEventListener('focus', again);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [again]);

  useEffect(() => {
    if (!projectId) return undefined;
    const abort = new AbortController();
    fetchSyncReview(projectId, canvasId, abort.signal)
      .then(review => setCount(pendingCount(review)))
      .catch(() => undefined);
    return () => abort.abort();
  }, [canvasId, projectId, refreshKey, tick]);

  return count;
}
