// Comparing two generations of a node, after open-ai-canvas's media versions (MIT, © 2026 ddcat and Open AI Canvas contributors).
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Pause, Play, X } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import type { NodeRun } from './canvasTypes';
import './CanvasCompareDialog.css';

type Kind = 'image' | 'video' | 'audio' | 'text';
type Side = 0 | 1;
interface Measured { width?: number; height?: number; seconds?: number }

const LABELS = ['A', 'B'] as const;
/** How far the second clip may wander from the first before it is pulled back. */
const DRIFT_SECONDS = 0.15;
const SLIDER_STEP = 5;
const MAX_ZOOM = 8;

function kindOf(run: NodeRun): Kind {
  const output = run.output;
  const medium = output?.medium;
  if (medium === 'text' || (output && !output.url && output.text)) return 'text';
  return medium ?? run.medium;
}

function urlOf(run: NodeRun) {
  return run.output?.url ? apiUrl(run.output.url) : '';
}

function when(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function clamp(value: number, low: number, high: number) {
  return Math.min(high, Math.max(low, value));
}

/** Marks the lines that are not part of the longest run of lines both texts share. */
function diffLines(a: string, b: string) {
  const left = a.split('\n');
  const right = b.split('\n');
  const n = left.length;
  const m = right.length;
  const leftChanged = left.map(() => true);
  const rightChanged = right.map(() => true);
  if (n * m > 4_000_000) {
    // Too long to align; compare line by line in place.
    left.forEach((line, index) => {
      if (right[index] === line) leftChanged[index] = rightChanged[index] = false;
    });
  } else {
    const table = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i -= 1) {
      for (let j = m - 1; j >= 0; j -= 1) {
        table[i][j] = left[i] === right[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (left[i] === right[j]) {
        leftChanged[i] = false;
        rightChanged[j] = false;
        i += 1;
        j += 1;
      } else if (table[i + 1][j] >= table[i][j + 1]) i += 1;
      else j += 1;
    }
  }
  return [
    left.map((text, index) => ({ text, changed: leftChanged[index] })),
    right.map((text, index) => ({ text, changed: rightChanged[index] })),
  ] as const;
}

export interface CanvasCompareDialogProps {
  a: NodeRun;
  b: NodeRun;
  /** The run the node shows now; its side says so instead of offering itself. */
  activeId?: string | null;
  /** Called with the chosen run's id. */
  onRestore: (entryId: string) => void;
  onClose: () => void;
}

/** Two generations of one node next to each other, so the better one can be kept. */
export function CanvasCompareDialog({ a, b, activeId, onRestore, onClose }: CanvasCompareDialogProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<'side' | 'slider'>('side');
  const [measured, setMeasured] = useState<[Measured, Measured]>([{}, {}]);
  const runs = [a, b] as const;
  const kinds = [kindOf(a), kindOf(b)] as const;
  const same = kinds[0] === kinds[1] ? kinds[0] : null;

  useEffect(() => { dialog.current?.focus(); }, []);

  const measure = (side: Side, next: Measured) => setMeasured(previous => {
    const copy: [Measured, Measured] = [previous[0], previous[1]];
    copy[side] = { ...previous[side], ...next };
    return copy;
  });

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };

  let body;
  if (same === 'image') body = <ImageCompare runs={runs} mode={mode} onMeasure={measure} />;
  else if (same === 'video') body = <VideoCompare runs={runs} onMeasure={measure} />;
  else if (same === 'audio') body = <AudioCompare runs={runs} onMeasure={measure} />;
  else if (same === 'text') body = <TextCompare runs={runs} />;
  else body = <MixedCompare runs={runs} onMeasure={measure} />;

  return (
    <div className="ccd-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} className="ccd-dialog" role="dialog" aria-modal="true" aria-label={t('对比生成结果')} tabIndex={-1} onKeyDown={onKeyDown}>
        <header className="ccd-head">
          <strong>{t('对比生成结果')}</strong>
          {same === 'image' && (
            <div className="ccd-modes" role="group" aria-label={t('对比方式')}>
              <button type="button" className={`ccd-mode${mode === 'side' ? ' is-on' : ''}`} aria-pressed={mode === 'side'} onClick={() => setMode('side')}>{t('并排')}</button>
              <button type="button" className={`ccd-mode${mode === 'slider' ? ' is-on' : ''}`} aria-pressed={mode === 'slider'} onClick={() => setMode('slider')}>{t('滑块')}</button>
            </div>
          )}
          <button type="button" className="ccd-close" aria-label={t('关闭')} onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <div className="ccd-body">{body}</div>
        <footer className="ccd-foot">
          {runs.map((run, index) => (
            <SideMeta key={LABELS[index]} label={LABELS[index]} run={run} measured={measured[index]} active={run.id === activeId} onRestore={onRestore} />
          ))}
        </footer>
      </div>
    </div>
  );
}

function SideMeta({ label, run, measured, active, onRestore }: {
  label: string; run: NodeRun; measured: Measured; active: boolean; onRestore: (id: string) => void;
}) {
  const seconds = measured.seconds ?? run.request?.requested_seconds;
  const facts = [
    run.model || t('未知模型'),
    when(run.created_at),
    seconds && Number.isFinite(seconds) ? t('{0} 秒', [Number(seconds.toFixed(1))]) : '',
    measured.width && measured.height ? `${measured.width}×${measured.height}` : '',
  ].filter(Boolean);
  return (
    <div className="ccd-meta" data-side={label}>
      <span className="ccd-badge">{label}</span>
      <small>{facts.join(' · ')}</small>
      {active ? (
        <span className="ccd-current">{t('当前')}</span>
      ) : (
        <button type="button" className="cn-button is-primary" aria-label={t('用 {0} 这一版', [label])} onClick={() => onRestore(run.id)}>{t('用这个')}</button>
      )}
    </div>
  );
}

type Runs = readonly [NodeRun, NodeRun];
type OnMeasure = (side: Side, next: Measured) => void;

// ---------------------------------------------------------------- images

function ImageCompare({ runs, mode, onMeasure }: { runs: Runs; mode: 'side' | 'slider'; onMeasure: OnMeasure }) {
  const urls = [urlOf(runs[0]), urlOf(runs[1])];
  const load = (side: Side) => (event: { currentTarget: HTMLImageElement }) =>
    onMeasure(side, { width: event.currentTarget.naturalWidth || undefined, height: event.currentTarget.naturalHeight || undefined });
  return mode === 'slider' ? <ImageSlider urls={urls} load={load} /> : <ImageSideBySide urls={urls} load={load} />;
}

type ImageLoad = (side: Side) => (event: { currentTarget: HTMLImageElement }) => void;

function ImageSideBySide({ urls, load }: { urls: string[]; load: ImageLoad }) {
  const panes = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState({ scale: 1, x: 50, y: 50 });

  useEffect(() => {
    const element = panes.current;
    if (!element) return;
    // A native listener: React's wheel handler is passive and cannot keep the page from scrolling.
    const onWheel = (event: WheelEvent) => {
      const pane = event.target instanceof Element ? event.target.closest('.ccd-zoom') : null;
      if (!pane) return;
      event.preventDefault();
      const rect = pane.getBoundingClientRect();
      const x = rect.width ? clamp(((event.clientX - rect.left) / rect.width) * 100, 0, 100) : 50;
      const y = rect.height ? clamp(((event.clientY - rect.top) / rect.height) * 100, 0, 100) : 50;
      setZoom(previous => ({ scale: clamp(previous.scale * Math.exp(-event.deltaY * 0.0015), 1, MAX_ZOOM), x, y }));
    };
    element.addEventListener('wheel', onWheel, { passive: false });
    return () => element.removeEventListener('wheel', onWheel);
  }, []);

  const style = { transform: `scale(${zoom.scale})`, transformOrigin: `${zoom.x}% ${zoom.y}%` };
  return (
    <div className="ccd-image-side">
      <div className="ccd-panes" ref={panes}>
        {urls.map((url, index) => (
          <figure key={LABELS[index]} className="ccd-pane ccd-zoom" data-side={LABELS[index]}>
            <img src={url} alt={t('{0} 结果', [LABELS[index]])} style={style} draggable={false} onLoad={load(index as Side)} />
            <span className="ccd-corner">{LABELS[index]}</span>
          </figure>
        ))}
      </div>
      <div className="ccd-bar">
        <small>{t('滚轮缩放，两边同步')}</small>
        <button type="button" className="cn-button" disabled={zoom.scale === 1} onClick={() => setZoom({ scale: 1, x: 50, y: 50 })}>
          {t('还原缩放（{0}%）', [Math.round(zoom.scale * 100)])}
        </button>
      </div>
    </div>
  );
}

function ImageSlider({ urls, load }: { urls: string[]; load: ImageLoad }) {
  const stage = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [position, setPosition] = useState(50);

  const follow = (clientX: number) => {
    const rect = stage.current?.getBoundingClientRect();
    if (!rect?.width) return;
    setPosition(clamp(((clientX - rect.left) / rect.width) * 100, 0, 100));
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    follow(event.clientX);
  };
  const stop = () => { dragging.current = false; };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, (value: number) => number> = {
      ArrowLeft: value => value - SLIDER_STEP,
      ArrowDown: value => value - SLIDER_STEP,
      ArrowRight: value => value + SLIDER_STEP,
      ArrowUp: value => value + SLIDER_STEP,
      Home: () => 0,
      End: () => 100,
    };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    event.stopPropagation();
    setPosition(value => clamp(move(value), 0, 100));
  };

  const shown = Math.round(position);
  return (
    <div
      className="ccd-slider-stage" ref={stage}
      onPointerDown={onPointerDown}
      onPointerMove={event => { if (dragging.current) follow(event.clientX); }}
      onPointerUp={stop} onPointerCancel={stop}
    >
      <img className="ccd-slider-img" src={urls[1]} alt={t('{0} 结果', ['B'])} draggable={false} onLoad={load(1)} />
      <img className="ccd-slider-img ccd-slider-over" src={urls[0]} alt={t('{0} 结果', ['A'])} draggable={false} style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }} onLoad={load(0)} />
      <span className="ccd-corner">A</span>
      <span className="ccd-corner is-right">B</span>
      <div
        className="ccd-divider" style={{ left: `${position}%` }}
        role="slider" tabIndex={0}
        aria-label={t('对比分界线')} aria-orientation="horizontal"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={shown} aria-valuetext={t('A 占 {0}%', [shown])}
        onKeyDown={onKeyDown}
      ><span className="ccd-divider-grip" aria-hidden="true" /></div>
    </div>
  );
}

