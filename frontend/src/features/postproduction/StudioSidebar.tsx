import { useRef, useState } from 'react';
import { Music, Pause, Play, Trash2, Upload } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { mediaUrlOf } from '../workbench/stageSix';
import {
  curvePoints, formatDuration, percentOf, SETTING_KEYS,
  type MusicVersion, type PostSettings, type SceneMarker, type SettingKey, type StudioTimeline, type StudioTrack, type TensionRow,
} from './postProduction';

const SETTING_LABELS: Record<SettingKey, [string, string]> = {
  transitions: ['场景转场', '关掉后镜头之间一律硬切'],
  dialogue: ['对白音轨', '关掉后成片里没有人声，只留配乐'],
  subtitles: ['嵌入字幕', '台词烧进画面'],
  title_card: ['片名卡与首尾淡入淡出', '片头标题卡，开头淡入、结尾淡出'],
};

const CURVE_W = 300;
const CURVE_H = 72;

interface Props {
  timeline: StudioTimeline;
  settings: PostSettings;
  library: StudioTrack[];
  tension: TensionRow[];
  markers: SceneMarker[];
  seconds: number;
  playhead: number;
  busy: string;
  musicModel: string;
  generatedMusic: string | null;
  musicVersions: MusicVersion[];
  onSetting: (key: SettingKey, value: boolean) => void;
  onBgm: (body: Record<string, unknown>, label: string) => void;
  onUpload: (file: File) => void;
}

