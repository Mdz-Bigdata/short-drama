import { ChevronDown, ChevronRight, Clapperboard, ImageIcon, RefreshCcw, Save, Search, Video } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';

import { apiRequest } from '../../api/client';
import { ShotDeskPanel } from './ShotDeskPanel';
import { VideoPromptEditor } from './VideoPromptEditor';
import {
  durationWarning,
  settingsEqual,
  shotStatus,
  useSliderForDurations,
  vocabularyLabel,
  type CameraRecipe,
  type ShotFixPlan,
  type ShotVisualSettings,
  type ShotVisualWorkspace as Workspace,
  ADMISSION_LABELS,
  QUEUE_STATUS_LABELS,
  isGenerationQueue,
  type GenerationQueue,
  formatCost,
  formatCostByCurrency,
  isBatchAdmission,
  isUsageSummary,
  type BatchAdmission,
  type UsageSummary,
} from './shotVisual';
import { t } from '../../i18n';

const INTENSITIES: Array<[CameraRecipe['intensity'], string]> = [['strong', '强'], ['medium', '中'], ['soft', '弱']];
// The desk pulls in the whole 3D workspace; it loads when someone opens it, not with the stage.
const DirectorDesk = lazy(() => import('../directorDesk/DirectorDesk').then(module => ({ default: module.DirectorDesk })));

interface Props {
  taskId: string;
  videoModel: string;
  imageModel: string;
  onRerun?: () => void;
}

type DetailTab = 'script' | 'prompts' | 'media';


function Collapsible({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="shot-workspace__collapsible">
      <button type="button" className="shot-workspace__collapsible-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
        <span>{title}</span>
      </button>
      {open && <div className="shot-workspace__collapsible-body">{children}</div>}
    </section>
  );
}


function DurationSelector({ value, options, disabled, onChange }: {
  value: number;
  options: number[];
  disabled: boolean;
  onChange: (seconds: number) => void;
}) {
  const warning = durationWarning(value, options);
  const slider = useSliderForDurations(options);
  return (
    <div className="shot-workspace__field">
      <label htmlFor="shot-visual-duration">{t('时长')}</label>
      {slider ? (
        <div className="shot-workspace__duration-slider">
          <input
            id="shot-visual-duration"
            type="range"
            min={options[0]}
            max={options[options.length - 1]}
            step={1}
            value={Math.min(Math.max(value, options[0]), options[options.length - 1])}
            disabled={disabled}
            aria-label={t('时长选择')}
            aria-valuetext={`${value} 秒`}
            onChange={event => onChange(Number(event.target.value))}
          />
          <span className="shot-workspace__duration-value">{value} 秒</span>
        </div>
      ) : (
        <div className="shot-workspace__duration-chips" role="radiogroup" aria-label={t('时长选择')}>
          {options.map(seconds => (
            <button
              key={seconds}
              type="button"
              role="radio"
              aria-checked={seconds === value}
              className={seconds === value ? 'is-active' : ''}
              disabled={disabled}
              onClick={() => onChange(seconds)}
            >
              {seconds} 秒
            </button>
          ))}
        </div>
      )}
      {warning && <p className="shot-workspace__warning" role="alert">{warning}</p>}
    </div>
  );
}