// ---------------------------------------------------------------- video

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function playAll(elements: Array<HTMLMediaElement | null>) {
  for (const element of elements) {
    if (!element || element.ended) continue;
    try {
      void element.play()?.catch(() => {});
    } catch {
      // A browser that refuses playback leaves that side still.
    }
  }
}

function pauseAll(elements: Array<HTMLMediaElement | null>) {
  for (const element of elements) element?.pause();
}

function VideoCompare({ runs, onMeasure }: { runs: Runs; onMeasure: OnMeasure }) {
  const first = useRef<HTMLVideoElement>(null);
  const second = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [durations, setDurations] = useState<[number, number]>([0, 0]);
  const [sound, setSound] = useState<[boolean, boolean]>([false, false]);
  const length = Math.max(durations[0], durations[1]);
  const videos = () => [first.current, second.current];

  const toggle = () => {
    const [lead, follow] = videos();
    if (playing) {
      pauseAll(videos());
      setPlaying(false);
      return;
    }
    if (lead && follow && Math.abs(follow.currentTime - lead.currentTime) > DRIFT_SECONDS && !lead.ended) follow.currentTime = lead.currentTime;
    playAll(videos());
    setPlaying(true);
  };

  const seek = (value: number) => {
    for (const element of videos()) {
      if (!element) continue;
      element.currentTime = Number.isFinite(element.duration) ? Math.min(value, element.duration) : value;
    }
    setTime(value);
  };

  // The first clip leads; once it has ended the second one carries the clock.
  const onTimeUpdate = (side: Side) => {
    const [one, two] = videos();
    const leader = one && one.ended && two && !two.ended ? 1 : 0;
    if (side !== leader) return;
    const lead = side === 0 ? one : two;
    const follow = side === 0 ? two : one;
    if (!lead) return;
    setTime(lead.currentTime);
    if (!follow || follow.ended) return;
    const end = Number.isFinite(follow.duration) ? follow.duration : Infinity;
    if (lead.currentTime < end && Math.abs(follow.currentTime - lead.currentTime) > DRIFT_SECONDS) follow.currentTime = lead.currentTime;
  };

  const onEnded = () => {
    if (videos().every(element => !element || element.ended)) setPlaying(false);
  };

  const onLoaded = (side: Side) => (event: { currentTarget: HTMLVideoElement }) => {
    const element = event.currentTarget;
    const seconds = Number.isFinite(element.duration) ? element.duration : 0;
    setDurations(previous => (side === 0 ? [seconds, previous[1]] : [previous[0], seconds]));
    onMeasure(side, { width: element.videoWidth || undefined, height: element.videoHeight || undefined, seconds: seconds || undefined });
  };

  const refs = [first, second];
  return (
    <div className="ccd-media">
      <div className="ccd-panes">
        {runs.map((run, index) => (
          <figure key={LABELS[index]} className="ccd-pane" data-side={LABELS[index]}>
            <video
              ref={refs[index]} src={urlOf(run)} playsInline preload="metadata" muted={!sound[index]}
              aria-label={t('{0} 结果', [LABELS[index]])}
              onTimeUpdate={() => onTimeUpdate(index as Side)} onEnded={onEnded} onLoadedMetadata={onLoaded(index as Side)}
            />
            <span className="ccd-corner">{LABELS[index]}</span>
            <button
              type="button" className={`ccd-sound${sound[index] ? ' is-on' : ''}`} aria-pressed={sound[index]}
              aria-label={t('{0} 的声音', [LABELS[index]])}
              onClick={() => setSound(previous => (index === 0 ? [!previous[0], previous[1]] : [previous[0], !previous[1]]))}
            >{t('声音')}</button>
          </figure>
        ))}
      </div>
      <div className="ccd-transport">
        <button type="button" className="cn-button" aria-label={playing ? t('同时暂停') : t('同时播放')} onClick={toggle}>
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </button>
        <input
          type="range" className="ccd-scrub" aria-label={t('同步进度')}
          min={0} max={length || 0} step={0.01} value={Math.min(time, length || time)}
          onChange={event => seek(Number(event.target.value))}
        />
        <small className="ccd-clock">{formatTime(time)} / {formatTime(length)}</small>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- audio

function AudioCompare({ runs, onMeasure }: { runs: Runs; onMeasure: OnMeasure }) {
  const first = useRef<HTMLAudioElement>(null);
  const second = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const players = () => [first.current, second.current];
  const refs = [first, second];

  const toggle = () => {
    if (playing) pauseAll(players());
    else playAll(players());
    setPlaying(!playing);
  };

  return (
    <div className="ccd-media">
      <div className="ccd-audio">
        {runs.map((run, index) => (
          <div key={LABELS[index]} className="ccd-audio-row" data-side={LABELS[index]}>
            <span className="ccd-badge">{LABELS[index]}</span>
            <audio
              ref={refs[index]} src={urlOf(run)} controls preload="metadata" aria-label={t('{0} 结果', [LABELS[index]])}
              onEnded={() => { if (players().every(element => !element || element.ended || element.paused)) setPlaying(false); }}
              onLoadedMetadata={event => {
                const seconds = event.currentTarget.duration;
                if (Number.isFinite(seconds) && seconds > 0) onMeasure(index as Side, { seconds });
              }}
            />
          </div>
        ))}
      </div>
      <div className="ccd-transport">
        <button type="button" className="cn-button" aria-label={playing ? t('同时暂停') : t('同时播放')} onClick={toggle}>
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- text

function TextCompare({ runs }: { runs: Runs }) {
  const left = runs[0].output?.text ?? '';
  const right = runs[1].output?.text ?? '';
  const sides = useMemo(() => diffLines(left, right), [left, right]);
  const changed = sides[0].filter(line => line.changed).length + sides[1].filter(line => line.changed).length;
  return (
    <div className="ccd-text">
      <p className="ccd-bar"><small>{changed ? t('有 {0} 行不同', [changed]) : t('两边文字相同')}</small></p>
      <div className="ccd-panes">
        {sides.map((lines, index) => (
          <ol key={LABELS[index]} className="ccd-lines" data-side={LABELS[index]} aria-label={t('{0} 结果', [LABELS[index]])}>
            {lines.map((line, row) => (
              <li key={row} className={line.changed ? 'is-changed' : undefined}>{line.text || ' '}</li>
            ))}
          </ol>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- different kinds

function MixedCompare({ runs, onMeasure }: { runs: Runs; onMeasure: OnMeasure }) {
  return (
    <div className="ccd-panes">
      {runs.map((run, index) => {
        const side = index as Side;
        const label = t('{0} 结果', [LABELS[index]]);
        const kind = kindOf(run);
        const url = urlOf(run);
        let media;
        if (kind === 'text') media = <pre className="ccd-plain">{run.output?.text ?? ''}</pre>;
        else if (kind === 'image') media = <img src={url} alt={label} onLoad={event => onMeasure(side, { width: event.currentTarget.naturalWidth || undefined, height: event.currentTarget.naturalHeight || undefined })} />;
        else if (kind === 'video') media = <video src={url} controls muted preload="metadata" aria-label={label} onLoadedMetadata={event => onMeasure(side, { width: event.currentTarget.videoWidth || undefined, height: event.currentTarget.videoHeight || undefined, seconds: Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : undefined })} />;
        else media = <audio src={url} controls preload="metadata" aria-label={label} />;
        return (
          <figure key={LABELS[index]} className="ccd-pane" data-side={LABELS[index]}>
            {media}
            <span className="ccd-corner">{LABELS[index]}</span>
          </figure>
        );
      })}
    </div>
  );
}
