import { useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import {
  ChevronDown, ChevronUp, ClipboardPaste, Copy, Diamond, Film, Pause, Play, Repeat, SkipBack, SkipForward, Square, Trash2,
} from 'lucide-react';

import { actorsInShot, type ActorKey, type StageEasing, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import {
  AMPLITUDE_RANGE, ANGLE_RANGE, CAMERA_MOVES, DEFAULT_MOVE_ANGLE, MOVE_EASINGS, SIDE_LABELS, cameraMove, type MoveSide,
} from '../lib/cameraMoves';
import { FRAME_RATES, cameraKeysOf, frameCount, frameOf, sampleActor, sampleShot, timeOfFrame, timelineOf } from '../lib/sampling';
import {
  DURATION_RANGE, EASING_LABELS, MAX_TRACK_KEYS, actorKeyAt, cameraKeyAt, durationRefusal, keyIndexAtFrame, keysOf, removeKey, retimeKey,
  trackKey, trackLabel, trackOperation, upsertKey, type TimelineKey, type TrackRef,
} from '../lib/timelineEdits';
import type { DeskPlayback } from '../useDeskPlayback';

interface Props {
  /** The plan as stored (unconfirmed edits included): what the keys are read from and written to. */
  plan: StagePlan;
  shot?: StageShot;
  playback: DeskPlayback;
  selection: SelectionRef[];
  editable: boolean;
  collapsed: boolean;
  onCollapsed: (collapsed: boolean) => void;
  onCommit: (request: EditRequest) => void;
  onSelect: (ref: SelectionRef, additive: boolean) => void;
}

interface KeyRef { track: TrackRef; index: number }

function timecode(frame: number, fps: number): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  const seconds = Math.floor(frame / fps);
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}:${pad(frame % fps)}`;
}

function sameTrack(a: TrackRef, b: TrackRef) {
  return trackKey(a) === trackKey(b);
}

export function TimelinePanel({ plan, shot, playback, selection, editable, collapsed, onCollapsed, onCommit, onSelect }: Props) {
  const timeline = useMemo(() => timelineOf(plan, shot?.shot_id), [plan, shot]);
  const { duration_s: durationS, fps } = timeline;
  const frames = frameCount(durationS, fps);
  const [picked, setPicked] = useState<KeyRef | null>(null);
  const [clipboard, setClipboard] = useState<{ kind: TrackRef['kind']; key: TimelineKey } | null>(null);
  const [message, setMessage] = useState('');
  const [movesOpen, setMovesOpen] = useState(false);
  const [move, setMove] = useState<{ preset: string; amplitude: number; angle: number; side: MoveSide; easing: StageEasing | '' }>(
    { preset: 'push', amplitude: 1, angle: DEFAULT_MOVE_ANGLE, side: 'auto', easing: '' },
  );
  // The key being dragged: drawn at `time` until it is let go, then written once.
  const [dragged, setDragged] = useState<(KeyRef & { time: number }) | null>(null);
  const drag = useRef<{ key: KeyRef; lane: HTMLElement; startX: number; moved: boolean } | null>(null);

  const primary = selection[selection.length - 1];
  const selectedActor = primary?.kind === 'actor' ? primary.name : '';
  const cast = useMemo(() => actorsInShot(plan, shot), [plan, shot]);
  const tracks = useMemo<TrackRef[]>(() => {
    const names = cast.filter(actor => timeline.actors[actor.name]?.length || actor.name === selectedActor).map(actor => actor.name);
    return [{ kind: 'camera' }, ...names.map(name => ({ kind: 'actor' as const, name }))];
  }, [cast, selectedActor, timeline]);

  const camera = plan.cameras.find(item => item.id === shot?.camera_id);
  // A lens that only has the planner's move shows it as the two keys it amounts to.
  const cameraKeys = useMemo(() => cameraKeysOf(timeline, camera), [camera, timeline]);
  const shownKeys = (track: TrackRef): TimelineKey[] => (track.kind === 'camera' ? cameraKeys : keysOf(timeline, track));
  const pickedKey = picked ? shownKeys(picked.track)[picked.index] : undefined;
  const busy = !editable || !shot;

  const write = (label: string, track: TrackRef, keys: TimelineKey[]) => {
    if (!shot) return;
    if (keys.length > MAX_TRACK_KEYS) { setMessage(`每条轨道最多 ${MAX_TRACK_KEYS} 个关键帧`); return; }
    setMessage('');
    onCommit({ label, operations: [trackOperation(shot.shot_id, timeline, track, keys)] });
  };

  const keyCamera = () => {
    const lens = sampleShot(plan, shot, playback.time).camera;
    if (!lens) return;
    const keys = upsertKey(cameraKeys, cameraKeyAt(lens, timeOfFrame(playback.frame, fps)), fps);
    write('机位关键帧', { kind: 'camera' }, keys);
    setPicked({ track: { kind: 'camera' }, index: keyIndexAtFrame(keys, playback.frame, fps) });
  };

  const keyActor = () => {
    const actor = cast.find(item => item.name === selectedActor);
    if (!actor) return;
    const track: TrackRef = { kind: 'actor', name: actor.name };
    const held = keysOf(timeline, track) as ActorKey[];
    const keys = upsertKey(held, actorKeyAt(sampleActor(actor, held, playback.time, true), timeOfFrame(playback.frame, fps)), fps);
    write(`${actor.name} 关键帧`, track, keys);
    setPicked({ track, index: keyIndexAtFrame(keys, playback.frame, fps) });
  };

  const removePicked = () => {
    if (!picked || !pickedKey) return;
    write('删除关键帧', picked.track, removeKey(shownKeys(picked.track), picked.index));
    setPicked(null);
  };

  const paste = () => {
    if (!clipboard) return;
    const track: TrackRef | null = clipboard.kind === 'camera' ? { kind: 'camera' }
      : picked?.track.kind === 'actor' ? picked.track : selectedActor ? { kind: 'actor', name: selectedActor } : null;
    if (!track) { setMessage('先选择一个角色，再把人物关键帧粘贴到他的轨道上'); return; }
    const keys = upsertKey(shownKeys(track), { ...clipboard.key, time: timeOfFrame(playback.frame, fps) }, fps);
    write('粘贴关键帧', track, keys);
    setPicked({ track, index: keyIndexAtFrame(keys, playback.frame, fps) });
  };

  const setEasing = (easing: StageEasing) => {
    if (!picked || !pickedKey) return;
    write('关键帧缓动', picked.track, shownKeys(picked.track).map((key, index) => (index === picked.index ? { ...key, easing } : key)));
  };

  const commitDuration = (text: string) => {
    const next = Number(text);
    if (!shot || text.trim() === '' || next === durationS) return;
    const refusal = durationRefusal(timeline, next);
    setMessage(refusal);
    if (!refusal) onCommit({ label: '镜头时长', operations: [{ op: 'set_timeline', shot_id: shot.shot_id, duration_s: next }] });
  };

  const applyMove = () => {
    if (!shot) return;
    const preset = cameraMove(move.preset);
    setMovesOpen(false);
    setPicked(null);
    setMessage('');
    onCommit({
      label: `运镜：${preset.label}`, barrier: true,
      operations: [{
        op: 'apply_camera_move', shot_id: shot.shot_id, preset: preset.id, amplitude: move.amplitude,
        ...(preset.angled ? { angle: move.angle } : {}), ...(preset.sided ? { side: move.side } : {}), ...(move.easing ? { easing: move.easing } : {}),
      }],
    });
  };

  const timeAt = (lane: HTMLElement, clientX: number) => {
    const box = lane.getBoundingClientRect();
    return box.width > 0 ? Math.min(1, Math.max(0, (clientX - box.left) / box.width)) * durationS : 0;
  };

  const scrub = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.buttons !== 1 && event.type !== 'pointerdown') return;
    // A number still being typed is sent on blur. It was typed about the instant on screen, so it has to
    // go before the playhead leaves: pointerdown comes before the browser's own blur.
    if (event.type === 'pointerdown' && document.activeElement instanceof HTMLElement && document.activeElement !== event.currentTarget) document.activeElement.blur();
    playback.pause();
    playback.seek(Math.min(frames - 1, frameOf(timeAt(event.currentTarget, event.clientX), fps)) / fps);
  };

  const grabKey = (key: KeyRef) => (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const lane = event.currentTarget.parentElement;
    if (!lane) return;
    setPicked(key);
    drag.current = { key, lane, startX: event.clientX, moved: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const dragKey = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const held = drag.current;
    if (!held || busy) return;
    if (!held.moved && Math.abs(event.clientX - held.startX) < 3) return;
    held.moved = true;
    const keys = retimeKey(shownKeys(held.key.track), held.key.index, timeAt(held.lane, event.clientX), fps, durationS);
    setDragged({ ...held.key, time: keys[held.key.index].time });
  };

  const dropKey = () => {
    const held = drag.current;
    drag.current = null;
    const target = dragged;
    setDragged(null);
    if (!held) return;
    const keys = shownKeys(held.key.track);
    // A click is a selection: the playhead goes to the key so that the stage shows what it holds.
    if (!held.moved || !target) { playback.pause(); playback.seek(frameOf(keys[held.key.index]?.time ?? 0, fps) / fps); return; }
    if (target.time !== keys[held.key.index].time) write('移动关键帧', held.key.track, retimeKey(keys, held.key.index, target.time, fps, durationS));
  };

  const nudgeKey = (key: KeyRef) => (event: ReactKeyboardEvent) => {
    if (busy) return;
    const keys = shownKeys(key.track);
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      event.stopPropagation();
      write('删除关键帧', key.track, removeKey(keys, key.index));
      setPicked(null);
    }
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      const moved = retimeKey(keys, key.index, keys[key.index].time + (event.key === 'ArrowLeft' ? -1 : 1) / fps, fps, durationS);
      if (moved[key.index].time !== keys[key.index].time) write('移动关键帧', key.track, moved);
    }
  };

  if (collapsed) {
    return (
      <section className="desk-timeline is-collapsed" aria-label="时间线">
        <button type="button" className="desk-timeline__toggle" aria-expanded="false" onClick={() => onCollapsed(false)}>
          <ChevronUp aria-hidden="true" /> 时间线 · {timecode(playback.frame, fps)} / {durationS} 秒
        </button>
      </section>
    );
  }

  const percent = (time: number) => `${(Math.min(time, durationS) / durationS) * 100}%`;
  const preset = cameraMove(move.preset);

  return (
    <section className="desk-timeline" aria-label="时间线">
      <div className="desk-timeline__bar">
        <div className="desk-timeline__transport" role="group" aria-label="播放控制">
          <button type="button" className="desk-icon" aria-label="停止" onClick={playback.stop}><Square aria-hidden="true" /></button>
          <button type="button" className="desk-icon" aria-label="上一帧" onClick={() => playback.step(-1)}><SkipBack aria-hidden="true" /></button>
          <button type="button" className="desk-icon is-play" aria-label={playback.playing ? '暂停' : '播放'} onClick={playback.playing ? playback.pause : playback.play}>
            {playback.playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>
          <button type="button" className="desk-icon" aria-label="下一帧" onClick={() => playback.step(1)}><SkipForward aria-hidden="true" /></button>
          <button type="button" className={`desk-icon ${playback.loop ? 'is-active' : ''}`} aria-label="循环播放" aria-pressed={playback.loop} onClick={() => playback.setLoop(!playback.loop)}><Repeat aria-hidden="true" /></button>
          <output className="desk-timeline__timecode" aria-label="时间码">{timecode(playback.frame, fps)}</output>
          <small>第 {playback.frame + 1} / {frames} 帧</small>
        </div>
        <label className="desk-timeline__field">
          <span>时长</span>
          <input
            key={durationS} type="number" aria-label="镜头时长（秒）" defaultValue={durationS} min={DURATION_RANGE[0]} max={DURATION_RANGE[1]} step={0.5} disabled={busy}
            onBlur={event => { commitDuration(event.target.value); event.target.value = String(durationS); }}
            onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }}
          />
          <span>秒</span>
        </label>
        <label className="desk-timeline__field">
          <span>帧率</span>
          <select aria-label="帧率" value={fps} disabled={busy} onChange={event => { if (shot) onCommit({ label: '帧率', operations: [{ op: 'set_timeline', shot_id: shot.shot_id, fps: Number(event.target.value) }] }); }}>
            {FRAME_RATES.map(rate => <option key={rate} value={rate}>{rate} fps</option>)}
          </select>
        </label>
        <div className="desk-timeline__actions">
          <button type="button" className="desk-button" disabled={busy || !camera || playback.playing} onClick={keyCamera}><Diamond aria-hidden="true" /> 在播放头处打关键帧 · 机位</button>
          <button type="button" className="desk-button" disabled={busy || !selectedActor || playback.playing} title={selectedActor ? '位置、朝向和当前姿势一起记为一帧' : '先在舞台上选择一个角色'} onClick={keyActor}>
            <Diamond aria-hidden="true" /> 在播放头处打关键帧 · {selectedActor || '角色'}
          </button>
          <button type="button" className="desk-button" aria-expanded={movesOpen} disabled={busy || !camera} onClick={() => setMovesOpen(open => !open)}><Film aria-hidden="true" /> 运镜预设</button>
          <button type="button" className="desk-icon" aria-label="收起时间线" aria-expanded="true" onClick={() => onCollapsed(true)}><ChevronDown aria-hidden="true" /></button>
        </div>
      </div>

      {movesOpen && (
        <form className="desk-timeline__moves" aria-label="运镜预设" noValidate onSubmit={event => { event.preventDefault(); applyMove(); }}>
          <label><span>预设</span>
            <select aria-label="运镜预设类型" value={move.preset} onChange={event => setMove(current => ({ ...current, preset: event.target.value, angle: cameraMove(event.target.value).defaultAngle ?? DEFAULT_MOVE_ANGLE }))}>
              {CAMERA_MOVES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label><span>幅度</span>
            <input type="number" aria-label="幅度" value={move.amplitude} min={AMPLITUDE_RANGE[0]} max={AMPLITUDE_RANGE[1]} step={0.05}
              onChange={event => setMove(current => ({ ...current, amplitude: Math.min(AMPLITUDE_RANGE[1], Math.max(AMPLITUDE_RANGE[0], Number(event.target.value) || 1)) }))} />
          </label>
          {preset.angled && (
            <label><span>角度</span>
              <input type="number" aria-label="角度" value={move.angle} min={ANGLE_RANGE[0]} max={ANGLE_RANGE[1]} step={1}
                onChange={event => setMove(current => ({ ...current, angle: Math.min(ANGLE_RANGE[1], Math.max(ANGLE_RANGE[0], Number(event.target.value) || DEFAULT_MOVE_ANGLE)) }))} />
            </label>
          )}
          {preset.sided && (
            <label><span>方向</span>
              <select aria-label="方向" value={move.side} onChange={event => setMove(current => ({ ...current, side: event.target.value as MoveSide }))}>
                {(Object.keys(SIDE_LABELS) as MoveSide[]).map(side => <option key={side} value={side}>{SIDE_LABELS[side]}</option>)}
              </select>
            </label>
          )}
          <label><span>缓动</span>
            <select aria-label="运镜缓动" value={move.easing} onChange={event => setMove(current => ({ ...current, easing: event.target.value as StageEasing | '' }))}>
              <option value="">默认（{EASING_LABELS[preset.defaultEasing ?? 'smooth']}）</option>
              {MOVE_EASINGS.map(easing => <option key={easing} value={easing}>{EASING_LABELS[easing]}</option>)}
            </select>
          </label>
          <button type="submit" className="desk-button is-primary">应用到第 {shot?.shot_id} 镜</button>
          <small>{preset.hint}。会替换本镜已有的机位关键帧；写入后每一帧都可以再拖动、改缓动或删除。不越轴、主体不出画由服务器保证，幅度过大时会自动收小。</small>
        </form>
      )}

      <div className="desk-timeline__tracks">
        <div className="desk-timeline__row is-ruler">
          <span className="desk-timeline__name">秒</span>
          <div className="desk-timeline__lane" role="slider" tabIndex={0} aria-label="播放头" aria-valuemin={0} aria-valuemax={frames - 1} aria-valuenow={playback.frame}
            onPointerDown={scrub} onPointerMove={scrub}
            onKeyDown={event => { if (event.key === 'ArrowLeft') playback.step(-1); if (event.key === 'ArrowRight') playback.step(1); }}
          >
            {Array.from({ length: Math.floor(durationS) + 1 }, (_, second) => <i key={second} style={{ left: percent(second) }}>{second}</i>)}
            <b className="desk-timeline__playhead" style={{ left: percent(playback.time) }} />
          </div>
        </div>
        {tracks.map(track => {
          const keys = shownKeys(track);
          const legacy = track.kind === 'camera' && !timeline.camera.length && keys.length > 0;
          return (
            <div key={trackKey(track)} className="desk-timeline__row">
              {track.kind === 'camera'
                ? <span className="desk-timeline__name">机位{legacy ? <small title="来自分镜的运镜；打一个关键帧后即可逐帧编辑"> · 分镜运镜</small> : null}</span>
                : <button type="button" className={`desk-timeline__name ${track.name === selectedActor ? 'is-active' : ''}`} onClick={() => onSelect({ kind: 'actor', name: track.name }, false)}>{track.name}</button>}
              <div className="desk-timeline__lane" aria-label={`${trackLabel(track)}轨`} onPointerDown={scrub} onPointerMove={event => { if (!drag.current) scrub(event); }}>
                {keys.map((key, index) => {
                  const isPicked = Boolean(picked && sameTrack(picked.track, track) && picked.index === index);
                  const time = dragged && sameTrack(dragged.track, track) && dragged.index === index ? dragged.time : key.time;
                  return (
                    <button
                      key={index} type="button" className={`desk-timeline__key ${isPicked ? 'is-picked' : ''} ${legacy ? 'is-legacy' : ''}`} style={{ left: percent(time) }}
                      aria-label={`${trackLabel(track)}关键帧 ${time.toFixed(2)} 秒`} aria-pressed={isPicked} disabled={legacy}
                      onPointerDown={grabKey({ track, index })} onPointerMove={dragKey} onPointerUp={dropKey} onPointerCancel={dropKey} onKeyDown={nudgeKey({ track, index })}
                    />
                  );
                })}
                <b className="desk-timeline__playhead" style={{ left: percent(playback.time) }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="desk-timeline__foot">
        {pickedKey && picked ? (
          <>
            <span>{trackLabel(picked.track)}轨 · {pickedKey.time.toFixed(2)} 秒</span>
            <label className="desk-timeline__field">
              <span>进入此帧的缓动</span>
              <select aria-label="关键帧缓动" value={pickedKey.easing} disabled={busy} onChange={event => setEasing(event.target.value as StageEasing)}>
                {(Object.keys(EASING_LABELS) as StageEasing[]).map(easing => <option key={easing} value={easing}>{EASING_LABELS[easing]}</option>)}
              </select>
            </label>
            <button type="button" className="desk-icon" aria-label="复制关键帧" onClick={() => setClipboard({ kind: picked.track.kind, key: pickedKey })}><Copy aria-hidden="true" /></button>
            <button type="button" className="desk-icon" aria-label="删除关键帧" disabled={busy} onClick={removePicked}><Trash2 aria-hidden="true" /></button>
          </>
        ) : <span className="desk-timeline__hint">点关键帧选中并跳到该帧 · 左右拖动改时间（吸附到帧）· 播放头停在关键帧上时，拖动舞台上的对象改的是这一帧</span>}
        <button type="button" className="desk-icon" aria-label="在播放头处粘贴关键帧" disabled={busy || !clipboard} onClick={paste}><ClipboardPaste aria-hidden="true" /></button>
        {shot && plan.timelines?.[String(shot.shot_id)] && (
          <button type="button" className="desk-button is-danger" disabled={busy} onClick={() => { setPicked(null); onCommit({ label: '清空时间线', operations: [{ op: 'clear_timeline', shot_id: shot.shot_id }] }); }}>清空本镜时间线</button>
        )}
        {message && <p className="desk-timeline__error" role="alert">{message}</p>}
      </div>
    </section>
  );
}
