import type { CanvasDoc } from './canvasTypes';

export const HISTORY_LIMIT = 100;

export interface DocHistory {
  doc: CanvasDoc;
  past: CanvasDoc[];
  future: CanvasDoc[];
  /** Consecutive edits with the same key (typing in one field) undo as one. */
  coalesce: string | null;
}

export function startHistory(doc: CanvasDoc): DocHistory {
  return { doc, past: [], future: [], coalesce: null };
}

export function pushEdit(state: DocHistory, doc: CanvasDoc, coalesce: string | null = null): DocHistory {
  if (doc === state.doc) return state;
  if (coalesce && coalesce === state.coalesce) return { ...state, doc, future: [] };
  return { doc, past: [...state.past, state.doc].slice(-HISTORY_LIMIT), future: [], coalesce };
}

export function undo(state: DocHistory): DocHistory {
  const previous = state.past[state.past.length - 1];
  if (!previous) return state;
  return { doc: previous, past: state.past.slice(0, -1), future: [state.doc, ...state.future], coalesce: null };
}

export function redo(state: DocHistory): DocHistory {
  const next = state.future[0];
  if (!next) return state;
  return { doc: next, past: [...state.past, state.doc], future: state.future.slice(1), coalesce: null };
}
