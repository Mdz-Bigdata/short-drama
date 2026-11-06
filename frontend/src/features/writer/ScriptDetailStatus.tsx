import { useEffect, useState } from 'react';
import { ListOrdered, LoaderCircle, TriangleAlert } from 'lucide-react';

import type { ScriptDetailPhase, ScriptDetailRecord } from './scriptDetail';
import { fetchScreenwritingState, type ScreenwritingLedgerEntry } from './screenwritingApi';
import { t } from '../../i18n';

export function ScriptDetailBanner({
  record,
  phase,
  onShowOutline,
}: {
  record: ScriptDetailRecord;
  phase: ScriptDetailPhase;
  onShowOutline?: () => void;
}) {
  const written = Number(record.written) || 0;
  const total = Number(record.total) || 0;
  const percent = Math.max(0, Math.min(100, Number(record.percent) || 0));
  const writing = phase === 'writing';
  return (
    <section className={`writer-detail-banner${writing ? '' : ' is-warning'}`} role="status" aria-live="polite">
      {writing
        ? <LoaderCircle className="writer-detail-banner__icon is-spinning" aria-hidden="true" />
        : <TriangleAlert className="writer-detail-banner__icon" aria-hidden="true" />}
      <div className="writer-detail-banner__body">
        <strong>
          {writing
            ? t('剧本大纲已完成，详细剧本正在后台撰写')
            : phase === 'failed' ? t('详细剧本后台撰写失败') : t('详细剧本后台撰写已中断')}
        </strong>
        <p>
          {writing
            ? t('已写完 {written}/{total} 集，全部写完后一次性显示。角色设计可以先开始，分镜会等剧本写完。', { written, total })
            : written > 0
              ? t('已写完 {written}/{total} 集并已保留。点「补写」从缺的那一集接着写。', { written, total })
              : t('还没有写完的集。点「补写」重新开始写。')}
          {!writing && record.error ? ` ${record.error}` : ''}
        </p>
        {writing && (
          <div className="writer-detail-banner__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}
            aria-label={t('详细剧本撰写进度')}>
            <span style={{ width: `${percent}%` }} />
          </div>
        )}
        {writing && record.label && <small>{record.label}</small>}
      </div>
      {onShowOutline && (
        <button type="button" className="writer-outline-button" onClick={onShowOutline}>
          <ListOrdered aria-hidden="true" /> {t('查看分集大纲')}
        </button>
      )}
    </section>
  );
}

/** The episode ledger as a read-only outline: what there is to read while the episodes are written. */
export function LedgerOutline({ taskId, refreshKey }: { taskId: string; refreshKey?: string }) {
  const [ledger, setLedger] = useState<ScreenwritingLedgerEntry[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchScreenwritingState(taskId, controller.signal)
      .then(state => { setLedger(state.available ? state.ledger : []); setFailed(false); })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setFailed(true);
      });
    return () => controller.abort();
  }, [taskId, refreshKey]);

  if (failed) return <p className="writer-outline-warning" role="status">{t('分集大纲暂时读不到，请稍后刷新。')}</p>;
  if (!ledger) return <p className="writer-ledger-outline__empty">{t('正在读取分集大纲…')}</p>;
  if (!ledger.length) return <p className="writer-ledger-outline__empty">{t('还没有分集大纲。')}</p>;
  return (
    <ol className="writer-ledger-outline">
      {ledger.map(entry => (
        <li key={entry.episode}>
          <header>
            <span>{t('第 {0} 集', [entry.episode])}</span>
            <strong>{entry.title || t('未命名')}</strong>
          </header>
          {entry.hook && <p className="writer-ledger-outline__hook">{entry.hook}</p>}
          {entry.storyBeats.length > 0 && (
            <ul>{entry.storyBeats.map((beat, index) => <li key={index}>{beat}</li>)}</ul>
          )}
          {entry.nextEpisodeTeaser && <p className="writer-ledger-outline__teaser">{t('下集')}：{entry.nextEpisodeTeaser}</p>}
        </li>
      ))}
    </ol>
  );
}
