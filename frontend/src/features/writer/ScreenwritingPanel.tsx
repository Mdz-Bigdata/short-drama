import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BookOpenText, ChevronDown, ChevronRight, Clapperboard, FileCode2, Save } from 'lucide-react';

import { ApiError, isUnauthorized } from '../../api/client';
import { draftOfScene, planOperations, type PlanDraft } from './planOperations';
import {
  fetchScreenwritingEpisode,
  fetchScreenwritingPrompt,
  fetchScreenwritingState,
  patchScreenwritingPlan,
  type ScreenwritingEpisode,
  type ScreenwritingPromptStage,
  type ScreenwritingState,
} from './screenwritingApi';

const SOURCE_KIND_LABEL: Record<string, string> = {
  outline: '按导演大纲创作',
  novel: '由小说改编',
  screenplay: '从成品剧本提取',
};

function violationMessage(error: unknown): string {
  // The API reports plan problems as readable text (which operation, which shot, which rule).
  if (error instanceof ApiError && error.message) return error.message;
  return '分镜规划保存失败，请稍后重试。';
}

export function ScreenwritingPanel({ taskId }: { taskId: string }) {
  const [state, setState] = useState<ScreenwritingState | null>(null);
  const [error, setError] = useState('');
  const [openEpisode, setOpenEpisode] = useState<number | null>(null);
  const [episode, setEpisode] = useState<ScreenwritingEpisode | null>(null);
  const [drafts, setDrafts] = useState<Record<string, PlanDraft>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [prompt, setPrompt] = useState('');

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    fetchScreenwritingState(taskId, controller.signal)
      .then(data => { setState(data); setError(''); })
      .catch(caught => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setState(null);
        setError(isUnauthorized(caught) ? '登录状态已过期，请重新登录后继续。' : '结构化编剧数据暂不可用。');
      });
    return () => controller.abort();
  }, [taskId]);

  const loadEpisode = useCallback((index: number) => {
    setPrompt('');
    setNotice('');
    fetchScreenwritingEpisode(taskId, index)
      .then(data => {
        setEpisode(data);
        setDrafts(Object.fromEntries(data.plan.scenes.map(scene => [scene.scene_id, draftOfScene(scene)])));
      })
      .catch(() => setError('该集的分镜规划读取失败。'));
  }, [taskId]);

  const toggleEpisode = (index: number) => {
    if (openEpisode === index) {
      setOpenEpisode(null);
      setEpisode(null);
      return;
    }
    setOpenEpisode(index);
    setEpisode(null);
    loadEpisode(index);
  };

  const scenes = useMemo(() => episode?.plan.scenes ?? [], [episode]);
  const operations = useMemo(() => planOperations(scenes, drafts), [scenes, drafts]);
  const violationsByScene = useMemo(() => {
    const map = new Map<string, string[]>();
    (episode?.violations ?? []).forEach(violation => {
      const key = violation.sceneId || '';
      map.set(key, [...(map.get(key) || []), violation.message]);
    });
    return map;
  }, [episode]);

  const save = async () => {
    if (!episode || operations.length === 0) return;
    setSaving(true);
    setNotice('');
    const submit = (confirmInvalidate: boolean) => patchScreenwritingPlan(taskId, episode.episode, {
      baseRevision: episode.planRevision,
      operations,
      confirmInvalidate,
    });
    try {
      let updated: ScreenwritingEpisode;
      try {
        updated = await submit(false);
      } catch (caught) {
        // Editing a shot invalidates the角色 / 分镜 / 成片 built from the old plan,
        // so the same confirmation the screenplay editor asks for is asked here.
        const needsConfirm = caught instanceof ApiError
          && caught.status === 409
          && /归档|下游|成片|角色、分镜/.test(String(caught.message));
        if (!needsConfirm) throw caught;
        if (!window.confirm('保存分镜改动会归档当前角色、分镜和成片，并从编剧阶段重新开始。旧成果仍保留在版本归档中。是否继续？')) {
          setNotice('已取消保存，本地改动仍保留。');
          return;
        }
        updated = await submit(true);
      }
      setEpisode(updated);
      setDrafts(Object.fromEntries(updated.plan.scenes.map(scene => [scene.scene_id, draftOfScene(scene)])));
      setNotice(updated.rewrittenSceneIds.length
        ? `已保存，重写了 ${updated.rewrittenSceneIds.join('、')} 的画面与动作提示词。`
        : '已保存。');
      setState(await fetchScreenwritingState(taskId));
    } catch (caught) {
      setNotice(violationMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const showPrompt = async (stage: ScreenwritingPromptStage) => {
    if (!episode) return;
    try {
      const data = await fetchScreenwritingPrompt(taskId, episode.episode, stage);
      setPrompt(data.prompt);
    } catch {
      setNotice('提示词预览读取失败。');
    }
  };

  if (error) return <p className="writer-empty" role="status">{error}</p>;
  if (!state) return <p className="writer-empty">正在读取结构化编剧数据…</p>;
  if (!state.available) {
    return (
      <p className="writer-empty">
        本项目的剧本由自由文本引擎生成，没有结构化分集规划。重新执行第 2 阶段即可获得分集账本与可编辑的分镜规划。
      </p>
    );
  }

  const durations = state.durations.supported;
  return (
    <div className="writer-screenwriting">
      <dl className="writer-screenwriting__meta">
        <div><dt>创作口径</dt><dd>{SOURCE_KIND_LABEL[state.sourceKind || ''] || '未知'}</dd></div>
        <div><dt>合法单镜时长</dt><dd>{durations.length ? `${durations[0]}–${durations[durations.length - 1]} 秒` : '—'}</dd></div>
        <div><dt>单集目标时长</dt><dd>{state.durations.episodeTargetSeconds ? `${state.durations.episodeTargetSeconds} 秒` : '未设置'}</dd></div>
        <div><dt>视频模型</dt><dd>{state.durations.videoModel || '未指定'}</dd></div>
      </dl>

      {state.stale && (
        <p className="writer-screenwriting__stale" role="status">
          <AlertTriangle aria-hidden="true" /> {state.staleReason || '剧本正文已被手动修改，分镜规划不再与正文一致。'}
        </p>
      )}

      <ol className="writer-screenwriting__ledger">
        {state.ledger.map(entry => {
          const summary = state.episodes.find(item => item.episode === entry.episode);
          const open = openEpisode === entry.episode;
          return (
            <li key={entry.episode} className={open ? 'is-open' : ''}>
              <button type="button" className="writer-screenwriting__toggle" aria-expanded={open} onClick={() => toggleEpisode(entry.episode)}>
                {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
                <span className="writer-screenwriting__episode">第 {entry.episode} 集</span>
                <strong>{entry.title || '未命名'}</strong>
                {summary && <span className="writer-screenwriting__count">{summary.sceneCount} 个分镜 · {summary.durationSeconds} 秒</span>}
                {summary && summary.needsReplan.length > 0 && (
                  <span className="writer-screenwriting__flag"><AlertTriangle aria-hidden="true" /> {summary.needsReplan.length} 个分镜待重拆</span>
                )}
              </button>
              <div className="writer-screenwriting__outline">
                {entry.hook && <p><span>集尾钩子</span>{entry.hook}</p>}
                {entry.storyBeats.length > 0 && (
                  <ul>{entry.storyBeats.map((beat, index) => <li key={index}>{beat}</li>)}</ul>
                )}
                {entry.nextEpisodeTeaser && <p><span>下集预告</span>{entry.nextEpisodeTeaser}</p>}
              </div>

              {open && (
                <div className="writer-screenwriting__plan">
                  {!episode && <p className="writer-empty">正在读取分镜规划…</p>}
                  {episode && episode.episode === entry.episode && (
                    <>
                      <div className="writer-screenwriting__actions">
                        <button type="button" onClick={() => { void showPrompt('plan'); }}><FileCode2 aria-hidden="true" /> 查看内容层提示词</button>
                        {state.sourceKind === 'outline' && (
                          <button type="button" onClick={() => { void showPrompt('prose'); }}><BookOpenText aria-hidden="true" /> 查看正文提示词</button>
                        )}
                        <button type="button" onClick={() => { void showPrompt('visual'); }}><Clapperboard aria-hidden="true" /> 查看视觉层提示词</button>
                        <button
                          type="button"
                          className="is-primary"
                          disabled={saving || operations.length === 0}
                          onClick={() => { void save(); }}
                        >
                          <Save aria-hidden="true" /> {saving ? '保存中…' : `保存改动${operations.length ? `（${operations.length}）` : ''}`}
                        </button>
                      </div>
                      {notice && <p className="writer-screenwriting__notice" role="status">{notice}</p>}
                      {prompt && <pre className="writer-screenwriting__prompt">{prompt}</pre>}
                      <table className="writer-screenwriting__table">
                        <thead>
                          <tr><th>分镜</th><th>时长</th><th>场景 / 出场</th><th>画面</th><th>口播</th></tr>
                        </thead>
                        <tbody>
                          {scenes.map(scene => {
                            const draft = drafts[scene.scene_id] || draftOfScene(scene);
                            const messages = violationsByScene.get(scene.scene_id) || [];
                            return (
                              <tr key={scene.scene_id} className={scene.needs_replan ? 'is-flagged' : ''}>
                                <td>
                                  <code>{scene.scene_id}</code>
                                  {scene.segment_break && <span className="writer-screenwriting__break">场景切换</span>}
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    aria-label={`${scene.scene_id} 时长（秒）`}
                                    min={durations[0] || 1}
                                    max={durations[durations.length - 1] || 60}
                                    value={draft.duration}
                                    onChange={event => setDrafts(current => ({ ...current, [scene.scene_id]: { ...draft, duration: event.target.value } }))}
                                  />
                                </td>
                                <td>
                                  <span>{scene.setting || '—'}</span>
                                  <small>{(scene.characters_in_scene || []).join('、') || '无角色'}</small>
                                </td>
                                <td>
                                  <textarea
                                    aria-label={`${scene.scene_id} 画面描述`}
                                    rows={3}
                                    value={draft.description}
                                    onChange={event => setDrafts(current => ({ ...current, [scene.scene_id]: { ...draft, description: event.target.value } }))}
                                  />
                                  {messages.map((message, index) => (
                                    <p key={index} className="writer-screenwriting__violation">{message}</p>
                                  ))}
                                </td>
                                <td>
                                  {(scene.utterances || []).length === 0 && <span>—</span>}
                                  {(scene.utterances || []).map((utterance, index) => (
                                    <p key={index}>
                                      <b>{utterance.kind === 'dialogue' ? utterance.speaker : '旁白'}</b>
                                      {utterance.text}
                                      {utterance.delivery && <small>{utterance.delivery}</small>}
                                    </p>
                                  ))}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
