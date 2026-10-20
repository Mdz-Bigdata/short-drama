import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Clapperboard, Download, Music, RefreshCcw, Scissors, Upload, XCircle } from 'lucide-react';

import { ApiError, apiRequest, apiUrl } from '../../api/client';
import './TimelinePanel.css';
import { t } from '../../i18n';

export interface TimelineClip {
  shot_id: number;
  video_url: string;
  candidates: string[];
  duration: number | null;
  in: number;
  out: number | null;
  muted: boolean;
  subtitle: string;
  voice_path: string | null;
  transition_in: { type: string; duration: number } | null;
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
}

const TRANSITION_LABELS: Record<string, string> = {
  hard_cut: '硬切', match_cut: '动作匹配', crossfade: '叠化', dip_to_black: '转黑', neutral_bridge: '中性过渡',
};
const DECISION_LABELS = { pending: '待审看', approved: '通过', rejected: '打回' } as const;

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
  const [drafts, setDrafts] = useState<Record<number, { in: string; out: string; subtitle: string }>>({});
  const [titleDraft, setTitleDraft] = useState('');
  const [uploadName, setUploadName] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  const apply = useCallback((response: TimelineResponse) => {
    setData(response);
    setTitleDraft(response.timeline.title.text);
    setDrafts(Object.fromEntries(response.timeline.clips.map(clip => [clip.shot_id, {
      in: String(clip.in ?? 0), out: clip.out === null ? '' : String(clip.out), subtitle: clip.subtitle,
    }])));
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await apiRequest<TimelineResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline`));
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '时间线读取失败');
    }
  }, [apply, taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const operate = useCallback(async (body: Record<string, unknown>, label: string) => {
    setBusy(label);
    setNotice('');
    try {
      apply(await apiRequest<TimelineResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline/ops`, { method: 'POST', body: JSON.stringify(body) }));
      setNotice(t('{0}已更新，重新合成后生效。', [label]));
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : `${label}失败`);
    } finally {
      setBusy('');
    }
  }, [apply, taskId]);

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

      <div className="timeline__row">
        <label>{t('片头标题')}
          <input aria-label={t('片头标题')} value={titleDraft} onChange={event => setTitleDraft(event.target.value)} placeholder={t('留空则无片头')} />
        </label>
        <button type="button" disabled={busy !== '' || titleDraft === timeline.title.text} onClick={() => { void operate({ operation: 'title', text: titleDraft }, '片头'); }}>{t('保存片头')}</button>
      </div>

      <ol className="timeline__clips">
        {timeline.clips.map((clip, index) => {
          const draft = drafts[clip.shot_id] ?? { in: '0', out: '', subtitle: clip.subtitle };
          const decision = clip.review.decision;
          return (
            <li key={clip.shot_id} className={`is-${decision}`}>
              <div className="timeline__clip-head">
                <Clapperboard aria-hidden="true" />
                <strong>镜头 {clip.shot_id}</strong>
                <span className="timeline__badge">{DECISION_LABELS[decision]}</span>
                <small>{clip.duration ? `${clip.duration} 秒` : '时长未知'}{clip.muted ? ' · 已静音' : ''}</small>
                <button type="button" aria-label={`通过镜头 ${clip.shot_id}`} disabled={busy !== ''} onClick={() => { void operate({ operation: 'review', shot_id: clip.shot_id, decision: 'approved' }, '审看'); }}><CheckCircle2 aria-hidden="true" /> {t('通过')}</button>
                <button type="button" aria-label={`打回镜头 ${clip.shot_id}`} disabled={busy !== ''} onClick={() => {
                  const note = window.prompt('打回原因（可选）', clip.review.note || '') ?? '';
                  void operate({ operation: 'review', shot_id: clip.shot_id, decision: 'rejected', note }, '审看');
                }}><XCircle aria-hidden="true" /> {t('打回')}</button>
              </div>
              {clip.review.note && <p className="timeline__note">审看备注：{clip.review.note}</p>}
              <div className="timeline__clip-body">
                <video src={clip.video_url} controls preload="metadata" />
                <div className="timeline__fields">
                  <label>{t('入点（秒）')}<input type="number" min={0} step={0.1} aria-label={`镜头 ${clip.shot_id} 入点`} value={draft.in} onChange={event => setDrafts(current => ({ ...current, [clip.shot_id]: { ...draft, in: event.target.value } }))} /></label>
                  <label>{t('出点（秒）')}<input type="number" min={0} step={0.1} aria-label={`镜头 ${clip.shot_id} 出点`} value={draft.out} placeholder={t('到结尾')} onChange={event => setDrafts(current => ({ ...current, [clip.shot_id]: { ...draft, out: event.target.value } }))} /></label>
                  <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'trim', shot_id: clip.shot_id, start: Number(draft.in) || 0, end: draft.out === '' ? null : Number(draft.out) }, '裁剪'); }}>{t('应用裁剪')}</button>
                  {index > 0 && (
                    <label>{t('转入转场')}
                      <select aria-label={`镜头 ${clip.shot_id} 转场`} value={clip.transition_in?.type ?? 'crossfade'} disabled={busy !== ''} onChange={event => { void operate({ operation: 'transition', shot_id: clip.shot_id, kind: event.target.value, duration: clip.transition_in?.duration ?? 0.22 }, '转场'); }}>
                        {transitions.map(kind => <option key={kind} value={kind}>{TRANSITION_LABELS[kind] ?? kind}</option>)}
                      </select>
                    </label>
                  )}
                  <label className="timeline__wide">{t('字幕')}
                    <input aria-label={`镜头 ${clip.shot_id} 字幕`} value={draft.subtitle} onChange={event => setDrafts(current => ({ ...current, [clip.shot_id]: { ...draft, subtitle: event.target.value } }))} onBlur={() => { if (draft.subtitle !== clip.subtitle) void operate({ operation: 'subtitle', shot_id: clip.shot_id, text: draft.subtitle }, '字幕'); }} />
                  </label>
                  <label className="timeline__check"><input type="checkbox" checked={clip.muted} disabled={busy !== ''} onChange={event => { void operate({ operation: 'mute', shot_id: clip.shot_id, muted: event.target.checked }, '静音'); }} /> {t('本镜配音静音')}</label>
                  {clip.candidates.length > 1 && (
                    <label>{t('候选版本')}
                      <select aria-label={`镜头 ${clip.shot_id} 候选版本`} value={clip.video_url} disabled={busy !== ''} onChange={event => { void operate({ operation: 'candidate', shot_id: clip.shot_id, video_url: event.target.value }, '候选'); }}>
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
        <header><Music aria-hidden="true" /><strong>{t('配乐')}</strong><span>当前：{timeline.bgm.source === 'none' ? '无配乐' : timeline.bgm.name ?? timeline.bgm.source} · 音量 {Math.round(timeline.bgm.volume * 100)}%{timeline.bgm.duck ? ' · 台词闪避' : ''}</span></header>
        <div className="timeline__row">
          <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'bgm', source: 'none' }, '配乐'); }}>{t('无配乐')}</button>
          <button type="button" disabled={busy !== ''} onClick={() => { void operate({ operation: 'bgm', source: 'generated' }, '配乐'); }}>{t('第 6 阶段生成的配乐')}</button>
          <label>{t('音量')}<input type="range" min={0} max={1} step={0.02} aria-label={t('配乐音量')} value={timeline.bgm.volume} onChange={event => { void operate({ operation: 'bgm', source: timeline.bgm.source, library_id: timeline.bgm.library_id, volume: Number(event.target.value) }, '配乐音量'); }} /></label>
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
