import { Activity, ChevronDown, ChevronRight, Clapperboard, Film, ImageIcon, RefreshCcw, Save, Video, X } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { apiRequest } from '../../api/client';
import { PilotShotCard } from './PilotShotCard';
import { ShotDeskPanel } from './ShotDeskPanel';
import { VideoPromptEditor } from './VideoPromptEditor';
import {
  describeShots,
  durationWarning,
  groupBlockedShots,
  settingsEqual,
  shotKey,
  shotPath,
  shotStatus,
  useSliderForDurations,
  vocabularyLabel,
  type CameraRecipe,
  type ShotFixPlan,
  type ShotVideoFailure,
  type ShotVisualRecord,
  type ShotVisualSettings,
  type ShotVisualWorkspace as Workspace,
  type EpisodeMeta,
  episodeNumberOf,
  episodeSummaries,
  formatClock,
  ADMISSION_LABELS,
  QUEUE_STATUS_LABELS,
  isGenerationQueue,
  splitQueueItems,
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

/** 本看板最近一次没出片：分类、供应商原话、下一步，以及发出去的分镜画面，好看出是哪张图被拒。 */
function ShotFailureCard({ failure }: { failure: ShotVideoFailure }) {
  const panels = failure.panels ?? [];
  return (
    <section className="shot-workspace__failure" role="alert" aria-label={t('出片失败')}>
      <p className="shot-workspace__failure-head">
        <strong>{failure.kind === 'input_image_sensitive' ? t('输入图被判敏感') : t('供应商未出片')}</strong>
        {failure.code && <code>{failure.code}</code>}
        {failure.scene_id && <span>{failure.scene_id}</span>}
      </p>
      <p className="shot-workspace__failure-message">{failure.message}</p>
      {failure.hint && <p className="shot-workspace__failure-hint">{failure.hint}</p>}
      {panels.length > 0 && (
        <ul className="shot-workspace__failure-panels" aria-label={t('发出去的分镜画面')}>
          {panels.map((url, index) => (
            <li key={url}>
              <a href={url} target="_blank" rel="noreferrer" title={t('查看大图')}>
                <img src={url} alt={t('第 {0} 格分镜', [String(index + 1)])} />
                <span className="num">{index + 1}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface Props {
  /** 各集的标题与成片状态；进度从镜头算。 */
  episodes?: EpisodeMeta[];
  taskId: string;
  videoModel: string;
  imageModel: string;
  onRerun?: () => void;
  onVideoModelChange?: (model: string) => void;
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


const PILOT_POLL_MS = 4000;

export function ShotVisualWorkspace({ taskId, videoModel, imageModel, onRerun, onVideoModelChange, episodes: episodeMeta = [] }: Props) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [error, setError] = useState('');
  // Notices belong to the shot they were produced for; switching shots hides them.
  // Shots are keyed by scene and number (shotKey): every scene numbers its shots from 1.
  const [notice, setNotice] = useState<{ shotKey: string; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  // Unsaved edits per shot; a shot without an entry shows its persisted settings.
  const [drafts, setDrafts] = useState<Record<string, ShotVisualSettings>>({});
  const [listCollapsed, setListCollapsed] = useState(false);
  // The episode whose scenes and shots the rail and the strip show; 0 follows the selected shot.
  const [episodeFilter, setEpisodeFilter] = useState(0);
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
  const [batchAsked, setBatchAsked] = useState(false);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [confirming, setConfirming] = useState(false);
  // The generation queue of the running (or last) stage-5 run: what waits, what runs, what can still be withdrawn.
  const [queue, setQueue] = useState<GenerationQueue | null>(null);
  const [queueNotice, setQueueNotice] = useState('');
  // The queue lives in a drawer opened from the status chip, so the shot panel stays about the shot.
  const [queueOpen, setQueueOpen] = useState(false);
  // Finished queue items are folded away so what is still waiting or running stays in view.
  const [showSettled, setShowSettled] = useState(false);

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

  // One shot to redo: its clip (the whole board clip) is marked stale, so the next stage-5 run regenerates it and reuses the rest.
  const regenerateShot = useCallback(async (shot: ShotVisualRecord) => {
    setSaving(true);
    try {
      const data = await apiRequest<Workspace>(shotPath(taskId, shot, 'regenerate'), {
        method: 'POST',
        body: JSON.stringify({ reason: '' }),
      });
      setWorkspace(data);
      setNotice({ shotKey: shotKey(shot), text: '已标记重做；重跑第 5 阶段时只重新生成本镜所在的片段，其余片段沿用。' });
      void loadAdmission();
    } catch (err) {
      setError(err instanceof Error ? err.message : '标记重做失败');
    } finally {
      setSaving(false);
    }
  }, [taskId, loadAdmission]);

  // 项目留着一个模型配置中心没启用的视频模型时，一键换成启用的那个(后端只收启用的型号)。
  // One clip before the batch. A redo reports what was wrong and makes the same clip again.
  const startPilot = useCallback(async (options: { shot_uid?: number; redo?: boolean; problems?: string[] } = {}) => {
    setSaving(true);
    try {
      const data = await apiRequest<Workspace>(`/api/drama/${encodeURIComponent(taskId)}/shots/pilot`, {
        method: 'POST', body: JSON.stringify(options),
      });
      setWorkspace(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '试拍没有启动');
    } finally {
      setSaving(false);
    }
  }, [taskId]);

  const switchVideoModel = useCallback(async (model: string) => {
    setSaving(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(`/api/drama/${encodeURIComponent(taskId)}/video-model`, {
        method: 'PUT',
        body: JSON.stringify({ video_model: model }),
      });
      setWorkspace(data);
      onVideoModelChange?.(model);
      void loadAdmission();
    } catch (err) {
      setError(err instanceof Error ? err.message : '更换视频模型失败');
    } finally {
      setSaving(false);
    }
  }, [taskId, loadAdmission, onVideoModelChange]);

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
      setSelectedKey(current => (current !== null && data.shots.some(shot => shotKey(shot) === current)) ? current : (data.shots[0] ? shotKey(data.shots[0]) : null));
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

  // The clip is made in the background: keep looking until it is out.
  const pilotState = workspace?.pilot?.state;
  const generating = Boolean(workspace?.running) || batchAsked || pilotState === 'requested' || pilotState === 'running';
  useEffect(() => {
    if (!generating) return undefined;
    const timer = window.setInterval(() => { void load(); }, PILOT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [generating, load]);
  // What is left to generate changed: the reused clip is no longer quoted.
  const wasGenerating = useRef(false);
  useEffect(() => {
    const finished = wasGenerating.current && !generating;
    wasGenerating.current = generating;
    if (!finished) return undefined;
    const handle = window.setTimeout(() => { void loadAdmission(); }, 0);
    return () => window.clearTimeout(handle);
  }, [generating, loadAdmission]);
  // The batch is started through the chat, so it may not show as running on the very next look.
  useEffect(() => {
    if (!batchAsked) return undefined;
    const timer = window.setTimeout(() => setBatchAsked(false), PILOT_POLL_MS * 5);
    return () => window.clearTimeout(timer);
  }, [batchAsked]);

  const selected = useMemo(
    () => workspace?.shots.find(shot => shotKey(shot) === selectedKey) ?? null,
    [workspace, selectedKey],
  );
  const draft = selected ? (drafts[shotKey(selected)] ?? selected.settings) : null;


  const dirty = Boolean(selected && draft && !settingsEqual(selected.settings, draft));
  const locked = Boolean(workspace?.running) || saving;

  const save = async () => {
    if (!selected || !draft || !workspace || !dirty || locked) return;
    setSaving(true);
    setError('');
    try {
      const data = await apiRequest<Workspace>(
        shotPath(taskId, selected, 'visual'),
        { method: 'PUT', body: JSON.stringify(draft) },
      );
      setWorkspace(data);
      setDrafts(current => {
        const next = { ...current };
        delete next[shotKey(selected)];
        return next;
      });
      setNotice({ shotKey: shotKey(selected), text: `镜头 ${selected.shot_id} 的运镜设置已保存，重跑第 5 阶段后生效。` });
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
        shotPath(taskId, selected, 'video-prompt'),
        { method: 'PUT', body: JSON.stringify({ prompt }) },
      );
      setWorkspace(data);
      setNotice({
        shotKey: shotKey(selected),
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
    setDrafts(current => ({ ...current, [shotKey(selected)]: { ...draft, ...patch } }));
  };

  /** Ask the backend for a category/intensity recipe filled with this shot's action and scene. */
  const composeRecipe = async () => {
    if (!selected || !recipeCategory || composing) return;
    setComposing(true);
    setError('');
    try {
      const composed = await apiRequest<CameraRecipe>(
        shotPath(taskId, selected, 'visual/recipe'),
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
        setNotice({ shotKey: shotKey(selected), text: '已记为成功，生效的修正手段会沉淀为项目经验。' });
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
      if (selected) setNotice({ shotKey: shotKey(selected), text: '已按场景分配固定种子（同场相邻），重跑第 5 阶段后生效。' });
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
        shotPath(taskId, selected, 'visual/select'),
        { method: 'PUT', body: JSON.stringify({ video_url: url }) },
      );
      setWorkspace(data);
      setNotice({ shotKey: shotKey(selected), text: `镜头 ${selected.shot_id} 已选用该版本。` });
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
  const generated = workspace.shots.filter(shot => shot.video_url && !shot.stale).length;
  const episodeCards = episodeSummaries(workspace.shots, episodeMeta);
  const episodes = episodeCards.map(card => card.number);
  const episodesDone = episodeCards.filter(card => card.filmDone || (card.shotCount > 0 && card.generated === card.shotCount)).length;
  const currentEpisode = episodeFilter || (selected ? episodeNumberOf(selected.scene_id) : episodes[0] ?? 0);
  const inEpisode = (shot: ShotVisualRecord) => !currentEpisode || episodeNumberOf(shot.scene_id) === currentEpisode;
  // The film strip under the scene chips holds the current episode's shots.
  const railShots = workspace.shots.filter(inEpisode);
  const episodeShots = workspace.shots.filter(inEpisode);
  const episodeGenerated = episodeShots.filter(shot => shot.video_url && !shot.stale).length;
  // The strip across the top: one chip per scene, coloured by how far its shots have got.
  const scenes = workspace.shots.filter(inEpisode).reduce<Array<{ id: string; status: 'ready' | 'partial' | 'failed' | 'pending'; firstKey: string }>>((list, shot) => {
    const status = shotStatus(shot).key;
    const entry = list.find(item => item.id === shot.scene_id);
    const mark = status === 'ready' ? 'ready' : status === 'refused' || status === 'failed' ? 'failed' : 'pending';
    if (!entry) {
      list.push({ id: shot.scene_id, status: mark, firstKey: shotKey(shot) });
    } else if (entry.status !== mark) {
      entry.status = entry.status === 'failed' || mark === 'failed' ? 'failed' : 'partial';
    }
    return list;
  }, []);
  const shotTitle = (desc: string) => desc.split(/[，。；！？,.;!?\n]/)[0].slice(0, 18) || '分镜画面';

  return (
    <div className={`shot-workspace${listCollapsed ? ' is-list-collapsed' : ''}`}>
      <header className="shot-workspace__topbar">
        <div className="shot-workspace__topbar-title">
          <h3>{t('运镜')}</h3>
          <span>{currentEpisode ? `第 ${currentEpisode} 集` : ''}{episodeCards.find(card => card.number === currentEpisode)?.title ? ` · ${episodeCards.find(card => card.number === currentEpisode)!.title}` : ''}</span>
          <em className={episodeGenerated === episodeShots.length ? 'is-done' : ''}>{episodeGenerated}/{episodeShots.length} {t('个运镜已生成')}</em>
        </div>
        {onRerun && !workspace.pilot && workspace.shots.some(shot => !shot.video_url || shot.stale) && (
          <button
            type="button" className="secondary-action shot-workspace__pilot-start" disabled={locked}
            title={t('整批生成之前，先只拍人和动作最少的一段看看效果。拍好的这段整批时直接复用。')}
            onClick={() => { void startPilot(); }}
          >
            {t('先试拍一段')}
          </button>
        )}
        {onRerun && (
          <button type="button" className="primary-action shot-workspace__rerun" onClick={onRerun} disabled={Boolean(workspace.running)}>
            <RefreshCcw size={14} aria-hidden="true" /> {t('重跑第 5 阶段')}（{workspace.shots.length}）
          </button>
        )}
        <nav className="shot-workspace__scenes" aria-label={t('场次')}>
          {scenes.map(scene => (
            <button
              key={scene.id}
              type="button"
              className={`is-${scene.status}${selected?.scene_id === scene.id ? ' is-current' : ''}`}
              onClick={() => { setEpisodeFilter(0); setSelectedKey(scene.firstKey); }}
            >
              {scene.id}<i aria-hidden="true" />
            </button>
          ))}
        </nav>
        <ul className="shot-workspace__filmstrip" aria-label={t('分镜')}>
          {railShots.map((shot, index) => {
            const status = shotStatus(shot);
            // Shot numbers restart in every scene, so the list says which scene a run of numbers belongs to.
            const sceneStart = Boolean(shot.scene_id) && railShots[index - 1]?.scene_id !== shot.scene_id;
            return (
              <li key={shotKey(shot)} className={sceneStart ? 'is-scene-start' : undefined}>
                {sceneStart && <span className="shot-workspace__scene-label" aria-hidden="true">{shot.scene_id}</span>}
                <button
                  type="button"
                  className={`shot-workspace__shot${shotKey(shot) === selectedKey ? ' is-selected' : ''}`}
                  aria-pressed={shotKey(shot) === selectedKey}
                  aria-label={`${shot.scene_id ? `${shot.scene_id} ` : ''}镜头 ${shot.shot_id}`}
                  title={shot.scene_id || undefined}
                  onClick={() => setSelectedKey(shotKey(shot))}
                >
                  <span className="shot-workspace__shot-index">{shot.shot_id}</span>
                  <span className="shot-workspace__shot-thumb">
                    {shot.image_url ? <img src={shot.image_url} alt="" loading="lazy" decoding="async" /> : <ImageIcon size={16} aria-hidden="true" />}
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
      </header>
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
          {!listCollapsed && <strong>{t('分集列表')} <small>{episodeCards.length} {t('集')}</small></strong>}
        </header>
        {!listCollapsed && (
          <>
            <ol className="shot-workspace__episodes" aria-label={t('分集列表')}>
              {episodeCards.map(card => {
                const percent = card.shotCount ? Math.round((card.generated / card.shotCount) * 100) : 0;
                const done = card.filmDone || (card.shotCount > 0 && card.generated === card.shotCount);
                return (
                  <li key={card.number}>
                    <button
                      type="button"
                      className={card.number === currentEpisode ? 'is-current' : ''}
                      aria-pressed={card.number === currentEpisode}
                      onClick={() => { setEpisodeFilter(card.number); setSelectedKey(card.firstKey); }}
                    >
                      <span className="shot-workspace__episode-thumb">
                        {card.thumbnail ? <img src={card.thumbnail} alt="" loading="lazy" decoding="async" /> : <ImageIcon size={16} aria-hidden="true" />}
                        <b>第{card.number}集</b>
                      </span>
                      <span className="shot-workspace__episode-body">
                        <span className="shot-workspace__episode-head">
                          <strong>{card.title || `第 ${card.number} 集`}</strong>
                          <em className="num">{formatClock(card.seconds)}</em>
                        </span>
                        <span className={`shot-workspace__episode-state${done ? ' is-done' : ''}`}>
                          <i aria-hidden="true" />{done ? t('制作完成') : t('制作中')} · {card.generated}/{card.shotCount} {t('运镜')}
                        </span>
                        <span className="shot-workspace__episode-progress">
                          <small>{t('制作进度')}</small>
                          <em className="num">{percent}%</em>
                          <span><span style={{ width: `${percent}%` }} /></span>
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </aside>

      {selected && draft && (
        <section className="shot-workspace__detail" aria-label={`${selected.scene_id ? `${selected.scene_id} ` : ''}镜头 ${selected.shot_id} 详情`}>
          <header className="shot-workspace__detail-header">
            <div className="shot-workspace__detail-title">
              {selected.scene_id && <span className="shot-workspace__scene-chip">{selected.scene_id}</span>}
              <strong>镜头 {selected.shot_id}</strong>
              <span className="shot-workspace__shot-title">{shotTitle(selected.desc)}</span>
              <span className="shot-workspace__shot-brief">{selected.scene_id} · {draft.duration_seconds} 秒运镜</span>
              {selected.contract_fingerprint && <code>契约 {selected.contract_fingerprint.slice(0, 12)}</code>}
              {selected.settings_source === 'edited' && <small>{t('人工设定')}</small>}
              {queue && (
                <button
                  type="button"
                  className={`shot-workspace__queue-chip${queue.running ? ' is-running' : ''}`}
                  aria-expanded={queueOpen}
                  aria-controls="shot-queue-drawer"
                  onClick={() => setQueueOpen(value => !value)}
                >
                  <Activity size={12} aria-hidden="true" />
                  {t('生成队列')}
                  {!queue.running && ` · ${t('上一轮')}`}
                  {(['running', 'queued', 'failed'] as const)
                    .filter(status => (queue.counts[status] ?? 0) > 0)
                    .map(status => <em key={status} className={`is-${status}`}>{QUEUE_STATUS_LABELS[status]} {queue.counts[status]}</em>)}
                </button>
              )}
            </div>
            <div className="shot-workspace__detail-actions">
              <button type="button" className="secondary-action" onClick={() => { void save(); }} disabled={!dirty || locked}>
                <Save size={14} aria-hidden="true" /> {saving ? t('保存中…') : t('保存运镜')}
              </button>
              <button type="button" className="secondary-action" onClick={() => { void assignSeeds(); }} disabled={locked}>
                {t('按场分配种子')}
              </button>
              {!workspace.pilot && !selected.video_url && (
                <button type="button" className="secondary-action" disabled={locked} onClick={() => { void startPilot({ shot_uid: selected.shot_uid }); }}>
                  {t('用这一镜试拍')}
                </button>
              )}
              {selected.video_url && (
                <button type="button" className="secondary-action" onClick={() => { void regenerateShot(selected); }} disabled={locked || saving || selected.stale}>
                  {t('重做本镜')}
                </button>
              )}
            </div>
          </header>

          {workspace.video_model_issue && (
            <section className="shot-workspace__model-issue" role="alert" aria-label={t('视频模型不可用')}>
              <p>{workspace.video_model_issue}</p>
              {(workspace.enabled_video_models ?? []).filter(model => model !== workspace.video_model).map(model => (
                <button key={model} type="button" className="secondary-action" disabled={locked} onClick={() => { void switchVideoModel(model); }}>
                  {t('改用')} {model}
                </button>
              ))}
            </section>
          )}

          {workspace.video_model_note && <p className="shot-workspace__hint" role="status">{workspace.video_model_note}</p>}

          {workspace.pilot && !(workspace.pilot.state === 'ready' && (workspace.running || batchAsked)) && (
            <PilotShotCard
              // A new clip starts with nothing ticked: the old ticks were about the old clip.
              key={workspace.pilot.video_url || workspace.pilot.state}
              pilot={workspace.pilot}
              locked={locked}
              onPass={() => { setBatchAsked(true); onRerun?.(); }}
              onRedo={problems => { void startPilot({ redo: true, problems }); }}
              onRetry={() => { void startPilot({ redo: true }); }}
            />
          )}

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
                  {groupBlockedShots(admission).map(group => (
                    <li key={group.message}>
                      <span>{group.message}</span>
                      <strong>{describeShots(group.shots, admission.shots.length)}</strong>
                    </li>
                  ))}
                  {admission.counts.withheld > 0 && <li><span>{t('本可生成，整批一起暂不提交')}</span><strong>其余 {admission.counts.withheld} 镜</strong></li>}
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
          <div className="shot-workspace__notes">
            {workspace.running && <p className="shot-workspace__hint" role="status">{t('任务正在执行阶段，暂不能修改运镜。')}</p>}
            {(selected.stale || staleCount > 0) && (
              <p className="shot-workspace__hint is-stale" role="status">
                {selected.stale ? selected.stale_reason || '内容已更新，提示词可能不符' : `${staleCount} 镜已修改运镜，重跑第 5 阶段后生效。`}
              </p>
            )}
            {dirty && <p className="shot-workspace__hint" role="status">{t('运镜设置已修改，保存后重跑第 5 阶段生效。')}</p>}
            {selected.failure && <ShotFailureCard failure={selected.failure} />}
            {selected.derived_notes.map(note => <p key={note} className="shot-workspace__hint">{note}</p>)}
            {notice && notice.shotKey === shotKey(selected) && <p className="shot-workspace__hint is-success" role="status">{notice.text}</p>}
            {error && <p className="shot-workspace__warning" role="alert">{error}</p>}
          </div>

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
                key={`${shotKey(selected)}:${selected.video_prompt}`}
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
              <div className="shot-workspace__media-grid">
                <div className="shot-workspace__column">
                  <figure className="shot-workspace__reference">
                    <figcaption><ImageIcon size={14} aria-hidden="true" /> {t('参考图')}</figcaption>
                    <div className="shot-workspace__frame">
                      {selected.image_url
                        ? <img src={selected.image_url} alt={`镜头 ${selected.shot_id} 分镜图`} />
                        : <p className="shot-workspace__hint">{t('尚未生成')}</p>}
                      <b>1</b>
                    </div>
                  </figure>
                  <section className="shot-workspace__plan" aria-label={t('运镜方案')}>
                    <h4><Video size={14} aria-hidden="true" /> {t('运镜方案')}</h4>
                    <div className="shot-workspace__plan-item">
                      <i>1</i>
                      <div>
                        <strong>{t('视频描述')}</strong>
                        <p>{selected.video_prompt || selected.desc || '（暂无）'}</p>
                        <button type="button" className="shot-workspace__link" onClick={() => setTab('prompts')}>{t('编辑提示词')}</button>
                      </div>
                    </div>
                  </section>
                </div>
                <div className="shot-workspace__column">
                  <figure className="shot-workspace__clip">
                    <figcaption>
                      <Film size={14} aria-hidden="true" /> {t('正式片')}
                      {selected.route && (
                        <small className="shot-workspace__route">自动路由：{selected.route.mode} · {selected.route.provider_family}{selected.route.reasons?.[0] ? ` · ${selected.route.reasons[0]}` : ''}</small>
                      )}
                    </figcaption>
                    <div className="shot-workspace__frame is-video">
                      {selected.video_url
                        ? <video src={selected.video_url} controls loop preload="metadata" aria-label={`镜头 ${selected.shot_id} 视频`} />
                        : <p className="shot-workspace__hint">{t('尚未生成')}</p>}
                    </div>
                    {(selected.candidate_urls?.length ?? 0) > 1 && (
                      <ul className="shot-workspace__candidates" aria-label={t('候选版本')}>
                        {selected.candidate_urls!.map((url, index) => (
                          <li key={url} className={url === selected.video_url ? 'is-current' : ''}>
                            <span>版本 {index + 1}</span>
                            <button type="button" className="secondary-action" disabled={saving} onClick={() => { void selectCandidate(url); }}>{t('选用此版')}</button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </figure>
                  <ShotDeskPanel
                    taskId={taskId} sceneId={selected.scene_id} shotId={selected.shot_id} reloadToken={deskToken}
                    onOpenDesk={() => setDeskShot({ sceneId: selected.scene_id, shotId: selected.shot_id })}
                  />
                </div>
              </div>
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
                  {fixPlan.variable_name && <p className="shot-workspace__hint">本轮只改：{fixPlan.variable_name}</p>}
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
            <strong>{generated}/{workspace.shots.length} {t('个运镜已完成')}</strong>
            <span className="shot-workspace__footer-sep" aria-hidden="true">|</span>
            <strong>{episodesDone}/{episodes.length} {t('集完成')}</strong>
            <span className="shot-workspace__footer-note">
              <Clapperboard size={13} aria-hidden="true" />
              视频模型 {workspace.video_model || videoModel} · 可用时长 {workspace.duration_options[0]}–{workspace.duration_options[workspace.duration_options.length - 1]} 秒 · 修改只影响本镜，流程仍按 8 个 Agent 顺序推进。
            </span>
          </footer>
        </section>
      )}
      {queue && queueOpen && (
        <aside id="shot-queue-drawer" className="shot-workspace__drawer" role="dialog" aria-modal="false" aria-label={t('生成队列')}>
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
            <button type="button" className="shot-workspace__drawer-close" aria-label={t('关闭队列')} onClick={() => setQueueOpen(false)}><X size={15} aria-hidden="true" /></button>
          </header>
          {queueNotice && <p className="shot-workspace__hint" role="status">{queueNotice}</p>}
          {(() => {
            const { active, settled } = splitQueueItems(queue.items);
            const shown = showSettled ? queue.items : active;
            const breakdown = (['done', 'cancelled', 'skipped'] as const)
              .filter(status => settled.some(item => item.status === status))
              .map(status => `${QUEUE_STATUS_LABELS[status]} ${settled.filter(item => item.status === status).length}`)
              .join(' · ');
            return (
              <>
                {settled.length > 0 && (
                  <button type="button" className="shot-workspace__queue-fold" aria-expanded={showSettled} onClick={() => setShowSettled(value => !value)}>
                    {showSettled ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
                    已结束 {settled.length} 项（{breakdown}）
                  </button>
                )}
                {shown.length > 0 && (
          <ul className="shot-workspace__queue-items">
            {shown.map(item => (
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
                )}
              </>
            );
          })()}
        </aside>
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
