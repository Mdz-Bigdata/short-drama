import { useEffect, useState } from 'react';
import { Check, LoaderCircle, RotateCcw, ScanSearch, X } from 'lucide-react';

import { t } from '../../i18n';
import { ASSETS_CHANGED_EVENT } from '../elements/assetEvents';
import {
  extractChapter, readChapterAssets, settleChapterAsset,
  type ChapterAssetItem, type ChapterAssetsView, type ChapterList,
} from './chapterAssetsApi';
import './ChapterAssets.css';

const LISTS: ChapterList[] = ['characters', 'scenes', 'props'];
const LIST_LABELS: Record<ChapterList, string> = { characters: '角色', scenes: '场景', props: '道具' };

/** Characters, scenes and props read chapter by chapter into a list; an entry reaches the asset library only once confirmed. */
export function ChapterAssets({ taskId }: { taskId: string }) {
  const [view, setView] = useState<ChapterAssetsView | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showSettled, setShowSettled] = useState(false);

  useEffect(() => {
    let active = true;
    readChapterAssets(taskId)
      .then(data => { if (active && Array.isArray(data?.chapters)) setView(data); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : t('章节资产加载失败')); });
    return () => { active = false; };
  }, [taskId]);

  if (!view) return error ? <div className="inline-error" role="alert">{error}</div> : null;

  const act = async (key: string, run: () => Promise<ChapterAssetsView>, said: (data: ChapterAssetsView) => string) => {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const data = await run();
      setView(data);
      setNotice(said(data));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('操作没有完成'));
    } finally {
      setBusy('');
    }
  };

  const extract = (chapterId: string, title: string) => act(`extract:${chapterId}`, () => extractChapter(taskId, chapterId), data => {
    const added = data.added ?? { characters: 0, scenes: 0, props: 0 };
    return t('「{0}」提取完成：新增角色 {1}、场景 {2}、道具 {3}', [title, added.characters, added.scenes, added.props]);
  });

  const settle = (item: ChapterAssetItem, action: 'confirm' | 'dismiss' | 'restore') => act(`${action}:${item.id}`, async () => {
    const data = await settleChapterAsset(taskId, item.id, action);
    if (action === 'confirm') window.dispatchEvent(new CustomEvent(ASSETS_CHANGED_EVENT, { detail: { reason: 'chapter-assets' } }));
    return data;
  }, () => (action === 'confirm' ? t('「{0}」已放进资产库并关联到本项目', [item.name]) : action === 'dismiss' ? t('已忽略「{0}」', [item.name]) : t('「{0}」回到待确认', [item.name])));

  const titleOf = new Map(view.chapters.map(chapter => [chapter.id, chapter.title]));
  const pending = view.items.filter(item => item.status === 'pending');
  const settled = view.items.filter(item => item.status !== 'pending');

  const row = (item: ChapterAssetItem) => (
    <li key={item.id} className={`chapter-assets__item chapter-assets__item--${item.status}`}>
      <div>
        <strong>{item.name}</strong>
        {item.known && <span className="chapter-assets__tag">{t('项目里已有')}</span>}
        {item.aliases.length > 0 && <small>{t('又称 {0}', [item.aliases.join('、')])}</small>}
        {item.description && <p>{item.description}</p>}
        <small>{t('出自 {0}', [item.chapters.map(id => titleOf.get(id) ?? id).join('、')])}</small>
      </div>
      <div className="chapter-assets__item-actions">
        {item.status === 'pending' ? (
          <>
            <button type="button" disabled={busy !== ''} onClick={() => void settle(item, 'confirm')} aria-label={t('确认「{0}」', [item.name])}>
              {busy === `confirm:${item.id}` ? <LoaderCircle className="spin" size={13} /> : <Check size={13} />}{t('确认')}
            </button>
            <button type="button" disabled={busy !== ''} onClick={() => void settle(item, 'dismiss')} aria-label={t('忽略「{0}」', [item.name])}>
              <X size={13} />{t('忽略')}
            </button>
          </>
        ) : item.status === 'dismissed' ? (
          <button type="button" disabled={busy !== ''} onClick={() => void settle(item, 'restore')} aria-label={t('恢复「{0}」', [item.name])}>
            <RotateCcw size={13} />{t('恢复')}
          </button>
        ) : <span className="chapter-assets__done">{t('已入库')}</span>}
      </div>
    </li>
  );

  return (
    <section className="chapter-assets" aria-labelledby="chapter-assets-title">
      <header className="chapter-assets__header">
        <div>
          <ScanSearch aria-hidden="true" />
          <h3 id="chapter-assets-title">{t('按章节提取资产')}</h3>
        </div>
        <p>{t('每一章调用一次文本模型（按用量计费），找出角色、场景和道具放进待确认清单；确认后才放进资产库。')}</p>
      </header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="command-result" role="status">{notice}</div>}
      {view.chapters.length === 0 ? (
        <p className="chapter-assets__empty">{t('还没有章节：先在上面的文库放入原文，或先写出剧本。')}</p>
      ) : (
        <ol className="chapter-assets__chapters">
          {view.chapters.map(chapter => (
            <li key={chapter.id}>
              <span className="chapter-assets__chapter-title">{chapter.title}</span>
              <small>
                {chapter.counts
                  ? t('角色 {0} · 场景 {1} · 道具 {2}', [chapter.counts.characters, chapter.counts.scenes, chapter.counts.props])
                  : t('{0} 字，未提取', [chapter.chars])}
                {chapter.changed && ` · ${t('原文改过，可重新提取')}`}
              </small>
              <button type="button" disabled={busy !== ''} onClick={() => void extract(chapter.id, chapter.title)}>
                {busy === `extract:${chapter.id}` ? <LoaderCircle className="spin" size={13} /> : <ScanSearch size={13} />}
                {chapter.counts ? t('重新提取') : t('提取')}
              </button>
            </li>
          ))}
        </ol>
      )}
      {pending.length > 0 && (
        <div className="chapter-assets__lists">
          {LISTS.map(list => {
            const entries = pending.filter(item => item.list === list);
            if (!entries.length) return null;
            return (
              <div key={list}>
                <h4>{t('待确认的{0}（{1}）', [t(LIST_LABELS[list]), entries.length])}</h4>
                <ul>{entries.map(row)}</ul>
              </div>
            );
          })}
        </div>
      )}
      {settled.length > 0 && (
        <details open={showSettled} onToggle={event => setShowSettled((event.target as HTMLDetailsElement).open)}>
          <summary>{t('已处理 {0} 条', [settled.length])}</summary>
          <ul>{settled.map(row)}</ul>
        </details>
      )}
    </section>
  );
}
