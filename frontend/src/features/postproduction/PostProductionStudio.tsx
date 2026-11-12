import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clapperboard, Download, FileText, RefreshCcw, Scissors, Sparkles, Wand2, X } from 'lucide-react';

import { ApiError, apiRequest } from '../../api/client';
import { getLocale, t } from '../../i18n';
import { DeliveryChecklist } from '../workbench/DeliveryChecklist';
import { mediaUrlOf, spokenText } from '../workbench/stageSix';
import type { BgmTrack } from '../workbench/TimelinePanel';
import {
  audioSourceOf, clipKey, clipRef, DEFAULT_SETTINGS, formatBytes, formatDuration, rowAt,
  type AudioSource, type SettingKey, type SoundRecord, type StudioClip, type StudioResponse,
} from './postProduction';
import { StudioSidebar } from './StudioSidebar';
import './PostProductionStudio.css';

const TimelinePanel = lazy(() => import('../workbench/TimelinePanel').then(module => ({ default: module.TimelinePanel })));

const SOURCE_LABELS: Record<AudioSource, string> = { native: '原声', tts: '配音', none: '无人声' };
const SOURCE_HINTS: Record<AudioSource, string> = {
  native: '用视频模型生成时自带的声音，口型和台词对得上',
  tts: '用配音替换，口型可能对不上',
  none: '这一镜不出人声',
};

