import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Clapperboard, Download, Music, RefreshCcw, Scissors, Upload, XCircle } from 'lucide-react';

import { ApiError, apiRequest, apiUrl } from '../../api/client';
import './TimelinePanel.css';
import { t } from '../../i18n';
import { DeliveryChecklist, type AcceptanceIssue } from './DeliveryChecklist';

export interface SoundJoin {
  join: '' | 'j_cut' | 'l_cut';
  seconds?: number;
  edited?: boolean;
  result?: { applied: boolean; seconds?: number; reason: string };
}

export interface TimelineClip {
  shot_id: number;
  /** 全剧唯一的镜头编号(集·场·镜)；各场镜号都从 1 起。旧时间线上可能没有。 */
  shot_uid?: number;
  scene_id?: string;
  video_url: string;
  candidates: string[];
  duration: number | null;
  in: number;
  out: number | null;
  muted: boolean;
  subtitle: string;
  voice_path: string | null;
  transition_in: { type: string; duration: number } | null;
  sound_in?: SoundJoin | null;
  review: { decision: 'pending' | 'approved' | 'rejected'; note: string; decided_at: string | null };
}

export interface Timeline {
  title: { text: string; seconds: number };
  clips: TimelineClip[];
  bgm: { source: 'none' | 'generated' | 'library'; path: string | null; url: string | null; library_id: string | null; name: string | null; volume: number; duck: boolean };
  revision: number;
}

export interface BgmTrack { id: string; name: string; mood: string; seconds: number | null; source: string }

interface TimelineResponse {
  task_id: string;
  timeline: Timeline;
  summary: { clips: number; included: number; review: Record<string, number>; seconds: number; bgm: string; revision: number };
  transitions: string[];
  bgm_library: BgmTrack[];
  // 成片交付前验收：按现在的修剪逐镜过一遍(后端 delivery_check)。
  acceptance?: AcceptanceIssue[];
}

const TRANSITION_LABELS: Record<string, string> = {
  hard_cut: '硬切', match_cut: '动作匹配', crossfade: '叠化', dip_to_black: '转黑', neutral_bridge: '中性过渡',
};
const SOUND_JOIN_SECONDS = [0.3, 0.5, 0.8, 1.2];
const DEFAULT_SOUND_JOIN_SECONDS = { j_cut: 0.4, l_cut: 0.5 } as const;
const DECISION_LABELS = { pending: '待审看', approved: '通过', rejected: '打回' } as const;

/** What the user has typed and not saved yet; a field left alone shows the saved value. */
type ClipDraft = { in?: string; out?: string; subtitle?: string };

const clipKey = (clip: TimelineClip) => clip.shot_uid ?? clip.shot_id;
const clipRef = (clip: TimelineClip) => (clip.shot_uid ? { shot_id: clip.shot_id, shot_uid: clip.shot_uid } : { shot_id: clip.shot_id });
const clipName = (clip: TimelineClip) => `${clip.scene_id ? `${clip.scene_id} · ` : ''}镜头 ${clip.shot_id}`;

interface Props {
  taskId: string;
  /** Called after a render so the shell can refresh the task (new final video). */
  onRendered?: (finalVideoUrl: string) => void;
}

