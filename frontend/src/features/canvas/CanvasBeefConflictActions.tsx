import { useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { t } from '../../i18n';
import { overwriteWithMine, planOverwrite, type OverwritePlan } from './canvasBeefSave';
import type { CanvasDoc, CanvasRecord } from './canvasTypes';
import './CanvasBeef.css';

export interface CanvasBeefConflictActionsProps {
  projectId: string;
  canvasId: string;
  mine: CanvasDoc;
  clientId?: string;
  onOverwritten: (record: CanvasRecord) => void;
}

/** Beside "load latest" and "save as a new canvas": keep mine over the newer version, after saying what that replaces. */
export function CanvasBeefConflictActions({ projectId, canvasId, mine, clientId, onOverwritten }: CanvasBeefConflictActionsProps) {
  const [plan, setPlan] = useState<OverwritePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const ask = async () => {
    setBusy(true);
    setError('');
    try {
      setPlan(await planOverwrite(projectId, canvasId, mine));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('读不到服务器上的版本'));
    } finally {
      setBusy(false);
    }
  };

  const overwrite = async () => {
    if (!plan) return;
    setBusy(true);
    setError('');
    try {
      onOverwritten(await overwriteWithMine(projectId, canvasId, plan.theirs, mine, clientId));
      setPlan(null);
    } catch (err) {
      setPlan(null);
      setError(err instanceof Error ? err.message : t('覆盖没有完成'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="canvas-beef-conflict">
      {!plan ? (
        <button type="button" onClick={() => void ask()} disabled={busy}>
          {busy && <LoaderCircle className="spin" size={13} />} {t('用我的覆盖')}
        </button>
      ) : (
        <span role="group" aria-label={t('确认覆盖')}>
          {t('将用我的 {0} 个节点替换服务器上的第 {1} 版（{2} 个节点）；那一版会留在历史里，可以恢复。', [plan.mineNodes, plan.theirs, plan.theirNodes])}
          <button type="button" onClick={() => setPlan(null)} disabled={busy}>{t('算了')}</button>
          <button type="button" className="is-primary" onClick={() => void overwrite()} disabled={busy}>{t('确认覆盖')}</button>
        </span>
      )}
      {error && <span className="inline-error" role="alert">{error}</span>}
    </span>
  );
}