/** The right column: the four basic switches, the music bed and where it comes in, and the tension curve. */
export function StudioSidebar({
  timeline, settings, library, tension, markers, seconds, playhead, busy, musicModel, generatedMusic, musicVersions,
  onSetting, onBgm, onUpload,
}: Props) {
  const versions = musicVersions.filter(item => item.url);
  const audio = useRef<HTMLAudioElement | null>(null);
  const upload = useRef<HTMLInputElement | null>(null);
  const [playing, setPlaying] = useState('');
  const [startDraft, setStartDraft] = useState<number | null>(null);
  const [volumeDraft, setVolumeDraft] = useState<number | null>(null);
  const bgm = timeline.bgm;
  const start = startDraft ?? bgm.start ?? 0;
  const volume = volumeDraft ?? bgm.volume;
  const currentName = bgm.source === 'none' ? t('无配乐') : bgm.name || (bgm.source === 'generated' ? t('阶段 6 生成') : t('配乐'));
  const currentUrl = bgm.source === 'library' && bgm.library_id
    ? apiUrl(`/api/library/bgm/${encodeURIComponent(bgm.library_id)}/audio`)
    : bgm.url ? mediaUrlOf(bgm.url) : '';

  const toggle = (id: string, url: string) => {
    const element = audio.current;
    if (!element) return;
    if (playing === id) {
      element.pause();
      setPlaying('');
      return;
    }
    element.src = url;
    void element.play()?.catch(() => setPlaying(''));
    setPlaying(id);
  };

  const commitStart = () => {
    if (startDraft === null) return;
    if (startDraft !== (bgm.start ?? 0)) onBgm({ operation: 'bgm', bgm_start: startDraft }, t('音乐定位'));
    setStartDraft(null);
  };
  const commitVolume = () => {
    if (volumeDraft === null) return;
    if (volumeDraft !== bgm.volume) onBgm({ operation: 'bgm', volume: volumeDraft }, t('配乐音量'));
    setVolumeDraft(null);
  };

  const points = curvePoints(tension, seconds, CURVE_W, CURVE_H);
  const peak = tension.reduce<TensionRow | null>((best, row) => (!best || row.tension > best.tension ? row : best), null);

  return (
    <aside className="pp-side" aria-label={t('合成设定')}>
      <section className="pp-card" aria-labelledby="pp-basic">
        <h4 id="pp-basic">{t('基础设定')}</h4>
        <ul className="pp-switches">
          {SETTING_KEYS.map(key => (
            <li key={key}>
              <span>
                <strong>{t(SETTING_LABELS[key][0])}</strong>
                <small>{t(SETTING_LABELS[key][1])}</small>
              </span>
              <button
                type="button" role="switch" aria-checked={settings[key]} aria-label={t(SETTING_LABELS[key][0])}
                className="pp-switch" disabled={busy !== ''} onClick={() => onSetting(key, !settings[key])}
              ><i aria-hidden="true" /></button>
            </li>
          ))}
        </ul>
      </section>

      <section className="pp-card" aria-labelledby="pp-bgm">
        <h4 id="pp-bgm"><Music aria-hidden="true" /> {t('氛围音乐（BGM）')}</h4>
        <div className="pp-now">
          <button type="button" className="pp-icon" disabled={!currentUrl} aria-label={playing === 'current' ? t('暂停当前配乐') : t('试听当前配乐')}
            onClick={() => toggle('current', currentUrl)}>
            {playing === 'current' ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>
          <span className="pp-now__name">
            <strong>{currentName}</strong>
            <small>{bgm.source === 'library' ? t('来自配乐库') : bgm.source === 'generated' ? musicModel : t('成片里没有配乐')}</small>
          </span>
          <button type="button" className="pp-icon" disabled={busy !== '' || bgm.source === 'none'} aria-label={t('去掉配乐')}
            onClick={() => onBgm({ operation: 'bgm', source: 'none' }, t('配乐'))}>
            <Trash2 aria-hidden="true" />
          </button>
        </div>
        <div className="pp-row">
          {versions.length > 0 && (
            <select aria-label={t('配乐版本')} disabled={busy !== ''}
              value={bgm.source === 'generated' && versions.some(item => item.url === bgm.url) ? String(bgm.url) : ''}
              onChange={event => { if (event.target.value) onBgm({ operation: 'bgm', source: 'generated', music_version: event.target.value }, t('配乐')); }}>
              <option value="">{t('生成的配乐版本')}</option>
              {versions.map((item, index) => (
                <option key={String(item.url)} value={String(item.url)}>
                  {t('生成 V{0}', [versions.length - index])}{item.episode ? ` · ${t('第 {0} 集', [item.episode])}` : ''}
                </option>
              ))}
            </select>
          )}
          {!versions.length && generatedMusic && bgm.source !== 'generated' && (
            <button type="button" className="pp-ghost" disabled={busy !== ''} onClick={() => onBgm({ operation: 'bgm', source: 'generated' }, t('配乐'))}>
              {t('用回生成的配乐')}
            </button>
          )}
          <button type="button" className="pp-ghost" disabled={busy !== ''} onClick={() => upload.current?.click()}>
            <Upload aria-hidden="true" /> {busy === 'upload' ? t('上传中…') : t('自定义上传')}
          </button>
          <input ref={upload} type="file" accept="audio/*" hidden aria-label={t('上传配乐文件')}
            onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onUpload(file); }} />
        </div>
        <label className="pp-slider">
          <span>{t('音量')} <b>{Math.round(volume * 100)}%</b></span>
          <input type="range" min={0} max={1} step={0.02} value={volume} disabled={bgm.source === 'none'} aria-label={t('配乐音量')}
            onChange={event => setVolumeDraft(Number(event.target.value))} onPointerUp={commitVolume} onKeyUp={commitVolume} onBlur={commitVolume} />
        </label>

        <div className="pp-library">
          <h5>{t('配乐库推荐')}</h5>
          {library.length === 0 ? <p className="pp-muted">{t('配乐库还是空的，可以先自定义上传一首。')}</p> : (
            <ul aria-label={t('配乐库推荐')}>
              {library.slice(0, 6).map(track => {
                const inUse = bgm.source === 'library' && bgm.library_id === track.id;
                return (
                  <li key={track.id} className={inUse ? 'is-active' : ''}>
                    <button type="button" className="pp-icon" aria-label={t('试听 {0}', [track.name])}
                      onClick={() => toggle(track.id, apiUrl(`/api/library/bgm/${encodeURIComponent(track.id)}/audio`))}>
                      {playing === track.id ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
                    </button>
                    <span className="pp-track">
                      <strong>{track.name}</strong>
                      <span className="pp-tags">
                        {track.match !== undefined && <b>{t('匹配度 {0}%', [Math.round(track.match * 100)])}</b>}
                        {(track.tags ?? []).map(tag => <em key={tag}>{tag}</em>)}
                      </span>
                    </span>
                    <button type="button" className="pp-ghost" disabled={busy !== '' || inUse}
                      onClick={() => onBgm({ operation: 'bgm', source: 'library', library_id: track.id }, t('配乐'))}>
                      {inUse ? t('使用中') : t('换上')}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <p className="pp-model"><span>{t('配乐模型')}</span><b>{musicModel}</b></p>

        <div className="pp-slider pp-placement">
          <span>{t('音乐定位')} <b>{t('从 {0} 进', [formatDuration(start)])}</b></span>
          <input type="range" min={0} max={Math.max(1, Math.floor(seconds))} step={0.5} value={start} disabled={bgm.source === 'none'}
            aria-label={t('音乐定位')} onChange={event => setStartDraft(Number(event.target.value))}
            onPointerUp={commitStart} onKeyUp={commitStart} onBlur={commitStart} />
          <ol className="pp-markers" aria-label={t('场景标记')}>
            {markers.map(marker => (
              <li key={`${marker.scene_id}-${marker.t}`} style={{ left: `${percentOf(marker.t, seconds)}%` }} title={marker.scene_id}>
                <span>{marker.scene_id}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="pp-card" aria-labelledby="pp-curve">
        <h4 id="pp-curve">{t('情绪张力曲线')}</h4>
        {points ? (
          <svg className="pp-curve" viewBox={`0 0 ${CURVE_W} ${CURVE_H}`} preserveAspectRatio="none" role="img"
            aria-label={peak ? t('张力最高在 {0}（{1}）', [formatDuration(peak.t), peak.scene_id]) : t('情绪张力曲线')}>
            <polygon points={`0,${CURVE_H} ${points} ${CURVE_W},${CURVE_H}`} className="pp-curve__fill" />
            <polyline points={points} className="pp-curve__line" />
            {bgm.source !== 'none' && <line className="pp-curve__music" x1={(percentOf(start, seconds) / 100) * CURVE_W} x2={(percentOf(start, seconds) / 100) * CURVE_W} y1={0} y2={CURVE_H} />}
            <line className="pp-curve__playhead" x1={(percentOf(playhead, seconds) / 100) * CURVE_W} x2={(percentOf(playhead, seconds) / 100) * CURVE_W} y1={0} y2={CURVE_H} />
          </svg>
        ) : <p className="pp-muted">{t('成片里还没有镜头。')}</p>}
        <p className="pp-legend"><i className="is-music" /> {t('配乐进入')} <i className="is-playhead" /> {t('播放位置')}</p>
      </section>
      <audio ref={audio} hidden onEnded={() => setPlaying('')} />
    </aside>
  );
}