export function TimelinePanel({ taskId, onRendered }: Props) {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [drafts, setDrafts] = useState<Record<number, ClipDraft>>({});
  const [titleDraft, setTitleDraft] = useState<string | null>(null);
  const [volumeDraft, setVolumeDraft] = useState<number | null>(null);
  const [draftsOf, setDraftsOf] = useState(taskId);
  const [uploadName, setUploadName] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  if (draftsOf !== taskId) {
    setDraftsOf(taskId);
    setDrafts({});
    setTitleDraft(null);
    setVolumeDraft(null);
  }

  const editDraft = (id: number, patch: ClipDraft) => setDrafts(current => ({ ...current, [id]: { ...current[id], ...patch } }));
  const dropDraft = (id: number, ...fields: Array<keyof ClipDraft>) => setDrafts(current => {
    const rest = { ...current[id] };
    for (const field of fields) delete rest[field];
    return { ...current, [id]: rest };
  });

  const load = useCallback(async () => {
    try {
      setData(await apiRequest<TimelineResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline`));
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '时间线读取失败');
    }
  }, [taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const operate = useCallback(async (body: Record<string, unknown>, label: string) => {
    setBusy(label);
    setNotice('');
    try {
      setData(await apiRequest<TimelineResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline/ops`, { method: 'POST', body: JSON.stringify(body) }));
      setNotice(t('{0}已更新，重新合成后生效。', [label]));
      return true;
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : `${label}失败`);
      return false;
    } finally {
      setBusy('');
    }
  }, [taskId]);

  const render = useCallback(async () => {
    setBusy('render');
    setNotice('');
    try {
      const result = await apiRequest<{ final_video_url: string }>(`/api/drama/${encodeURIComponent(taskId)}/timeline/render`, { method: 'POST', body: JSON.stringify({}) });
      setNotice(t('已按时间线重新合成成片。'));
      onRendered?.(result.final_video_url);
      await load();
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : '合成失败');
    } finally {
      setBusy('');
    }
  }, [load, onRendered, taskId]);

  const uploadBgm = useCallback(async (file: File) => {
    setBusy('upload');
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('name', uploadName.trim() || file.name.replace(/\.[^.]+$/, ''));
      const track = await apiRequest<BgmTrack>('/api/library/bgm', { method: 'POST', body: form });
      setUploadName('');
      await operate({ operation: 'bgm', source: 'library', library_id: track.id }, '配乐');
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : '配乐上传失败');
      setBusy('');
    }
  }, [operate, uploadName]);

  if (error) return <p className="timeline__empty" role="status">{error}</p>;
  if (!data) return <p className="timeline__empty">{t('正在读取剪辑时间线…')}</p>;
  const { timeline, summary, transitions } = data;
  const titleText = titleDraft ?? timeline.title.text;
  const volume = volumeDraft ?? timeline.bgm.volume;
  // 拖动时只动本地的值，松手才提交一次。
  const commitVolume = () => {
    if (volumeDraft === null || busy !== '') return;
    if (volumeDraft === timeline.bgm.volume) { setVolumeDraft(null); return; }
    void operate({ operation: 'bgm', source: timeline.bgm.source, library_id: timeline.bgm.library_id, volume: volumeDraft }, '配乐音量').then(() => setVolumeDraft(null));
  };

  return (
    <section className="timeline" aria-label={t('剪辑时间线')}>
      <header className="timeline__head">
        <Scissors aria-hidden="true" />
        <strong>{t('剪辑时间线')}</strong>
        <span>{summary.included}/{summary.clips} 镜入片 · 约 {summary.seconds} 秒 · 通过 {summary.review.approved ?? 0} · 打回 {summary.review.rejected ?? 0} · 待审看 {summary.review.pending ?? 0}</span>
        <button type="button" className="is-primary" disabled={busy !== ''} onClick={() => { void render(); }}>
          <RefreshCcw aria-hidden="true" /> {busy === 'render' ? t('合成中…') : t('按时间线重新合成')}
        </button>
        <a className="timeline__download" href={apiUrl(`/api/drama/${encodeURIComponent(taskId)}/timeline/jianying.zip`)} download>
          <Download aria-hidden="true" /> {t('下载剪映草稿')}
        </a>
      </header>
      {notice && <p className="timeline__notice" role="status">{notice}</p>}
      <DeliveryChecklist issues={data.acceptance ?? []} />

      <div className="timeline__row">
        <label>{t('片头标题')}
          <input aria-label={t('片头标题')} value={titleText} onChange={event => setTitleDraft(event.target.value)} placeholder={t('留空则无片头')} />
        </label>
        <button type="button" disabled={busy !== '' || titleText === timeline.title.text} onClick={() => { void operate({ operation: 'title', text: titleText }, '片头').then(saved => { if (saved) setTitleDraft(null); }); }}>{t('保存片头')}</button>
      </div>

      <ol className="timeline__clips">
        {timeline.clips.map((clip, index) => {
          const id = clipKey(clip);
          const ref = clipRef(clip);
          const name = clipName(clip);
          const draft = drafts[id] ?? {};
          const saved = { in: String(clip.in ?? 0), out: clip.out === null ? '' : String(clip.out) };
          const trimIn = draft.in ?? saved.in;
          const trimOut = draft.out ?? saved.out;
          const subtitle = draft.subtitle ?? clip.subtitle;
          const decision = clip.review.decision;
          return (
            <li key={id} className={`is-${decision}`}>
              <div className="timeline__clip-head">
                <Clapperboard aria-hidden="true" />
                <strong>{name}</strong>
                <span className="timeline__badge">{DECISION_LABELS[decision]}</span>
                <small>{clip.duration ? `${clip.duration} 秒` : '时长未知'}{clip.muted ? ' · 已静音' : ''}</small>
                <button type="button" aria-label={`通过${name}`} disabled={busy !== ''} onClick={() => { void operate({ operation: 'review', ...ref, decision: 'approved' }, '审看'); }}><CheckCircle2 aria-hidden="true" /> {t('通过')}</button>
                <button type="button" aria-label={`打回${name}`} disabled={busy !== ''} onClick={() => {
                  const note = window.prompt('打回原因（可选）', clip.review.note || '');
                  if (note === null) return;
                  void operate({ operation: 'review', ...ref, decision: 'rejected', note }, '审看');
                }}><XCircle aria-hidden="true" /> {t('打回')}</button>
              </div>
              {clip.review.note && <p className="timeline__note">审看备注：{clip.review.note}</p>}
              <div className="timeline__clip-body">
                <video src={clip.video_url} controls preload="metadata" />
                <div className="timeline__fields">
                  <label>{t('入点（秒）')}<input type="number" min={0} step={0.1} aria-label={`${name} 入点`} value={trimIn} onChange={event => editDraft(id, { in: event.target.value })} /></label>
                  <label>{t('出点（秒）')}<input type="number" min={0} step={0.1} aria-label={`${name} 出点`} value={trimOut} placeholder={t('到结尾')} onChange={event => editDraft(id, { out: event.target.value })} /></label>
                  <button type="button" className={trimIn !== saved.in || trimOut !== saved.out ? 'is-unsaved' : undefined} disabled={busy !== ''} onClick={() => { void operate({ operation: 'trim', ...ref, start: Number(trimIn) || 0, end: trimOut === '' ? null : Number(trimOut) }, '裁剪').then(done => { if (done) dropDraft(id, 'in', 'out'); }); }}>{t('应用裁剪')}</button>
                  {index > 0 && (
                    <label>{t('转入转场')}
                      <select aria-label={`${name} 转场`} value={clip.transition_in?.type ?? 'crossfade'} disabled={busy !== ''} onChange={event => { void operate({ operation: 'transition', ...ref, kind: event.target.value, duration: clip.transition_in?.duration ?? 0.22 }, '转场'); }}>
                        {transitions.map(kind => <option key={kind} value={kind}>{TRANSITION_LABELS[kind] ?? kind}</option>)}
                      </select>
                    </label>
                  )}
                  {index > 0 && (
                    <label>{t('声音错开')}
                      <select aria-label={`${name} 声音错开`} value={clip.sound_in?.join ?? ''} disabled={busy !== ''} onChange={event => { void operate({ operation: 'sound_join', ...ref, join: event.target.value }, '声音'); }}>
                        <option value="">{t('声画同切')}</option>
                        <option value="j_cut">{t('J-cut：这一镜的声音先到')}</option>
                        <option value="l_cut">{t('L-cut：上一镜的声音留下')}</option>
                      </select>
                    </label>
                  )}
                  {index > 0 && clip.sound_in?.join && (
                    <label>{t('错开秒数')}
                      <select aria-label={`${name} 错开秒数`} value={clip.sound_in.seconds ?? DEFAULT_SOUND_JOIN_SECONDS[clip.sound_in.join]} disabled={busy !== ''} onChange={event => { void operate({ operation: 'sound_join', ...ref, join: clip.sound_in?.join, seconds: Number(event.target.value) }, '声音'); }}>
                        {[...new Set([...SOUND_JOIN_SECONDS, clip.sound_in.seconds ?? DEFAULT_SOUND_JOIN_SECONDS[clip.sound_in.join]])].sort((a, b) => a - b).map(value => <option key={value} value={value}>{value} {t('秒')}</option>)}
                      </select>
                    </label>
                  )}
                  {index > 0 && clip.sound_in?.result && (
                    <p className="timeline__wide timeline__note" role="status">
                      {clip.sound_in.result.applied ? `${t('上次合成已错开')} ${clip.sound_in.result.seconds ?? ''} ${t('秒')}` : `${t('上次合成没有错开：')}${clip.sound_in.result.reason}`}
                    </p>
                  )}
                  <label className="timeline__wide">{t('字幕')}
                    <input aria-label={`${name} 字幕`} value={subtitle} onChange={event => editDraft(id, { subtitle: event.target.value })} onBlur={() => {
                      if (draft.subtitle === undefined) return;
                      if (subtitle === clip.subtitle) dropDraft(id, 'subtitle');
                      else void operate({ operation: 'subtitle', ...ref, text: subtitle }, '字幕').then(done => { if (done) dropDraft(id, 'subtitle'); });
                    }} />
                  </label>
                  <label className="timeline__check"><input type="checkbox" checked={clip.muted} disabled={busy !== ''} onChange={event => { void operate({ operation: 'mute', ...ref, muted: event.target.checked }, '静音'); }} /> {t('本镜配音静音')}</label>
                  {clip.candidates.length > 1 && (
                    <label>{t('候选版本')}
                      <select aria-label={`${name} 候选版本`} value={clip.video_url} disabled={busy !== ''} onChange={event => { void operate({ operation: 'candidate', ...ref, video_url: event.target.value }, '候选'); }}>
                        {clip.candidates.map((url, position) => <option key={url} value={url}>版本 {position + 1}</option>)}
                      </select>
                    </label>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="timeline__bgm" aria-label={t('配乐')}>
        <header><Music aria-hidden="true" /><strong>{t('配乐')}</strong><span>当前：{timeline.bgm.source === 'none' ? '无配乐' : timeline.bgm.name ?? timeline.bgm.source} · 音量 {Math.round(volume * 100)}%{timeline.bgm.duck ? ' · 台词闪避' : ''}</span></header>
        <div className="timeline__row">
          <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'bgm', source: 'none' }, '配乐'); }}>{t('无配乐')}</button>
          <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'bgm', source: 'generated' }, '配乐'); }}>{t('第 6 阶段生成的配乐')}</button>
          <label>{t('音量')}<input type="range" min={0} max={1} step={0.02} aria-label={t('配乐音量')} value={volume} disabled={busy !== ''} onChange={event => setVolumeDraft(Number(event.target.value))} onPointerUp={commitVolume} onKeyUp={commitVolume} onBlur={commitVolume} /></label>
        </div>
        <ul className="timeline__library" aria-label={t('配乐库')}>
          {data.bgm_library.length === 0 && <li className="timeline__empty">{t('配乐库还是空的：上传一段音乐，或把第 6 阶段生成的配乐留在库里。')}</li>}
          {data.bgm_library.map(track => (
            <li key={track.id} className={timeline.bgm.library_id === track.id ? 'is-active' : ''}>
              <strong>{track.name}</strong>
              <small>{track.mood || '未标情绪'}{track.seconds ? ` · ${Math.round(track.seconds)} 秒` : ''} · {track.source === 'generated' ? t('生成') : t('上传')}</small>
              <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'bgm', source: 'library', library_id: track.id }, '配乐'); }}>{t('用这条')}</button>
            </li>
          ))}
        </ul>
        <div className="timeline__row">
          <input aria-label={t('配乐名称')} value={uploadName} onChange={event => setUploadName(event.target.value)} placeholder={t('配乐名称（可选）')} />
          <input ref={fileInput} type="file" accept="audio/mpeg,audio/wav,audio/mp4,audio/x-m4a,audio/aac,audio/ogg" aria-label={t('上传配乐文件')} onChange={event => { const file = event.target.files?.[0]; if (file) void uploadBgm(file); event.target.value = ''; }} />
          <button type="button" disabled={busy !== ''} onClick={() => fileInput.current?.click()}><Upload aria-hidden="true" /> {t('上传到配乐库')}</button>
        </div>
      </section>
    </section>
  );
}
