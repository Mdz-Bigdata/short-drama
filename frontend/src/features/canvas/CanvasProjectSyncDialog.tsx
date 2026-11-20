import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Crosshair, Loader2 } from 'lucide-react';

import { ApiError, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { applySync, fetchSyncReview, type SyncItem, type SyncResult, type SyncReview } from './canvasProjectSync';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function fieldLabel(field: SyncItem['field']) {
  if (field === 'prompt') return t('提示词');
  if (field === 'duration') return t('时长');
  return t('图片');
}

function Value({ item, value }: { item: SyncItem; value: SyncItem['canvas'] }) {
  if (value === null || value === '') return <span className="cn-sync__empty">{t('（空）')}</span>;
  if (item.field === 'picture') return <img className="cn-sync__thumb" src={apiUrl(String(value))} alt="" loading="lazy" />;
  if (item.field === 'duration') return <span>{t('{0} 秒', [value])}</span>;
  return <span className="cn-sync__text">{String(value)}</span>;
}

function ItemRow({ item, checked, onToggle, onJump }: { item: SyncItem; checked: boolean; onToggle: () => void; onJump: () => void }) {
  return (
    <li className={`cn-sync__item is-${item.state}`}>
      <div className="cn-row">
        <label className="cn-sync__pick">
          <input type="checkbox" checked={checked} onChange={onToggle} aria-label={t('用项目里的{0}：{1}', [fieldLabel(item.field), item.label])} />
          <strong>{item.label}</strong> <small>· {fieldLabel(item.field)}</small>
        </label>
        <span className="cn-grow" />
        <button type="button" className="cn-button is-quiet" onClick={onJump} aria-label={t('在画布上找到：{0}', [item.label])} title={t('在画布上找到')}>
          <Crosshair aria-hidden="true" />
        </button>
      </div>
      <div className="cn-sync__compare">
        <div><small>{t('画布上')}</small><Value item={item} value={item.canvas} /></div>
        <div><small>{t('项目里')}</small><Value item={item} value={item.project} /></div>
      </div>
    </li>
  );
}

/**
 * Bring the canvas up to date with the project's storyboard: lay out the shots it does not have, take
 * over what the project changed, and decide where both sides changed. Nothing is moved or deleted.
 */
export function CanvasProjectSyncDialog({ projectId, canvasId, clientId, prepare, onApplied, onJump, onClose }: {
  projectId: string;
  canvasId: string;
  /** This window, so the saved event of its own sync does not come back to it as news from elsewhere. */
  clientId?: string;
  /** Saves what is unsaved first, so the review describes the canvas on screen; rejects when it cannot be saved. */
  prepare: () => Promise<number>;
  onApplied: (nodeIds: string[]) => void | Promise<void>;
  /** Close the dialog and show this node on the canvas. */
  onJump: (nodeId: string) => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [review, setReview] = useState<SyncReview | null>(null);
  const [accepted, setAccepted] = useState<ReadonlySet<string>>(new Set());
  const [addNew, setAddNew] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [outdated, setOutdated] = useState(false);
  const [done, setDone] = useState<SyncResult | null>(null);

  useEffect(() => {
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  const load = useCallback(async (signal?: AbortSignal) => {
    setProblem('');
    setOutdated(false);
    setReview(null);
    try {
      await prepare();
      const value = await fetchSyncReview(projectId, canvasId, signal);
      if (signal?.aborted) return;
      setReview(value);
      setAccepted(new Set(value.items.filter(item => item.checked).map(item => item.id)));
      setAddNew(value.new.this_time > 0);
    } catch (error) {
      if (!signal?.aborted) setProblem(messageOf(error, t('读取同步内容失败')));
    }
  }, [canvasId, prepare, projectId]);

  useEffect(() => {
    const abort = new AbortController();
    void load(abort.signal);
    return () => abort.abort();
  }, [load]);

  const updates = useMemo(() => review?.items.filter(item => item.state === 'update') ?? [], [review]);
  const conflicts = useMemo(() => review?.items.filter(item => item.state === 'conflict') ?? [], [review]);
  const toggle = (id: string) => setAccepted(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const nothing = review && !review.new.shots && !review.items.length;
  const changes = (addNew && review ? review.new.this_time : 0) + accepted.size;
  // Applying with nothing ticked still records that the canvas keeps its own versions, so it is not asked again.
  const canApply = Boolean(review && !nothing && (changes > 0 || review.items.length > 0));

  const apply = async () => {
    if (!review || busy || !canApply) return;
    setBusy(true);
    setProblem('');
    try {
      const result = await applySync(projectId, canvasId, review, [...accepted], addNew, clientId);
      setDone(result);
      if (result.applied) await onApplied(result.node_ids);
    } catch (error) {
      const message = messageOf(error, t('同步失败'));
      setProblem(message);
      // The canvas or the project moved after this review: look again rather than apply something unseen.
      setOutdated(error instanceof ApiError && error.status === 409);
    } finally {
      setBusy(false);
    }
  };

  const title = t('从项目同步');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog cn-sync" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        {!review && !problem && <p className="cn-hint"><Loader2 className="cn-spin" aria-hidden="true" /> {t('对照项目分镜…')}</p>}

        {review && !done && (
          <>
            <p className="cn-hint">{t('把项目分镜的变化带到画布上：补上还没有的镜头，带过来项目里改了、画布上没动过的内容。画布上改过的不会被覆盖，节点不会被移动或删除。')}</p>
            {!review.storyboard && <p className="cn-hint">{t('项目还没有分镜。')}</p>}
            {review.storyboard && nothing && !review.notes.length && <p className="cn-dialog__cost"><CheckCircle2 aria-hidden="true" /> {t('画布和项目分镜一致。')}</p>}

            {review.new.shots > 0 && (
              <section className="cn-sync__section" aria-label={t('新镜头')}>
                <label className="cn-sync__pick">
                  <input type="checkbox" checked={addNew} disabled={!review.new.this_time} onChange={event => setAddNew(event.target.checked)} />
                  <strong>{t('铺上 {0} 个新镜头', [review.new.this_time])}</strong>
                </label>
                <ul className="cn-sync__scenes">
                  {review.new.scenes.filter(scene => scene.this_time).map(scene => (
                    <li key={scene.scene_id}>
                      {scene.scene_id} · {scene.on_canvas ? t('{0} 个，接在这一场原来那一排后面', [scene.new]) : t('{0} 个，新起一排', [scene.new])}
                    </li>
                  ))}
                </ul>
                {review.new.later > 0 && <p className="cn-hint">{t('其余 {0} 个镜头下次同步再铺（一次铺不完）。', [review.new.later])}</p>}
              </section>
            )}

            {updates.length > 0 && (
              <section className="cn-sync__section" aria-label={t('项目里改了')}>
                <h3>{t('项目里改了（画布上没动过）')}</h3>
                <ul className="cn-sync__items">
                  {updates.map(item => <ItemRow key={item.id} item={item} checked={accepted.has(item.id)} onToggle={() => toggle(item.id)} onJump={() => onJump(item.node_id)} />)}
                </ul>
              </section>
            )}

            {conflicts.length > 0 && (
              <section className="cn-sync__section" aria-label={t('两边不一样')}>
                <h3>{t('两边不一样')}</h3>
                <p className="cn-hint">{t('画布上也改过，或者这个节点是有同步之前铺的，看不出是哪边改的。默认保留画布上的；勾选的改用项目里的。')}</p>
                <ul className="cn-sync__items">
                  {conflicts.map(item => <ItemRow key={item.id} item={item} checked={accepted.has(item.id)} onToggle={() => toggle(item.id)} onJump={() => onJump(item.node_id)} />)}
                </ul>
              </section>
            )}

            {review.notes.length > 0 && (
              <section className="cn-sync__section" aria-label={t('只提示，不改动')}>
                <h3>{t('只提示，不改动')}</h3>
                <ul className="cn-sync__notes">
                  {review.notes.map(note => (
                    <li key={`${note.kind}:${note.node_id}`} className="cn-row">
                      <span>
                        <strong>{note.label || `${note.scene} · ${note.shot}`}</strong>
                        {'：'}{note.kind === 'gone' ? t('项目里已没有这一镜，节点留在画布上') : t('项目里这一镜已经有分镜图，这个首帧还是待生成')}
                      </span>
                      <span className="cn-grow" />
                      <button type="button" className="cn-button is-quiet" onClick={() => onJump(note.node_id)} aria-label={t('在画布上找到：{0}', [note.label])} title={t('在画布上找到')}>
                        <Crosshair aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {done && (
          <p className="cn-dialog__cost" role="status">
            <CheckCircle2 aria-hidden="true" />
            {done.applied ? t('已同步：铺了 {0} 个镜头，更新 {1} 个节点，保留画布上的 {2} 处', [done.shots, done.updated, done.kept]) : t('没有需要改的。')}
          </p>
        )}
        {problem && <p className="cn-error" role="alert">{problem}</p>}

        <footer className="cn-dialog__foot">
          {outdated && <button type="button" className="cn-button" onClick={() => { void load(); }}>{t('重新对照')}</button>}
          <button type="button" className="cn-button" onClick={onClose}>{done || nothing ? t('完成') : t('取消')}</button>
          {review && !done && !nothing && (
            <button type="button" className="cn-button is-primary" disabled={busy || !canApply} onClick={() => { void apply(); }}>
              {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {changes ? t('同步（{0} 处）', [changes]) : t('同步')}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
