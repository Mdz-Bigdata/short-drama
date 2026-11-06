import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../api/client';
import { t } from '../../i18n';
import { fetchCanvas, saveCanvas } from './canvasApi';
import { pushEdit, redo, startHistory, undo, type DocHistory } from './canvasHistory';
import type { CanvasDoc, CanvasRecord } from './canvasTypes';

export type SaveStatus = 'loading' | 'idle' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict';

export const AUTOSAVE_MS = 1200;
const RETRY_MS = 5000;
const EMPTY: CanvasDoc = { nodes: [], edges: [] };

/**
 * One canvas's document: edits, undo, and autosave with a revision check.
 *
 * Every save names the revision it was based on. A 409 means someone else (another window, the
 * assistant) wrote in between; nothing is overwritten, autosave stops, and the person chooses.
 */
export function useCanvasDocument(projectId: string, canvasId: string) {
  const [history, setHistory] = useState<DocHistory>(() => startHistory(EMPTY));
  const [status, setStatus] = useState<SaveStatus>('loading');
  const [version, setVersion] = useState(0);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const historyRef = useRef(history);
  const versionRef = useRef(0);
  const loadedRef = useRef(false);
  const savedDoc = useRef<CanvasDoc>(EMPTY);
  const blocked = useRef(true);
  const inflight = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRef = useRef<() => Promise<boolean>>(async () => true);

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const schedule = useCallback((delay = AUTOSAVE_MS) => {
    if (blocked.current) return;
    clearTimer();
    timer.current = setTimeout(() => { void saveRef.current(); }, delay);
  }, []);

  const save = useCallback(async (): Promise<boolean> => {
    clearTimer();
    if (inflight.current) await inflight.current;
    if (blocked.current) return false;
    const doc = historyRef.current.doc;
    if (doc === savedDoc.current) return true;
    const attempt = (async () => {
      setStatus('saving');
      try {
        const record = await saveCanvas(projectId, canvasId, versionRef.current, doc);
        versionRef.current = record.version;
        setVersion(record.version);
        savedDoc.current = doc;
        if (historyRef.current.doc === doc) {
          setStatus('saved');
          setSaveError('');
        } else {
          setStatus('dirty');
          schedule();
        }
        return true;
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          blocked.current = true;
          setStatus('conflict');
        } else {
          setStatus('error');
          setSaveError(error instanceof Error ? error.message : '');
          schedule(RETRY_MS);
        }
        return false;
      }
    })();
    inflight.current = attempt;
    const outcome = await attempt;
    inflight.current = null;
    return outcome;
  }, [canvasId, projectId, schedule]);

  useEffect(() => { saveRef.current = save; }, [save]);

  const adopt = useCallback((record: Pick<CanvasRecord, 'version' | 'nodes' | 'edges'>) => {
    clearTimer();
    const doc: CanvasDoc = { nodes: record.nodes, edges: record.edges };
    const next = startHistory(doc);
    historyRef.current = next;
    savedDoc.current = doc;
    loadedRef.current = true;
    versionRef.current = record.version;
    blocked.current = false;
    setHistory(next);
    setVersion(record.version);
    setStatus(record.version ? 'saved' : 'idle');
  }, []);

  const reload = useCallback(async () => {
    blocked.current = true;
    setLoadError('');
    setStatus('loading');
    try {
      adopt(await fetchCanvas(projectId, canvasId));
    } catch (error) {
      setLoadError(error instanceof Error && error.message ? error.message : t('画布读取失败'));
      setStatus('error');
    }
  }, [adopt, canvasId, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    loadedRef.current = false;
    fetchCanvas(projectId, canvasId, controller.signal).then(adopt).catch(error => {
      if (controller.signal.aborted) return;
      setLoadError(error instanceof Error && error.message ? error.message : t('画布读取失败'));
      setStatus('error');
    });
    return () => controller.abort();
  }, [adopt, canvasId, projectId]);

  // Leaving with something unsaved: the last edit still goes out, the person just does not wait for it.
  useEffect(() => () => {
    clearTimer();
    if (!blocked.current && historyRef.current.doc !== savedDoc.current && !inflight.current) {
      void saveCanvas(projectId, canvasId, versionRef.current, historyRef.current.doc).catch(() => undefined);
    }
  }, [canvasId, projectId]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (historyRef.current.doc !== savedDoc.current) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  const apply = useCallback((next: DocHistory) => {
    if (next === historyRef.current) return;
    historyRef.current = next;
    setHistory(next);
    if (next.doc === savedDoc.current) {
      clearTimer();
      setStatus(current => (current === 'conflict' ? current : 'saved'));
    } else if (!blocked.current) {
      setStatus('dirty');
      schedule();
    }
  }, [schedule]);

  const edit = useCallback((change: (doc: CanvasDoc) => CanvasDoc, coalesce: string | null = null) => {
    apply(pushEdit(historyRef.current, change(historyRef.current.doc), coalesce));
  }, [apply]);

  /** Save now and keep going until what is on screen is what is stored; false when that cannot be done. */
  const flush = useCallback(async (): Promise<boolean> => {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const outcome = await save();
      if (!outcome) return false;
      if (historyRef.current.doc === savedDoc.current) return true;
    }
    return false;
  }, [save]);

  return {
    doc: history.doc,
    status,
    version,
    loadError,
    saveError,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    edit,
    undo: useCallback(() => apply(undo(historyRef.current)), [apply]),
    redo: useCallback(() => apply(redo(historyRef.current)), [apply]),
    flush,
    reload,
    adopt,
    currentVersion: useCallback(() => versionRef.current, []),
    isLoaded: useCallback(() => loadedRef.current, []),
    hasUnsaved: useCallback(() => historyRef.current.doc !== savedDoc.current, []),
    currentDoc: useCallback(() => historyRef.current.doc, []),
  };
}
