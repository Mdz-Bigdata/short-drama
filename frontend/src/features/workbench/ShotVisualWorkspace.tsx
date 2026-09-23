import { ChevronDown, ChevronRight, Clapperboard, ImageIcon, RefreshCcw, Save, Search, Video } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';

import { apiRequest } from '../../api/client';
import { ShotDeskPanel } from './ShotDeskPanel';
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
} from './shotVisual';

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
      <label htmlFor="shot-visual-duration">时长</label>
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
            aria-label="时长选择"
            aria-valuetext={`${value} 秒`}
            onChange={event => onChange(Number(event.target.value))}
          />
          <span className="shot-workspace__duration-value">{value} 秒</span>
        </div>
      ) : (
        <div className="shot-workspace__duration-chips" role="radiogroup" aria-label="时长选择">
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
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

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
    return <div className="stage-five-empty" role="status">正在加载镜头工作区…</div>;
  }
  if (!workspace) {
    return <div className="stage-five-empty" role="status">{error || '镜头工作区不可用。'}</div>;
  }
  if (workspace.shots.length === 0) {
    return (
      <div className="stage-five-empty" role="status">
        暂无分镜镜头。请先完成第 4 阶段分镜，再回到视觉阶段设置运镜。
      </div>
    );
  }

  const staleCount = workspace.shots.filter(shot => shot.stale).length;

  return (
    <div className={`shot-workspace${listCollapsed ? ' is-list-collapsed' : ''}`}>
      <aside className="shot-workspace__list" aria-label="分镜列表">
        <header className="shot-workspace__list-header">
          <button
            type="button"
            className="shot-workspace__list-toggle"
            aria-label={listCollapsed ? '展开分镜列表' : '折叠分镜列表'}
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
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索分镜…" aria-label="搜索分镜" />
            </label>
            <ul className="shot-workspace__shots" aria-label="分镜">
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
              {selected.settings_source === 'edited' && <small>人工设定</small>}
            </div>
            <div className="shot-workspace__detail-actions">
              <button type="button" className="secondary-action" onClick={() => { void save(); }} disabled={!dirty || locked}>
                <Save size={14} aria-hidden="true" /> {saving ? '保存中…' : '保存运镜'}
              </button>
              <button type="button" className="secondary-action" onClick={() => { void assignSeeds(); }} disabled={locked}>
                按场分配种子
              </button>
              {onRerun && (
                <button type="button" className="primary-action" onClick={onRerun} disabled={Boolean(workspace.running)}>
                  <RefreshCcw size={14} aria-hidden="true" /> 重跑第 5 阶段
                </button>
              )}
            </div>
          </header>

          {workspace.running && <p className="shot-workspace__hint" role="status">任务正在执行阶段，暂不能修改运镜。</p>}
          {(selected.stale || staleCount > 0) && (
            <p className="shot-workspace__hint is-stale" role="status">
              {selected.stale ? selected.stale_reason || '内容已更新，提示词可能不符' : `${staleCount} 镜已修改运镜，重跑第 5 阶段后生效。`}
            </p>
          )}
          {dirty && <p className="shot-workspace__hint" role="status">运镜设置已修改，保存后重跑第 5 阶段生效。</p>}
          {selected.derived_notes.map(note => <p key={note} className="shot-workspace__hint">{note}</p>)}
          {notice && notice.shotId === selected.shot_id && <p className="shot-workspace__hint is-success" role="status">{notice.text}</p>}
          {error && <p className="shot-workspace__warning" role="alert">{error}</p>}

          <div className="shot-workspace__tabs" role="tablist" aria-label="镜头详情">
            {([['script', '脚本 / 对话'], ['prompts', '提示词'], ['media', '分镜 / 视频']] as Array<[DetailTab, string]>).map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'is-active' : ''} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'script' && (
            <div className="shot-workspace__panel" role="tabpanel">
              <h4>画面描述</h4>
              <p>{selected.desc || '（暂无画面描述）'}</p>
              <h4>对话</h4>
              <p>{selected.dialogue || '（暂无对话）'}</p>
              <h4>声音</h4>
              <p>{selected.sound || '（暂无声音说明）'}</p>
            </div>
          )}

          {tab === 'prompts' && (
            <div className="shot-workspace__panel" role="tabpanel">
              <h4><ImageIcon size={14} aria-hidden="true" /> Image Prompt · 分镜图 <small>{imageModel}</small></h4>
              <pre>{selected.image_prompt || '待生成'}</pre>
              <h4><Video size={14} aria-hidden="true" /> Video Prompt · 视频 <small>{videoModel}</small></h4>
              <pre>{selected.video_prompt || '待生成'}</pre>
            </div>
          )}

          {tab === 'media' && (
            <div className="shot-workspace__panel shot-workspace__media" role="tabpanel">
              <ShotDeskPanel
                taskId={taskId} sceneId={selected.scene_id} shotId={selected.shot_id} reloadToken={deskToken}
                onOpenDesk={() => setDeskShot({ sceneId: selected.scene_id, shotId: selected.shot_id })}
              />
              <figure>
                <figcaption><ImageIcon size={14} aria-hidden="true" /> 分镜图</figcaption>
                {selected.image_url ? <img src={selected.image_url} alt={`镜头 ${selected.shot_id} 分镜图`} /> : <p className="shot-workspace__hint">尚未生成</p>}
              </figure>
              <figure>
                <figcaption><Video size={14} aria-hidden="true" /> 视频</figcaption>
                {selected.video_url
                  ? <video src={selected.video_url} controls loop preload="metadata" aria-label={`镜头 ${selected.shot_id} 视频`} />
                  : <p className="shot-workspace__hint">尚未生成</p>}
                {selected.route && (
                  <small className="shot-workspace__route">自动路由：{selected.route.mode} · {selected.route.provider_family}{selected.route.reasons?.[0] ? ` · ${selected.route.reasons[0]}` : ''}</small>
                )}
                {(selected.candidate_urls?.length ?? 0) > 1 && (
                  <ul className="shot-workspace__candidates" aria-label="候选版本">
                    {selected.candidate_urls!.map((url, index) => (
                      <li key={url}>
                        <span>版本 {index + 1}</span>
                        <button type="button" className="secondary-action" disabled={saving} onClick={() => { void selectCandidate(url); }}>选用此版</button>
                      </li>
                    ))}
                  </ul>
                )}
              </figure>
            </div>
          )}

          <Collapsible title="运镜 / 音效 / 对话" defaultOpen>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-motion">镜头运动</label>
              <select id="shot-visual-motion" value={draft.camera_motion} disabled={locked} onChange={event => update({ camera_motion: event.target.value })}>
                {workspace.camera_motions.map(entry => <option key={entry.value} value={entry.value}>{entry.label}（{entry.value}）</option>)}
              </select>
              <small>一镜只用一种运镜，按 {workspace.provider_family || '所选模型'} 官方运镜写法写入视频提示词。</small>
            </div>
            {(workspace.recipe_categories?.length ?? 0) > 0 && (
              <div className="shot-workspace__field shot-workspace__recipe">
                <label htmlFor="shot-visual-recipe">运镜灵感</label>
                <div className="shot-workspace__recipe-controls">
                  <select id="shot-visual-recipe" value={recipeCategory} disabled={locked} onChange={event => setRecipeCategory(event.target.value)}>
                    <option value="">选择叙事类别…</option>
                    {workspace.recipe_categories!.map(entry => <option key={entry.value} value={entry.value}>{entry.label} · {entry.purpose}</option>)}
                  </select>
                  <div className="shot-workspace__duration-chips" role="radiogroup" aria-label="情绪强度">
                    {INTENSITIES.map(([key, label]) => (
                      <button key={key} type="button" role="radio" aria-checked={recipeIntensity === key} className={recipeIntensity === key ? 'is-active' : ''} disabled={locked} onClick={() => setRecipeIntensity(key)}>{label}</button>
                    ))}
                  </div>
                  <button type="button" className="secondary-action" disabled={!recipeCategory || locked || composing} onClick={() => { void composeRecipe(); }}>
                    {composing ? '生成中…' : '生成配方'}
                  </button>
                </div>
                {recipe && (
                  <div className="shot-workspace__recipe-result">
                    <p><strong>{recipe.category_label} · {recipe.camera_motion_label} · {recipe.angle_label} · {recipe.rhythm_label}</strong></p>
                    <p>{recipe.prompt_zh}</p>
                    <p className="shot-workspace__hint">EN: {recipe.prompt_en}</p>
                    <p className="shot-workspace__hint">反向: {recipe.negative}</p>
                    <button type="button" className="secondary-action" disabled={locked} onClick={applyRecipe}>套用到本镜</button>
                  </div>
                )}
                <small>画风与质感锁死，相邻镜只换运动、角度、节奏或环境之一，避免撞镜。</small>
              </div>
            )}
            <div className="shot-workspace__field shot-workspace__feedback">
              <label htmlFor="shot-visual-feedback">这一镜翻车了？</label>
              <textarea
                id="shot-visual-feedback"
                rows={2}
                value={failureText}
                placeholder="用自己的话写：脸崩了 / 手是六根手指 / 特效糊住了脸 / 位置跳了…"
                onChange={event => setFailureText(event.target.value)}
              />
              <div className="shot-workspace__recipe-controls">
                <button
                  type="button"
                  className="secondary-action"
                  disabled={reporting || !failureText.trim()}
                  onClick={() => { void reportOutcome('failed'); }}
                >
                  {reporting ? '提交中…' : '报告问题'}
                </button>
                <button
                  type="button"
                  className="secondary-action"
                  disabled={reporting}
                  onClick={() => { void reportOutcome('success'); }}
                >
                  这条可用
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
                  {fixPlan.give_up && <p className="shot-workspace__hint">已到模型能力边界：考虑换等价表达或换模型。</p>}
                </div>
              )}
              <small>同一类问题在同一模型上出现两次，后续镜头会自动按它预防性加固。</small>
            </div>
            <DurationSelector value={draft.duration_seconds} options={workspace.duration_options} disabled={locked} onChange={seconds => update({ duration_seconds: seconds })} />
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-action">动作演变</label>
              <textarea id="shot-visual-action" value={draft.action} disabled={locked} rows={3} placeholder="描述这一镜的动作演变：从分镜图开始如何运动…" onChange={event => update({ action: event.target.value })} />
            </div>
            <div className="shot-workspace__field shot-workspace__seed-row">
              <label htmlFor="shot-visual-seed">种子</label>
              <input id="shot-visual-seed" type="number" min={0} max={2147483647} value={draft.seed ?? ''} disabled={locked} placeholder="留空则随机"
                onChange={event => update({ seed: event.target.value === '' ? null : Number(event.target.value) })} />
              <label htmlFor="shot-visual-candidates">生成版本数</label>
              <select id="shot-visual-candidates" value={draft.candidates ?? 1} disabled={locked} onChange={event => update({ candidates: Number(event.target.value) })}>
                {[1, 2, 3, 4].map(count => <option key={count} value={count}>{count} 次择优</option>)}
              </select>
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-ambiance-audio">环境音效</label>
              <input id="shot-visual-ambiance-audio" value={draft.ambiance_audio} disabled={locked} placeholder="环境音效描述..." onChange={event => update({ ambiance_audio: event.target.value })} />
            </div>
            <div className="shot-workspace__field">
              <span className="shot-workspace__label">对话</span>
              <p className="shot-workspace__readonly">{selected.dialogue || '（暂无对话）'}</p>
            </div>
          </Collapsible>

          <Collapsible title="composition · 构图">
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-shot-type">镜头</label>
              <select id="shot-visual-shot-type" value={draft.shot_type} disabled={locked} onChange={event => update({ shot_type: event.target.value })}>
                {workspace.shot_types.map(entry => <option key={entry.value} value={entry.value}>{entry.label}（{entry.value}）</option>)}
              </select>
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-lighting">光线</label>
              <input id="shot-visual-lighting" value={draft.lighting} disabled={locked} placeholder="光线描述..." onChange={event => update({ lighting: event.target.value })} />
            </div>
            <div className="shot-workspace__field">
              <label htmlFor="shot-visual-ambiance">氛围</label>
              <input id="shot-visual-ambiance" value={draft.ambiance} disabled={locked} placeholder="氛围描述..." onChange={event => update({ ambiance: event.target.value })} />
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
