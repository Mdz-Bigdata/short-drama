/** The background screenplay run stage 2 starts once its outline is in (``assets["2_detail"]``). */
export interface ScriptDetailRecord {
  status?: 'writing' | 'done' | 'failed';
  written?: number;
  total?: number;
  percent?: number;
  label?: string;
  error?: string | null;
  updated_at?: number;
}

export type ScriptDetailPhase = 'writing' | 'interrupted' | 'failed';

// The backend's SCRIPT_DETAIL_STALL_SECONDS default: a record that has not moved for this long lost its thread.
const STALL_SECONDS = 1200;

export function scriptDetailPhase(record: unknown, nowSeconds = Date.now() / 1000): ScriptDetailPhase | null {
  if (!record || typeof record !== 'object') return null;
  const detail = record as ScriptDetailRecord;
  if (detail.status === 'failed') return 'failed';
  if (detail.status !== 'writing') return null;
  const moved = Number(detail.updated_at) || 0;
  return moved && nowSeconds - moved > STALL_SECONDS ? 'interrupted' : 'writing';
}
