import { useCallback, useEffect, useReducer, useRef, useState } from 'react';

import { ApiError } from '../../api/client';
import { fetchSpatialPlan, patchSpatialPlan } from '../spatial/spatialApi';
import { deskReducer, initialDeskState, type EditKind } from './deskReducer';
import type { EditRequest } from './deskTypes';
import { createPatchQueue } from './lib/patchQueue';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
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
  const commit = useCallback((request: EditRequest) => { if (editable) send('edit', request); }, [editable, send]);
  const lastUndo = state.undo[state.undo.length - 1];
  const lastRedo = state.redo[state.redo.length - 1];
  const undo = useCallback(() => {
    if (editable && lastUndo) send('undo', { operations: lastUndo.inverse, label: lastUndo.label, barrier: true });
  }, [editable, lastUndo, send]);
  const redo = useCallback(() => {
    if (editable && lastRedo) send('redo', { operations: lastRedo.forward, label: lastRedo.label, barrier: true });
  }, [editable, lastRedo, send]);

  return { state, dispatch, commit, undo, redo, reload: load, editable };
}
