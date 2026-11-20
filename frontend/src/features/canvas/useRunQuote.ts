import { useEffect, useState } from 'react';

import { t } from '../../i18n';
import { assessRun } from './canvasApi';
import { quoteLine, type QuoteLine } from './canvasComposer';

/** A quote waits this long after the last save, so typing does not ask for one per keystroke. */
export const QUOTE_DELAY_MS = 500;

export type RunQuote = (QuoteLine & { pending: false }) | { pending: true; text: string; tone: 'pending' };

/**
 * What a run of one node would cost, as the server's own admission sees it. The server reads the
 * saved canvas, so the quote is asked once the canvas is saved and again after every later save;
 * `refreshKey` asks again when something outside the document changed (an input finished).
 * Nothing is quoted while `nodeId` is null. An assessment spends nothing.
 */
export function useRunQuote(projectId: string, canvasId: string, nodeId: string | null, version: number, settled: boolean, refreshKey = ''): RunQuote | null {
  const [result, setResult] = useState<{ key: string; line: QuoteLine | null } | null>(null);
  const key = nodeId ? `${canvasId}:${nodeId}:${version}:${refreshKey}` : '';

  useEffect(() => {
    if (!nodeId || !settled) return undefined;
    let live = true;
    const timer = setTimeout(() => {
      assessRun(projectId, canvasId, [nodeId])
        .then(assessment => { if (live) setResult({ key, line: quoteLine(assessment, nodeId) }); })
        .catch(() => { if (live) setResult({ key, line: null }); });
    }, QUOTE_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [canvasId, key, nodeId, projectId, settled]);

  if (!nodeId) return null;
  if (result?.key === key) return result.line ? { ...result.line, pending: false } : null;
  return { pending: true, text: settled ? t('估价中…') : t('保存后估价'), tone: 'pending' };
}
