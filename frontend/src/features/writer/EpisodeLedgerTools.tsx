import { useCallback, useEffect, useMemo, useState } from 'react';
import { GitMerge, Plus, RefreshCw, Scissors, Trash2 } from 'lucide-react';

import { ApiError } from '../../api/client';
import {
  adoptReplan,
  applyLedgerOperation,
  discardReplan,
  discardedEpisodesOf,
  fetchLedger,
  fetchLedgerImpact,
  fetchLedgerSource,
  requestReplan,
  type LedgerEntryView,
  type LedgerOperationBody,
  type LedgerView,
} from './screenwritingApi';
import { around, sentenceBoundaries } from './sourceSplitting';
import { t } from '../../i18n';

const ORIGIN_LABEL: Record<LedgerEntryView['origin'], string> = {
  cut: '切自整本源文',
  own: '自带原文',
  none: '无原文',
};

const RELATION_LABEL: Record<string, string> = {
  same: '边界不变',
  overlaps: '重新划分',
  new: '新增',
};

type Submit = (body: { confirm_discard: number[]; confirm_invalidate: boolean }) => Promise<LedgerView>;

interface Props {
  taskId: string;
  /** Called after the ledger changed, so the panel reloads the episode list. */
  onChanged: () => void;
  /** Open the full screenplay of a written episode (the 来源 cell links there). */
  onOpenEpisode?: (episode: number) => void;
}