export function ShotVisualWorkspace({ taskId, videoModel, imageModel, onRerun }: Props) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [error, setError] = useState('');
  // Notices belong to the shot they were produced for; switching shots hides them.
  const [notice, setNotice] = useState<{ shotId: number; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Unsaved edits per shot; a shot without an entry shows its persisted settings.
  const [drafts, setDrafts] = useState<Record<number, ShotVisualSettings>>({});
  const [query, setQuery] = useState('');
  const [listCollapsed, setListCollapsed] = useState(false);
  const [tab, setTab] = useState<DetailTab>('media');
  const [recipeCategory, setRecipeCategory] = useState('');
  const [recipeIntensity, setRecipeIntensity] = useState<CameraRecipe['intensity']>('medium');
  const [recipe, setRecipe] = useState<CameraRecipe | null>(null);
  const [composing, setComposing] = useState(false);
  // 这一镜生成翻车时，用自己的话报一句；后端归类、给修正方案，并记进项目台账。
  const [failureText, setFailureText] = useState('');
  const [fixPlan, setFixPlan] = useState<ShotFixPlan | null>(null);
  const [reporting, setReporting] = useState(false);
  // The shot whose scene the desk is open on; the desk itself is keyed by scene, as everywhere else.
  const [deskShot, setDeskShot] = useState<{ sceneId: string; shotId: number } | null>(null);
  const [deskToken, setDeskToken] = useState(0);
  // Stage 5 admits every shot together or none: the assessment, and what the project has spent so far.
  const [admission, setAdmission] = useState<BatchAdmission | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [confirming, setConfirming] = useState(false);
  // The generation queue of the running (or last) stage-5 run: what waits, what runs, what can still be withdrawn.
  const [queue, setQueue] = useState<GenerationQueue | null>(null);
  const [queueNotice, setQueueNotice] = useState('');

  const loadQueue = useCallback(async () => {
    try {
      const data = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/queue`);
      setQueue(isGenerationQueue(data) && data.items.length > 0 ? data : null);
    } catch {
      setQueue(null);
    }
  }, [taskId]);

  const cancelQueued = useCallback(async (key: string | null) => {
    setQueueNotice('');
    try {
      const path = key ? `/queue/${encodeURIComponent(key)}/cancel` : '/queue/cancel-queued';
      const data = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}${path}`, { method: 'POST', body: JSON.stringify({}) });
      setQueue(isGenerationQueue(data) ? data : null);
      setQueueNotice(key ? '已请求取消，队列在下次派发前生效。' : '已请求取消所有排队中的项；运行中的会跑完并保留结果。');
    } catch (err) {
      setQueueNotice(err instanceof Error ? err.message : '取消失败');
    }
  }, [taskId]);

  const loadAdmission = useCallback(async () => {
    try {
      const [assessed, spent] = await Promise.all([
        apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/shots/admission`, { method: 'POST', body: JSON.stringify({}) }),
        apiRequest<{ summary?: unknown }>(`/api/drama/${encodeURIComponent(taskId)}/usage?limit=1`),
      ]);
      setAdmission(isBatchAdmission(assessed) ? assessed : null);
      setUsage(isUsageSummary(spent?.summary) ? spent.summary : null);
    } catch {
      // The workspace is still usable without the assessment; stage 5 re-assesses when it starts.
      setAdmission(null);
    }
  }, [taskId]);

  // One shot to redo: it is marked stale, so the next stage-5 run regenerates it and reuses the rest.
  const regenerateShot = useCallback(async (shotId: number) => {
    setSaving(true);
    try {
      const data = await apiRequest<Workspace>(`/api/drama/${encodeURIComponent(taskId)}/shots/${shotId}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ reason: '' }),
      });
      setWorkspace(data);
      setNotice({ shotId, text: '已标记重做；重跑第 5 阶段时只重新生成本镜，其余镜头沿用已有片段。' });
      void loadAdmission();
    } catch (err) {
      setError(err instanceof Error ? err.message : '标记重做失败');
    } finally {
      setSaving(false);
    }
  }, [taskId, loadAdmission]);

  const confirmTiers = useCallback(async () => {
    if (!admission || admission.confirmations.length === 0) return;
    setConfirming(true);
    try {
      const assessed = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/shots/admission`, {
        method: 'POST',
        body: JSON.stringify({
          confirmed_request_durations: admission.confirmations.map(item => ({ scripted_seconds: item.scripted_seconds, requested_seconds: item.requested_seconds })),
          persist: true,
        }),
      });
      setAdmission(isBatchAdmission(assessed) ? assessed : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认时长档位失败');
    } finally {
      setConfirming(false);
    }
  }, [admission, taskId]);

  const load = useCallback(async () => {
    try {
      const data = await apiRequest<Workspace>(`/api/drama/${encodeURIComponent(taskId)}/shots/visual`);
      setWorkspace(data);
      setSelectedId(current => (current !== null && data.shots.some(shot => shot.shot_id === current)) ? current : (data.shots[0]?.shot_id ?? null));
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '镜头工作区加载失败');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    // Same pattern as the rest of the workbench: the initial fetch is scheduled
    // rather than started synchronously inside the effect body.
    const handle = window.setTimeout(() => { void load(); void loadAdmission(); void loadQueue(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load, loadAdmission, loadQueue]);

  const selected = useMemo(
    () => workspace?.shots.find(shot => shot.shot_id === selectedId) ?? null,
    [workspace, selectedId],
  );
  const draft = selected ? (drafts[selected.shot_id] ?? selected.settings) : null;

  const visibleShots = useMemo(() => {
    if (!workspace) return [];
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    if (!needle) return workspace.shots;
    return workspace.shots.filter(shot => `${shot.shot_id} ${shot.desc} ${shot.dialogue}`.toLocaleLowerCase('zh-CN').includes(needle));
  }, [workspace, query]);

  const dirty = Boolean(selected && draft && !settingsEqual(selected.settings, draft));
  const locked = Boolean(workspace?.running) || saving;

  const save = async () => {
    if (!selected || !draft || !workspace || !dirty || locked) return;
    setSaving(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(
        `/api/drama/${encodeURIComponent(taskId)}/shots/${selected.shot_id}/visual`,
        { method: 'PUT', body: JSON.stringify(draft) },
      );
      setWorkspace(data);
      setDrafts(current => {
        const next = { ...current };
        delete next[selected.shot_id];
        return next;
      });
      setNotice({ shotId: selected.shot_id, text: `镜头 ${selected.shot_id} 的运镜设置已保存，重跑第 5 阶段后生效。` });
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存运镜设置失败');
    } finally {
      setSaving(false);
    }
  };

  /** 保存人工改写的视频提示词；传 null 恢复自动编译。本镜已出的片会标记为待重做。 */
  const saveVideoPrompt = async (prompt: string | null) => {
    if (!selected || !workspace || workspace.running) return;
    setSavingPrompt(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(
        `/api/drama/${encodeURIComponent(taskId)}/shots/${selected.shot_id}/video-prompt`,
        { method: 'PUT', body: JSON.stringify({ prompt }) },
      );
      setWorkspace(data);
      setNotice({
        shotId: selected.shot_id,
        text: prompt === null
          ? `镜头 ${selected.shot_id} 已恢复自动编译的提示词，重新生成本镜后生效。`
          : `镜头 ${selected.shot_id} 的视频提示词已保存，重新生成本镜后生效。`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存视频提示词失败');
    } finally {
      setSavingPrompt(false);
    }
  };

  const update = (patch: Partial<ShotVisualSettings>) => {
    if (!selected || !draft) return;
    setDrafts(current => ({ ...current, [selected.shot_id]: { ...draft, ...patch } }));
  };

  /** Ask the backend for a category/intensity recipe filled with this shot's action and scene. */
  const composeRecipe = async () => {
    if (!selected || !recipeCategory || composing) return;
    setComposing(true);
    setError('');
    try {
      const composed = await apiRequest<CameraRecipe>(
        `/api/drama/${encodeURIComponent(taskId)}/shots/${selected.shot_id}/visual/recipe`,
        { method: 'POST', body: JSON.stringify({ category: recipeCategory, intensity: recipeIntensity }) },
      );
      setRecipe(composed);
    } catch (err) {
      setError(err instanceof Error ? err.message : '运镜配方生成失败');
    } finally {
      setComposing(false);
    }
  };

  /** Report how this shot came back, and get the fix for the next attempt. */
  const reportOutcome = async (result: 'failed' | 'success') => {
    if (!selected || reporting) return;
    if (result === 'failed' && !failureText.trim()) return;
    setReporting(true);
    setError('');
    try {
      const payload = await apiRequest<{ plan: ShotFixPlan | null; attempt: number }>(
        `/api/drama/${encodeURIComponent(taskId)}/shots/${selected.shot_id}/feedback`,
        {
          method: 'POST',
          body: JSON.stringify(
            result === 'failed'
              ? { result, text: failureText.trim() }
              : { result, applied_fix: fixPlan?.steps?.[0] || '' },
          ),
        },
      );
      setFixPlan(payload.plan);
      if (result === 'success') {
        setFailureText('');
        setNotice({ shotId: selected.shot_id, text: '已记为成功，生效的修正手段会沉淀为项目经验。' });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈提交失败');
    } finally {
      setReporting(false);
    }
  };

  const applyRecipe = () => {
    if (!recipe) return;
    update({ camera_motion: recipe.camera_motion, action: recipe.prompt_zh });
  };

  const assignSeeds = async () => {
    if (!workspace || locked) return;
    setSaving(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(`/api/drama/${encodeURIComponent(taskId)}/shots/seeds/assign`, { method: 'POST', body: JSON.stringify({}) });
      setWorkspace(data);
      setDrafts({});
      if (selected) setNotice({ shotId: selected.shot_id, text: '已按场景分配固定种子（同场相邻），重跑第 5 阶段后生效。' });
    } catch (err) {
      setError(err instanceof Error ? err.message : '分配种子失败');
    } finally {
      setSaving(false);
    }
  };

  const selectCandidate = async (url: string) => {
    if (!selected || saving) return;
    setSaving(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(
        `/api/drama/${encodeURIComponent(taskId)}/shots/${selected.shot_id}/visual/select`,
        { method: 'PUT', body: JSON.stringify({ video_url: url }) },
      );
      setWorkspace(data);
      setNotice({ shotId: selected.shot_id, text: `镜头 ${selected.shot_id} 已选用该版本。` });
    } catch (err) {
      setError(err instanceof Error ? err.message : '选用版本失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading && !workspace) {
    return <div className="stage-five-empty" role="status">{t('正在加载镜头工作区…')}</div>;
  }
  if (!workspace) {
    return <div className="stage-five-empty" role="status">{error || '镜头工作区不可用。'}</div>;
  }
  if (workspace.shots.length === 0) {
    return (
      <div className="stage-five-empty" role="status">
        {t('暂无分镜镜头。请先完成第 4 阶段分镜，再回到视觉阶段设置运镜。')}
      </div>
    );
  }

  const staleCount = workspace.shots.filter(shot => shot.stale).length;

  return (
    <div className={`shot-workspace${listCollapsed ? ' is-list-collapsed' : ''}`}>
      <aside className="shot-workspace__list" aria-label={t('分镜列表')}>
        <header className="shot-workspace__list-header">
          <button
            type="button"
            className="shot-workspace__list-toggle"
            aria-label={listCollapsed ? t('展开分镜列表') : t('折叠分镜列表')}
            onClick={() => setListCollapsed(value => !value)}
          >
            {listCollapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
          </button>
          {!listCollapsed && <strong>分镜 · {workspace.shots.length} 镜</strong>}
        </header>
        {!listCollapsed && (
          <>
            <label className="shot-workspace__search">
              <Search size={13} aria-hidden="true" />
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('搜索分镜…')} aria-label={t('搜索分镜')} />
            </label>
            <ul className="shot-workspace__shots" aria-label={t('分镜')}>
              {visibleShots.map(shot => {
                const status = shotStatus(shot);
                return (
                  <li key={shot.shot_id}>
                    <button
                      type="button"
                      className={`shot-workspace__shot${shot.shot_id === selectedId ? ' is-selected' : ''}`}
                      aria-pressed={shot.shot_id === selectedId}
                      aria-label={`镜头 ${shot.shot_id}`}
                      onClick={() => setSelectedId(shot.shot_id)}
                    >
                      <span className="shot-workspace__shot-index">{shot.shot_id}</span>
                      <span className="shot-workspace__shot-thumb">
                        {shot.image_url ? <img src={shot.image_url} alt="" /> : <ImageIcon size={16} aria-hidden="true" />}
                      </span>
                      <span className="shot-workspace__shot-body">
                        <span className="shot-workspace__shot-desc">{shot.desc || '分镜画面'}</span>
                        <span className="shot-workspace__shot-meta">
                          <em>{vocabularyLabel(workspace.shot_types, shot.settings.shot_type)}</em>
                          <em>{vocabularyLabel(workspace.camera_motions, shot.settings.camera_motion)}</em>
                          <em className="num">{shot.settings.duration_seconds} 秒</em>
                          <em className={`shot-workspace__status is-${status.key}`}>{status.label}</em>
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </aside>

      {selected && draft && (
        <section className="shot-workspace__detail" aria-label={`镜头 ${selected.shot_id} 详情`}>
          <header className="shot-workspace__detail-header">
            <div>
              <strong>镜头 {selected.shot_id}</strong>
              {selected.contract_fingerprint && <code>契约 {selected.contract_fingerprint.slice(0, 12)}</code>}
              {selected.settings_source === 'edited' && <small>{t('人工设定')}</small>}
            </div>
            <div className="shot-workspace__detail-actions">
              <button type="button" className="secondary-action" onClick={() => { void save(); }} disabled={!dirty || locked}>
                <Save size={14} aria-hidden="true" /> {saving ? t('保存中…') : t('保存运镜')}
              </button>
              <button type="button" className="secondary-action" onClick={() => { void assignSeeds(); }} disabled={locked}>
                {t('按场分配种子')}
              </button>
              {selected.video_url && (
                <button type="button" className="secondary-action" onClick={() => { void regenerateShot(selected.shot_id); }} disabled={locked || saving || selected.stale}>
                  {t('重做本镜')}
                </button>
              )}
              {onRerun && (
                <button type="button" className="primary-action" onClick={onRerun} disabled={Boolean(workspace.running)}>
                  <RefreshCcw size={14} aria-hidden="true" /> {t('重跑第 5 阶段')}
                </button>
              )}
            </div>
          </header>

          {admission && (
            <section className={`shot-workspace__admission is-${admission.decision}`} aria-label={t('批量视频准入')}>
              <header>
                <strong>{ADMISSION_LABELS[admission.decision]}</strong>
                <span>
                  生成 {admission.counts.generate} · 复用 {admission.counts.reuse} · 受阻 {admission.counts.blocked}
                  {admission.estimate.shots_to_generate > 0 && ` · 预估 ${formatCost(admission.estimate.cost, admission.estimate.currency, admission.estimate.priced)}（${admission.estimate.requested_seconds} 秒）`}
                  {usage && ` · 已花费 ${formatCostByCurrency(usage.cost_by_currency)}${usage.unpriced_calls ? `（${usage.unpriced_calls} 次调用未定价）` : ''}`}
                </span>
              </header>
              {admission.decision === 'blocked' && (
                <ul className="shot-workspace__admission-problems">
                  {admission.shots.filter(shot => shot.quote === 'blocked').map(shot => (
                    <li key={shot.shot_id}>
                      <strong>镜头 {shot.shot_id}</strong>
                      {shot.problems.filter(problem => problem.blocking).map(problem => <span key={problem.code}>{problem.message}</span>)}
                    </li>
                  ))}
                  {admission.counts.withheld > 0 && <li><strong>其余 {admission.counts.withheld} 镜</strong><span>{t('本可生成，整批一起暂不提交')}</span></li>}
                </ul>
              )}
              {admission.decision === 'confirmation_required' && (
                <div className="shot-workspace__admission-confirm">
                  <ul>
                    {admission.confirmations.map(item => (
                      <li key={`${item.scripted_seconds}-${item.requested_seconds}`}>
                        剧本 {item.scripted_seconds} 秒 → 请求 {item.requested_seconds} 秒 × {item.shot_count} 镜（镜头 {item.shot_ids.join('、')}）
                        · {formatCost(item.cost, item.currency, item.priced)}
                      </li>
                    ))}
                  </ul>
                  <p>{t('视频不会被裁剪：按请求档位生成，成片按脚本节奏剪接。')}</p>
                  <button type="button" className="secondary-action" disabled={confirming || locked} onClick={() => { void confirmTiers(); }}>
                    {confirming ? t('确认中…') : t('确认这些档位')}
                  </button>
                </div>
              )}
            </section>
          )}
          {queue && (
            <section className="shot-workspace__queue" aria-label={t('生成队列')}>
              <header>
                <strong>生成队列{queue.running ? '（运行中）' : '（上一轮）'}</strong>
                <span>
                  {(['queued', 'running', 'done', 'failed', 'cancelled', 'skipped'] as const)
                    .filter(status => (queue.counts[status] ?? 0) > 0)
                    .map(status => `${QUEUE_STATUS_LABELS[status]} ${queue.counts[status]}`)
                    .join(' · ')}
                  {Object.entries(queue.buckets).length > 0 && ` · 并发 ${Object.entries(queue.buckets).map(([bucket, info]) => `${bucket} ${info.running}/${info.limit}`).join('，')}`}
                </span>
                {queue.running && (queue.counts.queued ?? 0) > 0 && (
                  <button type="button" className="secondary-action" onClick={() => { void cancelQueued(null); }}>{t('取消全部排队')}</button>
                )}
                <button type="button" className="secondary-action" onClick={() => { void loadQueue(); }}>{t('刷新')}</button>
              </header>
              {queueNotice && <p className="shot-workspace__hint" role="status">{queueNotice}</p>}
              <ul className="shot-workspace__queue-items">
                {queue.items.map(item => (
                  <li key={item.key} className={`is-${item.status}`}>
                    <span className="shot-workspace__queue-status">{QUEUE_STATUS_LABELS[item.status]}</span>
                    <strong>{item.label}</strong>
                    <small>{item.bucket}{item.depends_on.length ? ` · 依赖 ${item.depends_on.join('、')}` : ''}</small>
                    {item.error && <em>{item.error}</em>}
                    {item.reason && !item.error && <em>{item.reason}</em>}
                    {queue.running && item.status === 'queued' && !(queue.withdraw ?? []).includes(item.key) && (
                      <button type="button" onClick={() => { void cancelQueued(item.key); }} aria-label={`取消 ${item.label}`}>{t('取消')}</button>
                    )}
                    {(queue.withdraw ?? []).includes(item.key) && item.status === 'queued' && <em>{t('取消待生效')}</em>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {workspace.running && <p className="shot-workspace__hint" role="status">{t('任务正在执行阶段，暂不能修改运镜。')}</p>}
          {(selected.stale || staleCount > 0) && (
            <p className="shot-workspace__hint is-stale" role="status">
              {selected.stale ? selected.stale_reason || '内容已更新，提示词可能不符' : `${staleCount} 镜已修改运镜，重跑第 5 阶段后生效。`}
            </p>
          )}
          {dirty && <p className="shot-workspace__hint" role="status">{t('运镜设置已修改，保存后重跑第 5 阶段生效。')}</p>}
          {selected.derived_notes.map(note => <p key={note} className="shot-workspace__hint">{note}</p>)}
          {notice && notice.shotId === selected.shot_id && <p className="shot-workspace__hint is-success" role="status">{notice.text}</p>}
          {error && <p className="shot-workspace__warning" role="alert">{error}</p>}

          <div className="shot-workspace__tabs" role="tablist" aria-label={t('镜头详情')}>
            {([['script', '脚本 / 对话'], ['prompts', '提示词'], ['media', '分镜 / 视频']] as Array<[DetailTab, string]>).map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'is-active' : ''} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'script' && (
            <div className="shot-workspace__panel" role="tabpanel">
              <h4>{t('画面描述')}</h4>
              <p>{selected.desc || '（暂无画面描述）'}</p>
              <h4>{t('对话')}</h4>
              <p>{selected.dialogue || '（暂无对话）'}</p>
              <h4>{t('声音')}</h4>
              <p>{selected.sound || '（暂无声音说明）'}</p>
            </div>
          )}

          {tab === 'prompts' && (
            <div className="shot-workspace__panel" role="tabpanel">
              <h4><Video size={14} aria-hidden="true" /> {t('视频提示词')} <small>{videoModel}</small></h4>
              <VideoPromptEditor
                key={`${selected.shot_id}:${selected.video_prompt}`}
                shotId={selected.shot_id}
                prompt={selected.video_prompt}
                edited={Boolean(selected.video_prompt_edited)}
                mentionKinds={selected.mention_kinds ?? {}}
                referenceNumbers={selected.reference_numbers ?? {}}
                locked={Boolean(workspace.running)}
                saving={savingPrompt}
                onSave={saveVideoPrompt}
              />
              <h4><ImageIcon size={14} aria-hidden="true" /> {t('分镜图提示词')} <small>{imageModel}</small></h4>
              <pre>{selected.image_prompt || '待生成'}</pre>
            </div>
          )}

          {tab === 'media' && (
            <div className="shot-workspace__panel shot-workspace__media" role="tabpanel">
              <ShotDeskPanel
                taskId={taskId} sceneId={selected.scene_id} shotId={selected.shot_id} reloadToken={deskToken}
                onOpenDesk={() => setDeskShot({ sceneId: selected.scene_id, shotId: selected.shot_id })}
              />
              <figure>
                <figcaption><ImageIcon size={14} aria-hidden="true" /> {t('分镜图')}</figcaption>
                {selected.image_url ? <img src={selected.image_url} alt={`镜头 ${selected.shot_id} 分镜图`} /> : <p className="shot-workspace__hint">{t('尚未生成')}</p>}
              </figure>
              <figure>
                <figcaption><Video size={14} aria-hidden="true" /> {t('视频')}</figcaption>
                {selected.video_url
                  ? <video src={selected.video_url} controls loop preload="metadata" aria-label={`镜头 ${selected.shot_id} 视频`} />
                  : <p className="shot-workspace__hint">{t('尚未生成')}</p>}
                {selected.route && (
                  <small className="shot-workspace__route">自动路由：{selected.route.mode} · {selected.route.provider_family}{selected.route.reasons?.[0] ? ` · ${selected.route.reasons[0]}` : ''}</small>
                )}
                {(selected.candidate_urls?.length ?? 0) > 1 && (
                  <ul className="shot-workspace__candidates" aria-label={t('候选版本')}>
                    {selected.candidate_urls!.map((url, index) => (
                      <li key={url}>
                        <span>版本 {index + 1}</span>
                        <button type="button" className="secondary-action" disabled={saving} onClick={() => { void selectCandidate(url); }}>{t('选用此版')}</button>
                      </li>
                    ))}
                  </ul>
                )}
              </figure>
            </div>
          )}

          <Collapsible title={t('运镜 / 音效 / 对话')} defaultOpen>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-motion">{t('镜头运动')}</label>
              <select id="shot-visual-motion" value={draft.camera_motion} disabled={locked} onChange={event => update({ camera_motion: event.target.value })}>
                {workspace.camera_motions.map(entry => <option key={entry.value} value={entry.value}>{entry.label}（{entry.value}）</option>)}
              </select>
              <small>一镜只用一种运镜，按 {workspace.provider_family || '所选模型'} 官方运镜写法写入视频提示词。</small>
            </div>
            {(workspace.recipe_categories?.length ?? 0) > 0 && (
              <div className="shot-workspace__field shot-workspace__recipe">
                <label htmlFor="shot-visual-recipe">{t('运镜灵感')}</label>
                <div className="shot-workspace__recipe-controls">
                  <select id="shot-visual-recipe" value={recipeCategory} disabled={locked} onChange={event => setRecipeCategory(event.target.value)}>
                    <option value="">{t('选择叙事类别…')}</option>
                    {workspace.recipe_categories!.map(entry => <option key={entry.value} value={entry.value}>{entry.label} · {entry.purpose}</option>)}
                  </select>
                  <div className="shot-workspace__duration-chips" role="radiogroup" aria-label={t('情绪强度')}>
                    {INTENSITIES.map(([key, label]) => (
                      <button key={key} type="button" role="radio" aria-checked={recipeIntensity === key} className={recipeIntensity === key ? 'is-active' : ''} disabled={locked} onClick={() => setRecipeIntensity(key)}>{label}</button>
                    ))}
                  </div>
                  <button type="button" className="secondary-action" disabled={!recipeCategory || locked || composing} onClick={() => { void composeRecipe(); }}>
                    {composing ? t('生成中…') : t('生成配方')}
                  </button>
                </div>
                {recipe && (
                  <div className="shot-workspace__recipe-result">
                    <p><strong>{recipe.category_label} · {recipe.camera_motion_label} · {recipe.angle_label} · {recipe.rhythm_label}</strong></p>
                    <p>{recipe.prompt_zh}</p>
                    <p className="shot-workspace__hint">EN: {recipe.prompt_en}</p>
                    <p className="shot-workspace__hint">反向: {recipe.negative}</p>
                    <button type="button" className="secondary-action" disabled={locked} onClick={applyRecipe}>{t('套用到本镜')}</button>
                  </div>
                )}
                <small>{t('画风与质感锁死，相邻镜只换运动、角度、节奏或环境之一，避免撞镜。')}</small>
              </div>
            )}
            <div className="shot-workspace__field shot-workspace__feedback">
              <label htmlFor="shot-visual-feedback">{t('这一镜翻车了？')}</label>
              <textarea
                id="shot-visual-feedback"
                rows={2}
                value={failureText}
                placeholder={t('用自己的话写：脸崩了 / 手是六根手指 / 特效糊住了脸 / 位置跳了…')}
                onChange={event => setFailureText(event.target.value)}
              />
              <div className="shot-workspace__recipe-controls">
                <button
                  type="button"
                  className="secondary-action"
                  disabled={reporting || !failureText.trim()}
                  onClick={() => { void reportOutcome('failed'); }}
                >
                  {reporting ? t('提交中…') : t('报告问题')}
                </button>
                <button
                  type="button"
                  className="secondary-action"
                  disabled={reporting}
                  onClick={() => { void reportOutcome('success'); }}
                >
                  {t('这条可用')}
                </button>
              </div>
              {fixPlan && (
                <div className="shot-workspace__recipe-result">
                  <p><strong>{fixPlan.category_name}</strong>（第 {fixPlan.attempt} 次）：{fixPlan.diagnosis}</p>
                  <ol>
                    {fixPlan.steps.map(step => <li key={step}>{step}</li>)}
                  </ol>
                  {fixPlan.negatives.length > 0 && (
                    <p className="shot-workspace__hint">建议追加负面词：{fixPlan.negatives.join('、')}</p>
                  )}
                  {fixPlan.give_up && <p className="shot-workspace__hint">{t('已到模型能力边界：考虑换等价表达或换模型。')}</p>}
                </div>
              )}
              <small>{t('同一类问题在同一模型上出现两次，后续镜头会自动按它预防性加固。')}</small>
            </div>
            <DurationSelector value={draft.duration_seconds} options={workspace.duration_options} disabled={locked} onChange={seconds => update({ duration_seconds: seconds })} />
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-action">{t('动作演变')}</label>
              <textarea id="shot-visual-action" value={draft.action} disabled={locked} rows={3} placeholder={t('描述这一镜的动作演变：从分镜图开始如何运动…')} onChange={event => update({ action: event.target.value })} />
            </div>
            <div className="shot-workspace__field shot-workspace__seed-row">
              <label htmlFor="shot-visual-seed">{t('种子')}</label>
              <input id="shot-visual-seed" type="number" min={0} max={2147483647} value={draft.seed ?? ''} disabled={locked} placeholder={t('留空则随机')}
                onChange={event => update({ seed: event.target.value === '' ? null : Number(event.target.value) })} />
              <label htmlFor="shot-visual-candidates">{t('生成版本数')}</label>
              <select id="shot-visual-candidates" value={draft.candidates ?? 1} disabled={locked} onChange={event => update({ candidates: Number(event.target.value) })}>
                {[1, 2, 3, 4].map(count => <option key={count} value={count}>{count} 次择优</option>)}
              </select>
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-ambiance-audio">{t('环境音效')}</label>
              <input id="shot-visual-ambiance-audio" value={draft.ambiance_audio} disabled={locked} placeholder={t('环境音效描述...')} onChange={event => update({ ambiance_audio: event.target.value })} />
            </div>
            <div className="shot-workspace__field">
              <span className="shot-workspace__label">{t('对话')}</span>
              <p className="shot-workspace__readonly">{selected.dialogue || '（暂无对话）'}</p>
            </div>
          </Collapsible>

          <Collapsible title={t('composition · 构图')}>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-shot-type">{t('镜头')}</label>
              <select id="shot-visual-shot-type" value={draft.shot_type} disabled={locked} onChange={event => update({ shot_type: event.target.value })}>
                {workspace.shot_types.map(entry => <option key={entry.value} value={entry.value}>{entry.label}（{entry.value}）</option>)}
              </select>
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-lighting">{t('光线')}</label>
              <input id="shot-visual-lighting" value={draft.lighting} disabled={locked} placeholder={t('光线描述...')} onChange={event => update({ lighting: event.target.value })} />
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-ambiance">{t('氛围')}</label>
              <input id="shot-visual-ambiance" value={draft.ambiance} disabled={locked} placeholder={t('氛围描述...')} onChange={event => update({ ambiance: event.target.value })} />
            </div>
          </Collapsible>

          <footer className="shot-workspace__footer">
            <Clapperboard size={13} aria-hidden="true" />
            <span>视频模型 {workspace.video_model || videoModel} · 可用时长 {workspace.duration_options[0]}–{workspace.duration_options[workspace.duration_options.length - 1]} 秒 · 修改只影响本镜，流程仍按 8 个 Agent 顺序推进。</span>
          </footer>
        </section>
      )}
      {deskShot && (
        <Suspense fallback={null}>
          <DirectorDesk
            key={`desk-${deskShot.sceneId}`}
            taskId={taskId}
            sceneId={deskShot.sceneId}
            initialShotId={deskShot.shotId}
            onClose={() => {
              setDeskShot(null);
              // What the desk applied lands on the shot itself, so both sides are read again.
              setDeskToken(value => value + 1);
              void load();
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
