import { Download, Pause, Play, SkipBack, X } from 'lucide-react';

import { clockText, sceneDuration, sceneTimeOf, type SceneSegment } from '../lib/monitors';
import { PLAYBACK_SPEEDS } from '../useDeskPlayback';

interface Props {
  segments: SceneSegment[];
  shotId: number | null;
  /** The playhead inside the current shot. */
  time: number;
  playing: boolean;
  /** 1 is real time. */
  speed: number;
  onSpeed: (speed: number) => void;
  onPlay: () => void;
  onPause: () => void;
  /** A point on the scene's clock: the desk finds the shot it falls in. */
  onSeek: (sceneTime: number) => void;
  /** 0…1 while the whole scene is being written out as one video; `null` otherwise. */
  exportProgress?: number | null;
  /** Why the scene cannot be exported right now; '' when it can. */
  exportRefusal?: string;
  onExport?: () => void;
  onCancelExport?: () => void;
}

/** The 成片预演 transport: the whole scene as one strip, shot after shot, the way the cut will run. */
export function ScenePlayer({ segments, shotId, time, playing, speed, onSpeed, onPlay, onPause, onSeek, exportProgress = null, exportRefusal = '', onExport, onCancelExport }: Props) {
  const exporting = exportProgress !== null;
  const total = sceneDuration(segments);
  const now = sceneTimeOf(segments, shotId, time);
  const current = segments.find(segment => segment.shotId === shotId);
  return (
    <section className="desk-scene-player" aria-label="成片预演播放">
      <div className="desk-scene-player__controls">
        <button type="button" className="desk-icon" aria-label={playing ? '暂停' : '播放'} title={playing ? '暂停（空格）' : '播放（空格）'} disabled={exporting} onClick={playing ? onPause : onPlay}>
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </button>
        <button type="button" className="desk-icon" aria-label="回到开头" title="回到本场开头" disabled={exporting} onClick={() => onSeek(0)}><SkipBack aria-hidden="true" /></button>
        <select className="desk-timeline__speed" aria-label="播放速度" title="播放速度" value={speed} onChange={event => onSpeed(Number(event.target.value))}>
          {PLAYBACK_SPEEDS.map(item => <option key={item} value={item}>{item}×</option>)}
        </select>
        <span className="desk-scene-player__clock" aria-label="成片时间">{clockText(now)} / {clockText(total)}</span>
        <span className="desk-scene-player__shot" role="status">{current?.title ?? ''}</span>
        {onExport && !exporting && (
          <button
            type="button" className="desk-button desk-scene-player__export" disabled={Boolean(exportRefusal)} onClick={onExport}
            title={exportRefusal || '把本场所有镜头按顺序、透过各镜机位连成一条视频，保存到本机'}
          ><Download aria-hidden="true" /> 导出成片预演</button>
        )}
        {exporting && (
          <span className="desk-scene-player__exporting" role="group" aria-label="成片预演导出进度">
            <progress aria-label="成片预演导出进度" value={exportProgress} max={1} />
            <span>{Math.round(exportProgress * 100)}%</span>
            <button type="button" className="desk-icon" aria-label="取消导出" title="取消导出" onClick={onCancelExport}><X aria-hidden="true" /></button>
          </span>
        )}
      </div>
      <div className="desk-scene-player__strip" role="group" aria-label="本场镜头">
        {segments.map(segment => (
          <button
            key={segment.shotId} type="button" aria-current={segment.shotId === shotId ? 'true' : undefined}
            className={segment.shotId === shotId ? 'is-current' : ''} style={{ flexGrow: Math.max(segment.duration, 0.01) }}
            title={`${segment.title} · ${segment.duration.toFixed(1)} 秒`} aria-label={`跳到${segment.title}`} disabled={exporting} onClick={() => onSeek(segment.start)}
          >{segment.shotId}</button>
        ))}
      </div>
      <input
        type="range" className="desk-scene-player__scrub" aria-label="成片进度" min={0} max={total || 0} step={0.01} value={Math.min(now, total)}
        aria-valuetext={`${clockText(now)} / ${clockText(total)}`} disabled={exporting} onChange={event => onSeek(Number(event.target.value))}
      />
    </section>
  );
}