export function EpisodeLedgerTools({ taskId, onChanged, onOpenEpisode }: Props) {
  const [view, setView] = useState<LedgerView | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [splitting, setSplitting] = useState<number | null>(null);
  const [excerpt, setExcerpt] = useState<{ start: number; text: string } | null>(null);
  const [splitPoint, setSplitPoint] = useState('');
  const [splitTitle, setSplitTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [createTitle, setCreateTitle] = useState('');
  const [createText, setCreateText] = useState('');
  const [createKind, setCreateKind] = useState<'novel' | 'screenplay'>('novel');
  const [createAfter, setCreateAfter] = useState('');

  const load = useCallback((signal?: AbortSignal) => fetchLedger(taskId, signal)
    .then(data => { setView(data); setError(''); })
    .catch(caught => {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setError(caught instanceof ApiError && caught.status === 404 ? '' : '分集账本读取失败。');
    }), [taskId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const run = async (submit: Submit, describe: string, { changesEpisodes = true } = {}) => {
    setBusy(true);
    setNotice('');
    try {
      let confirmDiscard: number[] = [];
      let confirmInvalidate = false;
      let result: LedgerView | null = null;
      // A 409 either names the written episodes the step throws away (confirm each,
      // after showing what they hold) or says downstream outputs would be archived.
      for (let attempt = 0; attempt < 3 && !result; attempt += 1) {
        try {
          result = await submit({ confirm_discard: confirmDiscard, confirm_invalidate: confirmInvalidate });
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 409) throw caught;
          const message = String(caught.message);
          const episodes = discardedEpisodesOf(message);
          if (episodes.length) {
            const impact = await fetchLedgerImpact(taskId, episodes).then(data => data.episodes).catch(() => []);
            const lines = episodes.map(number => {
              const hit = impact.find(item => item.episode === number);
              const detail = hit ? `${hit.scenes} 个分镜${hit.has_prose ? '、正文' : ''}` : '已写出的内容';
              return `第 ${number} 集${hit?.title ? `《${hit.title}》` : ''}：${detail}`;
            });
            if (!window.confirm(t('{0}会丢掉以下已写出的集，并重新写出受影响的集：\\n{1}\\n是否继续？', [describe, lines.join('\n')]))) {
              setNotice(t('已取消。'));
              return;
            }
            confirmDiscard = episodes;
            continue;
          }
          if (/归档|下游|成片|角色、分镜/.test(message)) {
            if (!window.confirm(t('这一步会归档当前角色、分镜和成片，并从编剧阶段重新开始。旧成果仍保留在版本归档中。是否继续？'))) {
              setNotice(t('已取消。'));
              return;
            }
            confirmInvalidate = true;
            continue;
          }
          throw caught;
        }
      }
      if (!result) return;
      setView(result);
      setSplitting(null);
      setExcerpt(null);
      setCreating(false);
      const parts: string[] = [];
      if (result.created?.length) parts.push(`新写出第 ${result.created.join('、')} 集`);
      if (result.discarded?.length) parts.push(`丢弃了第 ${result.discarded.join('、')} 集的旧内容`);
      if (result.renumbered && Object.keys(result.renumbered).length) {
        parts.push(`重新编号：${Object.entries(result.renumbered).map(([from, to]) => `${from}→${to}`).join('，')}`);
      }
      parts.push(...(result.notes ?? []));
      setNotice(parts.length ? `${describe}完成，${parts.join('；')}。` : `${describe}完成。`);
      if (changesEpisodes) onChanged();
    } catch (caught) {
      setNotice(caught instanceof ApiError && caught.message ? caught.message : `${describe}失败，请稍后重试。`);
    } finally {
      setBusy(false);
    }
  };

  const operate = (body: Omit<LedgerOperationBody, 'confirm_discard' | 'confirm_invalidate'>, describe: string) =>
    run(confirm => applyLedgerOperation(taskId, { ...body, ...confirm }), describe);

  const openSplit = async (entry: LedgerEntryView) => {
    if (!entry.source_range) return;
    setSplitting(entry.episode);
    setSplitPoint('');
    setSplitTitle('');
    setExcerpt(null);
    try {
      const data = await fetchLedgerSource(taskId, entry.source_range.start, entry.source_range.end);
      setExcerpt({ start: data.start, text: data.text });
    } catch {
      setNotice(t('该集原文读取失败。'));
      setSplitting(null);
    }
  };

  const boundaries = useMemo(() => (excerpt ? sentenceBoundaries(excerpt.text) : []), [excerpt]);
  const splitRelative = Number(splitPoint);
  const splitPreview = excerpt && splitRelative > 0 && splitRelative < excerpt.text.length ? around(excerpt.text, splitRelative) : null;

  const replan = (fromEpisode: number) =>
    run(async () => requestReplan(taskId, fromEpisode), `从第 ${fromEpisode} 集起重新规划`, { changesEpisodes: false });

  const adopt = (deleteReplaced: boolean) =>
    run(confirm => adoptReplan(taskId, { delete_replaced: deleteReplaced, ...confirm }), '采纳候选规划');

  const discard = async () => {
    setBusy(true);
    try {
      setView(await discardReplan(taskId));
      setNotice(t('已放弃候选规划。'));
    } catch {
      setNotice(t('放弃候选规划失败。'));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="writer-empty" role="status">{error}</p>;
  if (!view) return null;

  const entries = view.entries;
  const candidate = view.candidate;

  return (
    <section className="writer-ledger" aria-label={t('分集账本操作')}>
      <header className="writer-ledger__head">
        <h3>{t('分集账本')}</h3>
        <span>{entries.length} 集 · 源文 {view.source_length} 字 · 未切分 {view.unsplit.length} 段</span>
        <button type="button" disabled={busy} onClick={() => setCreating(current => !current)}>
          <Plus aria-hidden="true" /> {t('新建一集')}
        </button>
      </header>
      {notice && <p className="writer-screenwriting__notice" role="status">{notice}</p>}

      {creating && (
        <form
          className="writer-ledger__form"
          onSubmit={event => {
            event.preventDefault();
            void operate({
              operation: 'create',
              title: createTitle,
              text: createText,
              source_kind: createText.trim() ? createKind : null,
              after: createAfter === '' ? null : Number(createAfter),
            }, '新建一集');
          }}
        >
          <label>{t('标题')}<input value={createTitle} onChange={event => setCreateTitle(event.target.value)} placeholder={t('留空则按序号命名')} /></label>
          <label>{t('排在')}<select value={createAfter} onChange={event => setCreateAfter(event.target.value)}>
            <option value="">{t('最后')}</option>
            <option value="0">{t('最前')}</option>
            {entries.map(entry => <option key={entry.episode} value={entry.episode}>第 {entry.episode} 集之后</option>)}
          </select></label>
          <label>{t('体裁')}<select value={createKind} onChange={event => setCreateKind(event.target.value as 'novel' | 'screenplay')} disabled={!createText.trim()}>
            <option value="novel">{t('小说')}</option>
            <option value="screenplay">{t('成品剧本')}</option>
          </select></label>
          <label className="writer-ledger__wide">{t('这一集自己的原文（可留空，留空则按大纲创作）')}
            <textarea rows={4} value={createText} onChange={event => setCreateText(event.target.value)} />
          </label>
          <div className="writer-screenwriting__actions">
            <button type="submit" className="is-primary" disabled={busy}>{t('创建并写出')}</button>
            <button type="button" onClick={() => setCreating(false)}>{t('取消')}</button>
          </div>
        </form>
      )}

      <table className="writer-ledger__table">
        <thead>
          <tr><th>{t('集')}</th><th>{t('来源')}</th><th>{t('原文')}</th><th>{t('长度')}</th><th>{t('状态')}</th><th>{t('操作')}</th></tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => {
            const next = entries[index + 1];
            const canMerge = entry.origin === 'cut' && next?.origin === 'cut';
            const gapBetween = canMerge && entry.source_range && next.source_range && next.source_range.start > entry.source_range.end;
            return (
              <tr key={entry.episode} className={entry.ledger_status === 'stale' ? 'is-stale' : ''}>
                <td><span className="writer-screenwriting__episode">第 {entry.episode} 集</span><strong>{entry.title || '未命名'}</strong></td>
                <td>
                  {onOpenEpisode && entry.written ? (
                    <button
                      type="button"
                      className="writer-ledger__source-link"
                      title={t('查看本集完整剧本')}
                      aria-label={`查看第 ${entry.episode} 集完整剧本`}
                      onClick={() => onOpenEpisode(entry.episode)}
                    >
                      {t(ORIGIN_LABEL[entry.origin])}{entry.source_name ? ` · ${entry.source_name}` : ''}
                    </button>
                  ) : (
                    <>{t(ORIGIN_LABEL[entry.origin])}{entry.source_name ? ` · ${entry.source_name}` : ''}</>
                  )}
                </td>
                <td className="writer-ledger__excerpt">
                  {entry.units > 0 ? <><span>{entry.opening}</span>…<span>{entry.closing}</span></> : '—'}
                </td>
                <td>{entry.units ? `${entry.units} ${entry.units_noun}` : '—'}</td>
                <td>{entry.written ? t('已写出') : t('待写出')}{entry.ledger_status === 'stale' ? '（已过期）' : ''}</td>
                <td className="writer-ledger__ops">
                  {entry.origin === 'cut' && (
                    <>
                      <button type="button" disabled={busy} onClick={() => { void openSplit(entry); }} aria-label={`拆分第 ${entry.episode} 集`}><Scissors aria-hidden="true" /> {t('拆分')}</button>
                      {canMerge && (
                        <button type="button" disabled={busy} aria-label={`合并第 ${entry.episode} 集与下一集`}
                          onClick={() => { void operate({ operation: 'merge_with_next', episode: entry.episode, include_unsplit: Boolean(gapBetween) }, `合并第 ${entry.episode}、${next.episode} 集`); }}>
                          <GitMerge aria-hidden="true" /> {t('并入下一集')}
                        </button>
                      )}
                      <button type="button" disabled={busy || Boolean(candidate)} aria-label={`从第 ${entry.episode} 集起重新规划`}
                        onClick={() => { void replan(entry.episode); }}>
                        <RefreshCw aria-hidden="true" /> {t('自此重规划')}
                      </button>
                    </>
                  )}
                  {entry.origin !== 'cut' && index > 0 && (
                    <button type="button" disabled={busy} onClick={() => { void operate({ operation: 'move', episode: entry.episode, after: index === 1 ? 0 : entries[index - 2].episode }, `上移第 ${entry.episode} 集`); }}>{t('上移')}</button>
                  )}
                  {entry.origin !== 'cut' && next && (
                    <button type="button" disabled={busy} onClick={() => { void operate({ operation: 'move', episode: entry.episode, after: next.episode }, `下移第 ${entry.episode} 集`); }}>{t('下移')}</button>
                  )}
                  <button type="button" disabled={busy} className="is-danger" aria-label={`删除第 ${entry.episode} 集`}
                    onClick={() => { void operate({ operation: 'delete', episode: entry.episode }, `删除第 ${entry.episode} 集`); }}>
                    <Trash2 aria-hidden="true" /> {t('删除')}
                  </button>
                </td>
              </tr>
            );
          })}
          {view.unsplit.map(span => (
            <tr key={`gap-${span.start}`} className="is-gap">
              <td colSpan={3}>未切分原文：第 {span.start}–{span.end} 字</td>
              <td>{span.end - span.start} 字</td>
              <td>{t('未成集')}</td>
              <td className="writer-ledger__ops">
                <button type="button" disabled={busy} onClick={() => { void operate({ operation: 'cut_unsplit', start: span.start, end: span.end }, '把未切分原文切为一集'); }}>
                  <Scissors aria-hidden="true" /> {t('切为一集')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {splitting !== null && (
        <form
          className="writer-ledger__form"
          aria-label={`拆分第 ${splitting} 集`}
          onSubmit={event => {
            event.preventDefault();
            if (!excerpt || !splitPreview) return;
            void operate({ operation: 'split', episode: splitting, offset: excerpt.start + splitRelative, title: splitTitle }, `拆分第 ${splitting} 集`);
          }}
        >
          <p>第 {splitting} 集在哪里断开？后半段成为新的一集，排在它之后。</p>
          {!excerpt && <p className="writer-empty">{t('正在读取原文…')}</p>}
          {excerpt && (
            <>
              <label>{t('按句子')}<select value={splitPoint} onChange={event => setSplitPoint(event.target.value)}>
                <option value="">{t('选择断句位置')}</option>
                {boundaries.map(point => {
                  const context = around(excerpt.text, point, 10);
                  return <option key={point} value={point}>{`…${context.before} ┃ ${context.after}…`}</option>;
                })}
              </select></label>
              <label>{t('或字符位置')}<input type="number" min={1} max={Math.max(1, excerpt.text.length - 1)} value={splitPoint} onChange={event => setSplitPoint(event.target.value)} /></label>
              <label>{t('新集标题')}<input value={splitTitle} onChange={event => setSplitTitle(event.target.value)} placeholder={t('留空则沿用原标题（续）')} /></label>
              {splitPreview && (
                <p className="writer-ledger__preview">
                  <span>{splitPreview.before}</span><b>┃</b><span>{splitPreview.after}</span>
                  <small>前半段 {splitRelative} 字，后半段 {excerpt.text.length - splitRelative} 字</small>
                </p>
              )}
              <div className="writer-screenwriting__actions">
                <button type="submit" className="is-primary" disabled={busy || !splitPreview}>{t('在此拆分')}</button>
                <button type="button" onClick={() => { setSplitting(null); setExcerpt(null); }}>{t('取消')}</button>
              </div>
            </>
          )}
        </form>
      )}

      {candidate && (
        <div className="writer-ledger__candidate" role="region" aria-label={t('候选重规划')}>
          <header>
            <h4>候选重规划 · 从第 {candidate.from_episode} 集起</h4>
            <span>原 {candidate.old_count} 集（均 {candidate.old_average_units} 字） → 新 {candidate.new_count} 集（均 {candidate.new_average_units} 字）</span>
          </header>
          {!candidate.adoptable && <p className="writer-screenwriting__stale" role="status">{t('源文或账本在规划后变过，这份候选已不能采纳。')}</p>}
          <ol>
            {candidate.entries.map(row => (
              <li key={row.position}>
                <strong>{row.title || `新第 ${row.position} 集`}</strong>
                <span>{row.units} 字</span>
                <em>{RELATION_LABEL[row.relation] || row.relation}{row.overlaps.length ? `（原第 ${row.overlaps.join('、')} 集）` : ''}</em>
                {row.hook && <small>{row.hook}</small>}
              </li>
            ))}
          </ol>
          {candidate.replaced_written.length > 0 && (
            <p>采纳会替换已写出的第 {candidate.replaced_written.join('、')} 集：保留则它们留在末尾（无原文、已过期），删除则直接丢弃。</p>
          )}
          <div className="writer-screenwriting__actions">
            <button type="button" className="is-primary" disabled={busy || !candidate.adoptable} onClick={() => { void adopt(false); }}>{t('采纳并保留旧集')}</button>
            <button type="button" disabled={busy || !candidate.adoptable} onClick={() => { void adopt(true); }}>{t('采纳并删除旧集')}</button>
            <button type="button" disabled={busy} onClick={() => { void discard(); }}>{t('放弃候选')}</button>
          </div>
        </div>
      )}
    </section>
  );
}
