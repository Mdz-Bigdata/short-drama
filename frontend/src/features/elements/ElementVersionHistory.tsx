import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { History, LoaderCircle, RotateCcw, X } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import type { ElementItem } from './elementTypes';
import {
  fetchRevisions,
  fetchUsages,
  relativeTime,
  restoreRevision,
  revisionReasonLabel,
  syncCounts,
  usageShotLabel,
  type ElementRevision,
  type ElementUsage,
  type WithSync,
} from './elementVersions';
import './ElementVersionHistory.css';

type Loaded<T> = { state: 'loading' } | { state: 'ready'; items: T[] } | { state: 'error'; message: string };

const errorText = (reason: unknown) => (reason instanceof Error ? reason.message : t('加载失败'));

/** 一个资产引用在哪些镜头：项目名 · 场景 · 第 N 镜，并标出在分镜 / 视频里。 */
export function ElementUsageList({ usages }: { usages: ElementUsage[] }) {
  if (!usages.length) return <p className="element-versions__empty">{t('还没有镜头用到它')}</p>;
  return (
    <ul className="element-usage-list">
      {usages.map((usage, index) => (
        <li key={`${usage.task_id}:${usage.shot_uid ?? usage.shot_id ?? index}`}>
          <span>{[usage.title || usage.task_id, usageShotLabel(usage)].filter(Boolean).join(' · ')}</span>
          {usage.in_storyboard && <small className="element-usage-flag">{t('分镜')}</small>}
          {usage.in_video && <small className="element-usage-flag">{t('视频')}</small>}
        </li>
      ))}
    </ul>
  );
}

/**
 * 资产的版本记录：每一版改了什么、什么时候改的、和现在有什么不同，可以恢复到任意一版；
 * 下面列出引用它的镜头，恢复前就知道会牵动哪些。
 */
export function ElementVersionHistory({ item, onClose, onRestored }: {
  item: ElementItem;
  onClose: () => void;
  /** 恢复成功：新的资产详情、标成过期的镜头和片段数、恢复到的版本号。 */
  onRestored: (updated: ElementItem, counts: { shotsMarked: number; clipsMarked: number }, version: number) => void;
}) {
  const [revisions, setRevisions] = useState<Loaded<ElementRevision>>({ state: 'loading' });
  const [usages, setUsages] = useState<Loaded<ElementUsage>>({ state: 'loading' });
  const [restoring, setRestoring] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    void fetchRevisions(item.id)
      .then(items => { if (live) setRevisions({ state: 'ready', items }); })
      .catch(reason => { if (live) setRevisions({ state: 'error', message: errorText(reason) }); });
    void fetchUsages(item.id)
      .then(items => { if (live) setUsages({ state: 'ready', items }); })
      .catch(reason => { if (live) setUsages({ state: 'error', message: errorText(reason) }); });
    return () => { live = false; };
  }, [item.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && restoring === null) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, restoring]);

  const restore = async (revision: ElementRevision) => {
    if (restoring !== null) return;
    const usageCount = usages.state === 'ready' ? usages.items.length : 0;
    const question = usageCount
      ? t('恢复到 v{0}？{1} 个镜头引用了它，会标记为需重画或重跑。', [revision.version, usageCount])
      : t('恢复到 v{0}？当前内容会另存为新的一版，随时可以再换回来。', [revision.version]);
    if (!window.confirm(question)) return;
    setRestoring(revision.revision);
    setError('');
    try {
      const updated = await restoreRevision(item.id, revision.revision);
      // sync 只用来数过期的镜头，不存到资产上。
      const detail: Partial<WithSync<ElementItem>> = { ...updated };
      delete detail.sync;
      onRestored({ ...item, ...detail }, syncCounts(updated), revision.version);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('恢复失败，请稍后重试。'));
    } finally {
      setRestoring(null);
    }
  };

  const title = t('“{0}”的版本记录', [item.name]);
  return createPortal(
    <div className="element-versions__backdrop" onClick={event => { if (event.target === event.currentTarget && restoring === null) onClose(); }}>
      <div className="element-versions" role="dialog" aria-modal="true" aria-label={title}>
        <header className="element-versions__header">
          <h2><History size={16} aria-hidden="true" /> {title}</h2>
          <span>{t('当前 v{0}', [item.version])}</span>
          <button type="button" onClick={onClose} aria-label={t('关闭版本记录')} disabled={restoring !== null}><X size={16} /></button>
        </header>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="element-versions__section" aria-label={t('历史版本')}>
          {revisions.state === 'loading' && <p className="element-versions__empty"><LoaderCircle className="spin" size={14} /> {t('正在读取版本记录…')}</p>}
          {revisions.state === 'error' && <p className="element-versions__empty" role="alert">{t('版本记录读取失败：{0}', [revisions.message])}</p>}
          {revisions.state === 'ready' && !revisions.items.length && <p className="element-versions__empty">{t('还没有历史版本')}</p>}
          {revisions.state === 'ready' && revisions.items.length > 0 && (
            <ol className="element-revision-list">
              {revisions.items.map(revision => {
                const current = revision.version === item.version;
                const renamed = revision.name && revision.name !== item.name;
                const described = (revision.description ?? '') !== (item.description ?? '');
                const images = revision.files.filter(file => file.url);
                return (
                  <li key={revision.revision} aria-label={t('版本 v{0}', [revision.version])} className={current ? 'is-current' : ''}>
                    <div className="element-revision__head">
                      <strong>{t('版本 v{0}', [revision.version])}</strong>
                      <span>{[revisionReasonLabel(revision.reason), relativeTime(revision.created_at)].filter(Boolean).join(' · ')}</span>
                      {current
                        ? <small className="element-usage-flag">{t('当前版本')}</small>
                        : (
                          <button
                            type="button"
                            onClick={() => { void restore(revision); }}
                            disabled={restoring !== null}
                            aria-busy={restoring === revision.revision}
                          >
                            {restoring === revision.revision ? <LoaderCircle className="spin" size={13} /> : <RotateCcw size={13} />}
                            {' '}{t('恢复到这个版本')}
                          </button>
                        )}
                    </div>
                    {!current && renamed && <p className="element-revision__diff">{t('名称：{0} → 现在 {1}', [revision.name, item.name])}</p>}
                    {!current && described && (
                      <p className="element-revision__diff">{t('描述：{0}', [revision.description || t('（空）')])}</p>
                    )}
                    {images.length > 0 && (
                      <div className="element-revision__files">
                        {images.slice(0, 6).map((file, index) => (
                          <img key={`${file.slot}:${index}`} src={apiUrl(file.url!)} alt={t('v{0} {1}', [revision.version, file.slot])} loading="lazy" />
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </section>
        <section className="element-versions__section" aria-label={t('被引用')}>
          <h3>{t('被引用')}{usages.state === 'ready' ? ` ${usages.items.length}` : ''}</h3>
          {usages.state === 'loading' && <p className="element-versions__empty"><LoaderCircle className="spin" size={14} /> {t('正在查找引用它的镜头…')}</p>}
          {usages.state === 'error' && <p className="element-versions__empty">{t('引用读取失败：{0}', [usages.message])}</p>}
          {usages.state === 'ready' && <ElementUsageList usages={usages.items} />}
        </section>
      </div>
    </div>,
    document.body,
  );
}