/** When a version was rendered, in the viewer's own time zone. */
function renderedAt(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso : when.toLocaleString(getLocale(), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

interface Props {
  taskId: string;
  /** The current film, if stage 7 made one. */
  filmUrl?: string | null;
  /** Changes whenever the film is rendered again, so the player reloads the same path. */
  filmKey: string;
  episode?: number | null;
  sound?: SoundRecord | null;
  /** The project's audio model: music is generated only when it is ElevenLabs. */
  audioModel?: string;
  /** Something about the project changed upstream (a stage ran): read the timeline again. */
  refreshKey?: string;
  /** A stage of this page is running: buttons that would start another wait. */
  running?: boolean;
  /** Films still carrying a character's old voice after a voice change (0 = the one-run film). */
  voiceRerender?: number[];
  onRegenerateSound: () => void;
  onCompose: () => void;
  onRendered: () => void;
}

/** 剪辑合成师: one page for the sound and the final cut, like a post-production bay. */
export function PostProductionStudio({
  taskId, filmUrl, filmKey, episode, sound, audioModel = '', refreshKey = '', running = false, voiceRerender = [],
  onRegenerateSound, onCompose, onRendered,
}: Props) {
  const [data, setData] = useState<StudioResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [version, setVersion] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [editRoom, setEditRoom] = useState(false);
  const [prompts, setPrompts] = useState(false);
  const player = useRef<HTMLVideoElement | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await apiRequest<StudioResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline`);
      if (!result?.timeline?.clips) throw new Error(t('时间线读取失败'));
      setData(result);
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('时间线读取失败'));
    }
  }, [taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load, refreshKey, filmKey]);

  const operate = useCallback(async (body: Record<string, unknown>, label: string) => {
    setBusy(label);
    setNotice('');
    try {
      setData(await apiRequest<StudioResponse>(`/api/drama/${encodeURIComponent(taskId)}/timeline/ops`, { method: 'POST', body: JSON.stringify(body) }));
      setNotice(t('{0}已更新，重新合成后生效。', [label]));
      return true;
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : t('{0}失败', [label]));
      return false;
    } finally {
      setBusy('');
    }
  }, [taskId]);

  const render = useCallback(async (target?: number) => {
    setBusy(target ? `render:${target}` : 'render');
    setNotice('');
    try {
      await apiRequest<{ final_video_url: string }>(`/api/drama/${encodeURIComponent(taskId)}/timeline/render`, {
        method: 'POST', body: JSON.stringify(target ? { episode: target } : {}),
      });
      setNotice(target ? t('已重新合成第 {0} 集。', [target]) : t('已重新合成成片。'));
      setVersion('');
      onRendered();
      await load();
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : t('合成失败'));
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
      form.append('name', file.name.replace(/\.[^.]+$/, ''));
      const track = await apiRequest<BgmTrack>('/api/library/bgm', { method: 'POST', body: form });
      setBusy('');
      await operate({ operation: 'bgm', source: 'library', library_id: track.id }, t('配乐'));
    } catch (caught) {
      setNotice(caught instanceof ApiError ? caught.message : t('配乐上传失败'));
      setBusy('');
    }
  }, [operate]);

  const post = data?.post;
  const clips = useMemo(() => data?.timeline.clips ?? [], [data]);
  const shots = useMemo(() => new Map((post?.shots ?? []).map(shot => [shot.shot_uid, shot])), [post]);
  const draftClips = clips.filter(clip => clip.review.decision !== 'rejected' && shots.get(clip.shot_uid ?? null)?.draft);

  const upscale = useCallback(async () => {
    if (!draftClips.length) return;
    if (!window.confirm(t('把 {0} 个样片镜头在本机放大成高清？不调用付费模型，放大后需要重新合成。', [draftClips.length]))) return;
    setBusy('hd');
    setNotice('');
    let done = 0;
    try {
      for (const clip of draftClips) {
        const query = new URLSearchParams({ ...(clip.scene_id ? { scene_id: clip.scene_id } : {}), ...(clip.shot_uid ? { shot_uid: String(clip.shot_uid) } : {}) });
        await apiRequest(`/api/drama/${encodeURIComponent(taskId)}/shots/${clip.shot_id}/hd?${query}`, { method: 'POST', body: JSON.stringify({ mode: 'upscale' }) });
        done += 1;
      }
      setNotice(t('已放大 {0} 个镜头，重新合成后成片用高清片段。', [done]));
    } catch (caught) {
      setNotice(t('放大到第 {0} 个镜头时失败：{1}', [done + 1, caught instanceof Error ? caught.message : '']));
    } finally {
      setBusy('');
      await load();
    }
  }, [draftClips, load, taskId]);

  if (error) return <p className="pp-empty" role="status">{error}</p>;
  if (!data) return <p className="pp-empty">{t('正在读取剪辑时间线…')}</p>;

  const { timeline, summary } = data;
  const settings = post?.settings ?? DEFAULT_SETTINGS;
  const tension = post?.tension ?? [];
  const versions = post?.film_versions ?? [];
  const playing = version || filmUrl || '';
  const current = rowAt(tension, playhead);
  const currentClip = current ? clips.find(clip => clipKey(clip) === (current.shot_uid ?? current.shot_id)) : undefined;
  const chosen = clips.find(clip => clipKey(clip) === selected) ?? null;
  const sources = summary.audio_sources;
  const sizeBytes = versions.find(item => item.url === playing)?.bytes ?? post?.estimated_bytes ?? 0;
  const sizeIsEstimate = !versions.find(item => item.url === playing)?.bytes;
  const episodeLabel = episode ?? timeline.episode;

  const seek = (clip: StudioClip) => {
    setSelected(clipKey(clip));
    const row = tension.find(item => (item.shot_uid ?? item.shot_id) === clipKey(clip));
    if (row && player.current) {
      player.current.currentTime = row.t + 0.05;
      setPlayhead(row.t);
    }
  };

  const setSource = (clip: StudioClip, source: AudioSource) =>
    void operate({ operation: 'audio_source', ...clipRef(clip), audio_source: source }, t('人声来源'));

  const regenerate = () => {
    if (!window.confirm(t('重新生成配音、音效和配乐，然后重新合成成片？原声镜头不会重新配音；配了 ElevenLabs 时会产生音频费用。剪辑台上的修剪和选的配乐会保留。'))) return;
    onRegenerateSound();
  };

  return (
    <section className="pp" aria-label={t('剪辑合成师')}>
      <header className="pp-head">
        <div className="pp-head__title">
          <Clapperboard aria-hidden="true" />
          <h3>{t('后期制作')}{episodeLabel ? ` · ${t('第 {0} 集', [episodeLabel])}` : ''}</h3>
          <span className="pp-chip">{t('{0} 个镜头', [summary.included])}</span>
          {sources && (
            <span className="pp-chip pp-chip--sound" title={t('视频模型出了声的镜头直接用原声，没出声的才配音')}>
              {t('原声 {0} · 配音 {1} · 无人声 {2}', [sources.native ?? 0, sources.tts ?? 0, sources.none ?? 0])}
            </span>
          )}
        </div>
        <div className="pp-head__actions">
          <button type="button" className={editRoom ? 'is-on' : ''} aria-pressed={editRoom} onClick={() => setEditRoom(open => !open)}>
            <Scissors aria-hidden="true" /> {t('剪辑室')}
          </button>
          <button type="button" onClick={() => setPrompts(true)}><FileText aria-hidden="true" /> {t('查看提示词')}</button>
          <button type="button" className="is-primary" disabled={running || busy !== ''} onClick={regenerate}>
            <Wand2 aria-hidden="true" /> {t('一键重新生成音效配乐')}
          </button>
        </div>
      </header>

      {notice && <p className="pp-notice" role="status">{notice}</p>}

      {voiceRerender.length > 0 && (
        <div className="pp-alert" role="group" aria-label={t('换了音色，要重新合成的成片')}>
          <p>{t('换了角色的声音：下面这些成片里还是旧声音，重新合成后才会换成新的。')}</p>
          <div className="pp-row">
            {voiceRerender.map(number => (
              <button key={number} type="button" disabled={busy !== '' || running}
                onClick={() => { void render(number && number !== (episode ?? timeline.episode) ? number : undefined); }}>
                <RefreshCcw aria-hidden="true" /> {busy === `render:${number}` ? t('合成中…') : number ? t('重新合成第 {0} 集', [number]) : t('重新合成成片')}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="pp-body">
        <div className="pp-main">
          <div className="pp-toolbar">
            <label className="pp-version">
              <span>{t('版本')}</span>
              <select value={playing} aria-label={t('成片版本')} onChange={event => setVersion(event.target.value === filmUrl ? '' : event.target.value)} disabled={!versions.length && !filmUrl}>
                {filmUrl && !versions.some(item => item.url === filmUrl) && <option value={filmUrl}>{t('当前成片')}</option>}
                {versions.map((item, index) => (
                  <option key={item.url} value={item.url}>
                    {`V${versions.length - index}`}{item.url === filmUrl ? ` · ${t('当前')}` : ''}{item.rendered_at ? ` · ${renderedAt(item.rendered_at)}` : ''}{item.seconds ? ` · ${formatDuration(item.seconds)}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <span className="pp-toolbar__spacer" />
            <button type="button" disabled={!draftClips.length || busy !== '' || running} onClick={() => { void upscale(); }}
              title={draftClips.length ? t('{0} 个镜头还是样片分辨率', [draftClips.length]) : t('所有镜头都已是高清')}>
              <Sparkles aria-hidden="true" /> {busy === 'hd' ? t('放大中…') : t('生成高清片段')}{draftClips.length ? ` (${draftClips.length})` : ''}
            </button>
            {playing
              ? <a className="pp-download" href={playing} download><Download aria-hidden="true" /> {t('下载视频')}</a>
              : <span className="pp-download is-disabled" aria-disabled="true"><Download aria-hidden="true" /> {t('下载视频')}</span>}
          </div>

          <div className="pp-stage">
            {playing ? (
              <video
                key={`${playing}:${filmKey}`} ref={player} src={playing} controls playsInline
                onTimeUpdate={event => setPlayhead(event.currentTarget.currentTime)}
              />
            ) : (
              <div className="pp-stage__empty">
                <p>{running ? t('剪辑合成师正在合成，完成后在这里播放。') : t('声音已经做好，成片还没合成。')}</p>
                {!running && <button type="button" className="is-primary" onClick={onCompose}><Clapperboard aria-hidden="true" /> {t('合成成片')}</button>}
              </div>
            )}
          </div>
          <p className="pp-caption" aria-live="polite">
            {currentClip?.subtitle ? <><b>{currentClip.scene_id ? `${currentClip.scene_id} · ` : ''}{t('镜头 {0}', [currentClip.shot_id])}</b> {currentClip.subtitle}</> : <span>{t('播放时这里显示当前镜头的台词。')}</span>}
          </p>

          <ol className="pp-strip" aria-label={t('镜头胶片条')}>
            {clips.map((clip, index) => {
              const shot = shots.get(clip.shot_uid ?? null);
              const source = audioSourceOf(clip);
              const rejected = clip.review.decision === 'rejected';
              const sceneStart = index === 0 || clips[index - 1].scene_id !== clip.scene_id;
              const active = current && (current.shot_uid ?? current.shot_id) === clipKey(clip);
              return (
                <li key={clipKey(clip)} className={[sceneStart ? 'is-scene-start' : '', rejected ? 'is-rejected' : '', selected === clipKey(clip) ? 'is-selected' : '', active ? 'is-playing' : ''].filter(Boolean).join(' ')}>
                  {sceneStart && clip.scene_id && <span className="pp-strip__scene">{clip.scene_id}</span>}
                  <button type="button" onClick={() => seek(clip)}
                    aria-label={t('{0} 镜头 {1}，{2}', [clip.scene_id ?? '', clip.shot_id, rejected ? t('已打回') : t(SOURCE_LABELS[source])])}>
                    {shot?.image_url ? <img src={mediaUrlOf(shot.image_url)} alt="" loading="lazy" /> : <span className="pp-strip__blank">{clip.shot_id}</span>}
                    <i className={`pp-dot is-${rejected ? 'rejected' : source}`} aria-hidden="true" />
                    {shot?.draft && <em className="pp-strip__draft">{t('样片')}</em>}
                    <span className="pp-strip__num">{clip.shot_id}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="pp-legend">
            <i className="pp-dot is-native" /> {t('原声')} <i className="pp-dot is-tts" /> {t('配音')} <i className="pp-dot is-none" /> {t('无人声')} <i className="pp-dot is-rejected" /> {t('已打回')}
          </p>

          {chosen && (
            <div className="pp-shot" role="group" aria-label={t('镜头 {0} 的人声', [chosen.shot_id])}>
              <strong>{chosen.scene_id ? `${chosen.scene_id} · ` : ''}{t('镜头 {0}', [chosen.shot_id])}</strong>
              <div className="pp-segment" role="radiogroup" aria-label={t('人声来源')}>
                {(['native', 'tts', 'none'] as AudioSource[]).map(source => {
                  const unavailable = source === 'native' && !chosen.native_available;
                  return (
                    <button key={source} type="button" role="radio" aria-checked={audioSourceOf(chosen) === source}
                      disabled={busy !== '' || unavailable} title={unavailable ? t('这一镜的片段没有原声') : t(SOURCE_HINTS[source])}
                      onClick={() => setSource(chosen, source)}>
                      {t(SOURCE_LABELS[source])}
                    </button>
                  );
                })}
              </div>
              {audioSourceOf(chosen) === 'tts' && chosen.voice_path && <audio controls src={mediaUrlOf(chosen.voice_path)} aria-label={t('这一镜的配音')} />}
              {audioSourceOf(chosen) === 'tts' && !chosen.voice_path && <small>{t('还没配过音，重新合成时补配。')}</small>}
              {audioSourceOf(chosen) === 'tts' && chosen.native_available && <small className="pp-warn">{t('配音的口型可能和画面对不上。')}</small>}
              <button type="button" className="pp-icon" aria-label={t('关闭')} onClick={() => setSelected(null)}><X aria-hidden="true" /></button>
            </div>
          )}

          <DeliveryChecklist<StudioResponse> issues={data.acceptance ?? []} taskId={taskId} onTimeline={setData} />
        </div>

        <StudioSidebar
          timeline={timeline} settings={settings} library={data.bgm_library} tension={tension} markers={post?.scene_markers ?? []}
          seconds={summary.seconds} playhead={playhead} busy={busy}
          musicModel={/eleven/i.test(audioModel) ? 'ElevenLabs Music' : t('未配置配乐模型（只用配乐库）')}
          generatedMusic={sound?.bgm_url ?? null}
          musicVersions={post?.music_versions ?? []}
          onSetting={(key: SettingKey, value: boolean) => { void operate({ operation: 'settings', settings: { [key]: value } }, t('基础设定')); }}
          onBgm={(body, label) => { void operate(body, label); }}
          onUpload={file => { void uploadBgm(file); }}
        />
      </div>

      <footer className="pp-foot">
        <span>{t('时长')} <b>{formatDuration(summary.seconds)}</b></span>
        <span>{sizeIsEstimate ? t('大小（预估）') : t('大小')} <b>{formatBytes(sizeBytes)}</b></span>
        <button type="button" className="is-primary" disabled={busy !== '' || running || !summary.included} onClick={() => { void render(); }}>
          <RefreshCcw aria-hidden="true" /> {busy === 'render' ? t('合成中…') : t('重新合成')}
        </button>
      </footer>

      {editRoom && (
        <section className="pp-room" aria-label={t('剪辑室')}>
          <Suspense fallback={<p className="pp-empty">{t('正在打开剪辑室…')}</p>}>
            <TimelinePanel taskId={taskId} onRendered={() => { onRendered(); void load(); }} />
          </Suspense>
        </section>
      )}

      {/* 页面是尺寸容器，fixed 定位会相对它而不是视口：对话框挂到 body 上。 */}
      {prompts && createPortal(
        <div className="pp-dialog" role="dialog" aria-modal="true" aria-label={t('提示词')}
          onKeyDown={event => { if (event.key === 'Escape') setPrompts(false); }}
          onClick={event => { if (event.target === event.currentTarget) setPrompts(false); }}>
          <div className="pp-dialog__panel">
            <header>
              <h4>{t('提示词')}</h4>
              <button type="button" className="pp-icon" aria-label={t('关闭')} autoFocus onClick={() => setPrompts(false)}><X aria-hidden="true" /></button>
            </header>
            <p className="pp-muted">{t('原声镜头的台词和声音写在第 5 步的视频提示词里，由视频模型一起生成；这里是配乐、环境音和配音用的。')}</p>
            <h5>{t('配乐')}</h5>
            <pre>{sound?.music_prompt || t('这一轮没有调用配乐模型。')}</pre>
            <h5>{t('环境音')}</h5>
            <pre>{sound?.ambience_prompt || t('这一轮没有生成环境音（原声里已经有了，或没配音频模型）。')}</pre>
            <h5>{t('配音')} {sound?.voice_profile ? <small>{sound.voice_profile}</small> : null}</h5>
            {sound?.dialogue_directions?.length ? (
              <ul className="pp-lines">
                {sound.dialogue_directions.map((line, index) => (
                  <li key={`${line.shot_id}-${index}`}><b>{t('镜头 {0}', [line.shot_id])}</b> <span>{line.speaker}</span> {spokenText(line.verbatim_text ?? '')} {line.emotion ? <em>{line.emotion}</em> : null}</li>
                ))}
              </ul>
            ) : <p className="pp-muted">{t('没有需要配音的台词。')}</p>}
          </div>
        </div>,
        document.body,
      )}
    </section>
  );
}
