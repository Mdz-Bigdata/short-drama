import { useCallback, useEffect, useReducer, useRef, useState } from 'react';

import { ApiError } from '../../api/client';
import { fetchSpatialPlan, patchSpatialPlan } from '../spatial/spatialApi';
import { deskReducer, initialDeskState, type EditKind } from './deskReducer';
import type { EditRequest } from './deskTypes';
import { createPatchQueue } from './lib/patchQueue';

// Only the server's own sentence is shown: a request that never arrived fails with the browser's English.
function messageOf(error: unknown, fallback: string) {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

/** The desk session of one scene: the reducer, the serialized PATCH queue behind it, and undo / redo. */
export function useDeskSession(taskId: string, sceneId: string) {
  const [state, dispatch] = useReducer(deskReducer, initialDeskState);
  const editId = useRef(0);

  // The desk is keyed by scene, so the ids captured here never go stale.
  const [queue] = useState(() => createPatchQueue({
    // The desk is what-you-see: no edit of its own asks the server to re-solve a lens.
    patch: (revision, operations, options) => patchSpatialPlan(taskId, sceneId, revision, operations, options),
    onApplied: (response, editIds) => dispatch({ type: 'applied', response, editIds }),
    onRejected: (error, editIds) => dispatch({
      type: 'rejected', editIds, status: error instanceof ApiError ? error.status : 0, message: messageOf(error, '保存失败，请稍后重试。'),
    }),
  }));

  const load = useCallback((signal?: AbortSignal) => (
    fetchSpatialPlan(taskId, sceneId, signal)
      .then(response => {
        queue.reset(response.plan.revision);
        dispatch({ type: 'loaded', response });
      })
      .catch(error => {
        if (signal?.aborted) return;
        dispatch({ type: 'loadFailed', message: messageOf(error, '空间调度读取失败。') });
      })
  ), [queue, sceneId, taskId]);

  // Runs on open, and again whenever a revision conflict bumps the token.
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, state.reloadToken]);

  const send = useCallback((kind: EditKind, request: EditRequest) => {
    if (!request.operations.length) return;
    editId.current += 1;
    const id = editId.current;
    dispatch({ type: 'edit', id, kind, label: request.label, operations: request.operations, irreversible: request.irreversible });
    queue.enqueue({ id, operations: request.operations, solve: false, barrier: request.barrier });
  }, [queue]);

  const editable = Boolean(state.plan) && !state.readOnly;
  // Undo and redo asked for while an edit is still saving. That edit is not in the history until
  // the server has it, so replaying at once would take back the edit before it.
  const waiting = useRef<Array<'undo' | 'redo'>>([]);
  const commit = useCallback((request: EditRequest) => {
    if (!editable) return;
    // An undo must never reach an edit made after it was asked for.
    waiting.current = [];
    send('edit', request);
  }, [editable, send]);
  const lastUndo = state.undo[state.undo.length - 1];
  const lastRedo = state.redo[state.redo.length - 1];
  const saving = state.pending.length > 0;
  const replay = useCallback((kind: 'undo' | 'redo') => {
    if (kind === 'undo' && lastUndo) send('undo', { operations: lastUndo.inverse, label: lastUndo.label, barrier: true });
    else if (kind === 'redo' && lastRedo) send('redo', { operations: lastRedo.forward, label: lastRedo.label, barrier: true });
    else waiting.current = [];
  }, [lastRedo, lastUndo, send]);
  const ask = useCallback((kind: 'undo' | 'redo') => {
    if (!editable) return;
    if (saving) { waiting.current.push(kind); return; }
    waiting.current = [];
    replay(kind);
  }, [editable, replay, saving]);
  const undo = useCallback(() => ask('undo'), [ask]);
  const redo = useCallback(() => ask('redo'), [ask]);

  // One at a time: each replay is an edit of its own, and the next reads the history it leaves.
  const { saveState } = state;
  useEffect(() => {
    if (saving || !waiting.current.length) return;
    // Rejected or read again: what the keypress meant to take back is no longer there.
    if (!editable || saveState !== 'saved') { waiting.current = []; return; }
    replay(waiting.current.shift()!);
  }, [editable, replay, saveState, saving]);

  const canUndo = editable && (state.undo.length > 0 || state.pending.some(edit => edit.kind !== 'undo' && edit.inverse !== false));
  const canRedo = editable && (state.redo.length > 0 || state.pending.some(edit => edit.kind === 'undo'));

  return { state, dispatch, commit, undo, redo, canUndo, canRedo, reload: load, editable };
}
