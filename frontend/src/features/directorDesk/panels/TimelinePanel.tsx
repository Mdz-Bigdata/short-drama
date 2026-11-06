import { useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import {
  ChevronDown, ChevronUp, ClipboardPaste, Copy, Diamond, Film, Pause, Play, Repeat, SkipBack, SkipForward, Square, Trash2, Waypoints,
} from 'lucide-react';

import { actorsInShot, type ActionClip, type ActorKey, type CameraCut, type FollowClip, type SpacePoint, type StageEasing, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import {
  AMPLITUDE_RANGE, ANGLE_RANGE, CAMERA_MOVES, DEFAULT_MOVE_ANGLE, MOVE_EASINGS, SIDE_LABELS, cameraMove, type MoveSide,
} from '../lib/cameraMoves';
import { HUMANOID_CLIPS, humanoidClip } from '../lib/humanoidClips';
import { FRAME_RATES, cameraKeysOf, frameCount, frameOf, sampleActor, sampleShot, timeOfFrame, timelineOf } from '../lib/sampling';
import {
  FOLLOW_PRESETS, actionClipsOf, addAction, addCut, addFollow, bakeFollow, clipsOperation, cutsOperation, figureForAction, followOperation,
} from '../lib/timelineClips';
import {
  DURATION_RANGE, EASING_LABELS, MAX_TRACK_KEYS, actorKeyAt, cameraKeyAt, durationRefusal, keyIndexAtFrame, keysOf, removeKey, retimeKey,
  trackKey, trackLabel, trackOperation, upsertKey, type TimelineKey, type TrackRef,
} from '../lib/timelineEdits';
import type { DeskPlayback } from '../useDeskPlayback';
import { ClipLane } from './ClipLane';

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
type BlockRef = { kind: 'action'; name: string; id: string } | { kind: 'follow'; id: string } | { kind: 'cut'; id: string };

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
  const [pickedBlock, setPickedBlock] = useState<BlockRef | null>(null);
  // People put on the timeline by hand, before they have a key or a clip of their own.
  const [pinned, setPinned] = useState<string[]>([]);
  const drag = useRef<{ key: KeyRef; lane: HTMLElement; startX: number; moved: boolean } | null>(null);

  const primary = selection[selection.length - 1];
  const selectedActor = primary?.kind === 'actor' ? primary.name : '';
  const cast = useMemo(() => actorsInShot(plan, shot), [plan, shot]);
  const tracks = useMemo<TrackRef[]>(() => {
    const names = cast
      .filter(actor => timeline.actors[actor.name]?.length || timeline.clips?.[actor.name]?.length || actor.name === selectedActor || pinned.includes(actor.name))
      .map(actor => actor.name);
    return [{ kind: 'camera' }, ...names.map(name => ({ kind: 'actor' as const, name }))];
  }, [cast, pinned, selectedActor, timeline]);

  const camera = plan.cameras.find(item => item.id === shot?.camera_id);
  // A lens that only has the planner's move shows it as the two keys it amounts to.
  const cameraKeys = useMemo(() => cameraKeysOf(timeline, camera), [camera, timeline]);
  const shownKeys = (track: TrackRef): TimelineKey[] => (track.kind === 'camera' ? cameraKeys : keysOf(timeline, track));
  const pickedKey = picked ? shownKeys(picked.track)[picked.index] : undefined;
  const busy = !editable || !shot;
  const follow = timeline.follow ?? [];
  const pickedAction = pickedBlock?.kind === 'action' ? actionClipsOf(timeline, pickedBlock.name).find(clip => clip.id === pickedBlock.id) : undefined;
  const pickedFollow = pickedBlock?.kind === 'follow' ? follow.find(clip => clip.id === pickedBlock.id) : undefined;
  const cuts = timeline.cuts ?? [];
  const pickedCut = pickedBlock?.kind === 'cut' ? cuts.find(cut => cut.id === pickedBlock.id) : undefined;
  // The lenses a cut may go to: the shot's own and its candidates.
  const lenses = shot ? [shot.camera_id, ...(shot.alt_camera_ids ?? [])].flatMap(id => plan.cameras.filter(item => item.id === id)) : [];
  const lensLabel = (id: string) => plan.cameras.find(item => item.id === id)?.label || id;

  const writeCuts = (label: string, next: CameraCut[]) => {
    if (!shot) return;
    setMessage('');
    onCommit({ label, operations: [cutsOperation(shot.shot_id, next)] });
  };

  const dropCut = (cameraId: string) => {
    const cut = addCut(timeline, cameraId, timeOfFrame(playback.frame, fps));
    if (!cut) { setMessage('播放头这里已经没有空位：先把播放头挪到空白处，或修剪旁边的切机位片段'); return; }
    setPickedBlock({ kind: 'cut', id: cut.id });
    writeCuts(`切到 ${lensLabel(cameraId)}`, [...cuts, cut]);
  };

  const writeClips = (label: string, name: string, clips: ActionClip[]) => {
    if (!shot) return;
    setMessage('');
    onCommit({ label, operations: [clipsOperation(shot.shot_id, timeline, name, clips)] });
  };

  const writeFollow = (label: string, clips: FollowClip[]) => {
    if (!shot) return;
    setMessage('');
    onCommit({ label, operations: [followOperation(shot.shot_id, clips)] });
  };

  const dropAction = (name: string, clipId: string) => {
    if (!shot) return;
    const clip = addAction(timeline, name, clipId, timeOfFrame(playback.frame, fps));
    if (!clip) { setMessage('播放头这里已经没有空位：先把播放头挪到空白处，或修剪旁边的片段'); return; }
    setMessage('');
    setPickedBlock({ kind: 'action', name, id: clip.id });
    onCommit({
      label: `动作：${humanoidClip(clipId).name}`,
      operations: [...figureForAction(cast.find(actor => actor.name === name)), clipsOperation(shot.shot_id, timeline, name, [...actionClipsOf(timeline, name), clip])],
    });
  };

  const dropFollow = (actor: string, presetId: string) => {
    const preset = FOLLOW_PRESETS.find(item => item.id === presetId);
    if (!preset) return;
    const clip = addFollow(timeline, actor, preset, timeOfFrame(playback.frame, fps));
    if (!clip) { setMessage('播放头这里已经没有空位：先把播放头挪到空白处，或修剪旁边的跟拍片段'); return; }
    setPickedBlock({ kind: 'follow', id: clip.id });
    writeFollow(`跟拍：${actor}`, [...follow, clip]);
  };

  const changeFollow = (changes: Partial<FollowClip>) => {
    if (pickedFollow) writeFollow('调整跟拍', follow.map(clip => (clip.id === pickedFollow.id ? { ...clip, ...changes } : clip)));
  };

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
              {track.kind === 'camera' ? (
                <>
                  <span className="desk-timeline__name is-sub">切机位
                    <select
                      aria-label="添加切机位片段" value="" disabled={busy || lenses.length < 2} title={lenses.length < 2 ? '先在机位面板添加候选机位' : undefined}
                      onChange={event => { if (event.target.value) dropCut(event.target.value); }}
                    >
                      <option value="">+ 切到</option>
                      {lenses.map(item => <option key={item.id} value={item.id}>{item.label}{item.id === shot?.camera_id ? '（主机位）' : ''}</option>)}
                    </select>
                  </span>
                  <ClipLane
                    tone="cut" label="切机位" durationS={durationS} fps={fps} time={playback.time} disabled={busy}
                    blocks={cuts.map(cut => ({ ...cut, label: lensLabel(cut.camera_id) }))}
                    pickedId={pickedBlock?.kind === 'cut' ? pickedBlock.id : ''}
                    onPick={id => setPickedBlock({ kind: 'cut', id })}
                    onChange={blocks => writeCuts('移动切机位片段', cuts.map(cut => { const moved = blocks.find(block => block.id === cut.id); return moved ? { ...cut, start: moved.start, end: moved.end } : cut; }).sort((a, b) => a.start - b.start))}
                    onScrub={scrub}
                  />
                  <span className="desk-timeline__name is-sub">跟拍
                    <select
                      aria-label="添加跟拍片段" value="" disabled={busy || !cast.length}
                      onChange={event => { const [actor, preset] = event.target.value.split('\u0000'); if (actor && preset) dropFollow(actor, preset); }}
                    >
                      <option value="">+ 跟拍</option>
                      {cast.map(actor => (
                        <optgroup key={actor.name} label={actor.name}>
                          {FOLLOW_PRESETS.map(preset => <option key={preset.id} value={`${actor.name}\u0000${preset.id}`}>{preset.label}</option>)}
                        </optgroup>
                      ))}
                    </select>
                  </span>
                  <ClipLane
                    tone="follow" label="跟拍" durationS={durationS} fps={fps} time={playback.time} disabled={busy}
                    blocks={follow.map(clip => ({ ...clip, label: clip.actor }))}
                    pickedId={pickedBlock?.kind === 'follow' ? pickedBlock.id : ''}
                    onPick={id => setPickedBlock({ kind: 'follow', id })}
                    onChange={blocks => writeFollow('移动跟拍片段', follow.map(clip => { const moved = blocks.find(block => block.id === clip.id); return moved ? { ...clip, start: moved.start, end: moved.end } : clip; }).sort((a, b) => a.start - b.start))}
                    onScrub={scrub}
                  />
                </>
              ) : (
                <>
                  <span className="desk-timeline__name is-sub">动作
                    <select
                      aria-label={`给${track.name}添加动作`} value="" disabled={busy}
                      onChange={event => { if (event.target.value) dropAction(track.name, event.target.value); }}
                    >
                      <option value="">+ 动作</option>
                      {HUMANOID_CLIPS.map(clip => <option key={clip.id} value={clip.id}>{clip.name}</option>)}
                    </select>
                  </span>
                  <ClipLane
                    tone="action" label={`「${track.name}」动作`} durationS={durationS} fps={fps} time={playback.time} disabled={busy}
                    blocks={actionClipsOf(timeline, track.name).map(clip => ({ ...clip, label: humanoidClip(clip.clip).name }))}
                    pickedId={pickedBlock?.kind === 'action' && pickedBlock.name === track.name ? pickedBlock.id : ''}
                    onPick={id => setPickedBlock({ kind: 'action', name: track.name, id })}
                    onChange={blocks => writeClips('移动动作片段', track.name, actionClipsOf(timeline, track.name).map(clip => { const moved = blocks.find(block => block.id === clip.id); return moved ? { ...clip, start: moved.start, end: moved.end } : clip; }).sort((a, b) => a.start - b.start))}
                    onScrub={scrub}
                  />
                </>
              )}
            </div>
          );
        })}
        {cast.some(actor => !tracks.some(track => track.kind === 'actor' && track.name === actor.name)) && (
          <div className="desk-timeline__row">
            <select
              className="desk-timeline__add" aria-label="添加角色到时间线" value=""
              onChange={event => { if (event.target.value) setPinned(names => [...names, event.target.value]); }}
            >
              <option value="">+ 添加角色到时间线</option>
              {cast.filter(actor => !tracks.some(track => track.kind === 'actor' && track.name === actor.name)).map(actor => <option key={actor.name} value={actor.name}>{actor.name}</option>)}
            </select>
          </div>
        )}
      </div>

      {pickedAction && pickedBlock?.kind === 'action' && (
        <div className="desk-timeline__clipbar" role="group" aria-label="动作片段">
          <strong>{pickedBlock.name} · {humanoidClip(pickedAction.clip).name}</strong>
          <span>{pickedAction.start.toFixed(2)}–{pickedAction.end.toFixed(2)} 秒</span>
          <label className="desk-timeline__field"><span>动作</span>
            <select aria-label="片段动作" value={pickedAction.clip} disabled={busy} onChange={event => writeClips('更换动作', pickedBlock.name, actionClipsOf(timeline, pickedBlock.name).map(clip => (clip.id === pickedAction.id ? { ...clip, clip: event.target.value } : clip)))}>
              {HUMANOID_CLIPS.map(clip => <option key={clip.id} value={clip.id}>{clip.name}</option>)}
            </select>
          </label>
          <label className="desk-timeline__field"><span>速度</span>
            <input
              key={pickedAction.speed ?? 1} type="number" aria-label="动作速度" defaultValue={pickedAction.speed ?? 1} min={0.1} max={4} step={0.1} disabled={busy}
              onBlur={event => { const speed = Number(event.target.value); if (speed >= 0.1 && speed <= 4 && speed !== (pickedAction.speed ?? 1)) writeClips('动作速度', pickedBlock.name, actionClipsOf(timeline, pickedBlock.name).map(clip => (clip.id === pickedAction.id ? { ...clip, speed } : clip))); }}
            />
          </label>
          <button type="button" className="desk-icon" aria-label="删除动作片段" disabled={busy} onClick={() => { setPickedBlock(null); writeClips('删除动作片段', pickedBlock.name, actionClipsOf(timeline, pickedBlock.name).filter(clip => clip.id !== pickedAction.id)); }}><Trash2 aria-hidden="true" /></button>
        </div>
      )}

      {pickedCut && (
        <div className="desk-timeline__clipbar" role="group" aria-label="切机位片段">
          <strong>切到 · {lensLabel(pickedCut.camera_id)}</strong>
          <span>{pickedCut.start.toFixed(2)}–{pickedCut.end.toFixed(2)} 秒</span>
          <label className="desk-timeline__field"><span>机位</span>
            <select aria-label="切到哪个机位" value={pickedCut.camera_id} disabled={busy} onChange={event => writeCuts('更换切机位', cuts.map(cut => (cut.id === pickedCut.id ? { ...cut, camera_id: event.target.value } : cut)))}>
              {lenses.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <small>这段时间机位画面和导出的白模视频都按这个机位拍；它不随主机位的关键帧运动</small>
          <button type="button" className="desk-icon" aria-label="删除切机位片段" disabled={busy} onClick={() => { setPickedBlock(null); writeCuts('删除切机位片段', cuts.filter(cut => cut.id !== pickedCut.id)); }}><Trash2 aria-hidden="true" /></button>
        </div>
      )}
      {pickedFollow && (
        <div className="desk-timeline__clipbar" role="group" aria-label="跟拍片段">
          <strong>跟拍 · {pickedFollow.actor}</strong>
          <span>{pickedFollow.start.toFixed(2)}–{pickedFollow.end.toFixed(2)} 秒</span>
          {(['右', '上', '后'] as const).map((axis, index) => (
            <label key={axis} className="desk-timeline__field"><span>{axis}</span>
              <input
                key={pickedFollow.offset[index]} type="number" aria-label={`跟拍偏移 ${axis}（米）`} defaultValue={pickedFollow.offset[index]} step={0.1} disabled={busy}
                onBlur={event => {
                  const value = Number(event.target.value);
                  if (!Number.isFinite(value) || value === pickedFollow.offset[index]) return;
                  const offset = [...pickedFollow.offset] as SpacePoint;
                  offset[index] = value;
                  changeFollow({ offset });
                }}
              />
            </label>
          ))}
          <label className="desk-timeline__field"><span>焦距</span>
            <input
              key={pickedFollow.lens_mm ?? 0} type="number" aria-label="跟拍焦距（毫米）" defaultValue={pickedFollow.lens_mm ?? ''} min={8} max={600} step={1} disabled={busy}
              onBlur={event => { const value = Number(event.target.value); if (value >= 8 && value <= 600 && value !== pickedFollow.lens_mm) changeFollow({ lens_mm: value }); }}
            />
          </label>
          <label className="desk-timeline__field"><span>跟随</span>
            <select aria-label="跟拍坐标系" value={pickedFollow.relative} disabled={busy} onChange={event => changeFollow({ relative: event.target.value as FollowClip['relative'] })}>
              <option value="actor">随人物转身</option>
              <option value="world">保持世界方向</option>
            </select>
          </label>
          <label className="desk-timeline__field"><span>过渡</span>
            <input
              key={pickedFollow.blend_s} type="number" aria-label="跟拍进出过渡（秒）" defaultValue={pickedFollow.blend_s} min={0} max={3} step={0.1} disabled={busy}
              onBlur={event => { const value = Number(event.target.value); if (value >= 0 && value <= 3 && value !== pickedFollow.blend_s) changeFollow({ blend_s: value }); }}
            />
          </label>
          <button type="button" className="desk-button" disabled={busy} title="写成普通机位关键帧：可以逐帧改，Blender 和工程导出也读得到" onClick={() => { if (shot) { setPickedBlock(null); onCommit({ label: '跟拍转关键帧', operations: [bakeFollow(plan, shot)] }); } }}><Waypoints aria-hidden="true" /> 转为关键帧</button>
          <button type="button" className="desk-icon" aria-label="删除跟拍片段" disabled={busy} onClick={() => { setPickedBlock(null); writeFollow('删除跟拍片段', follow.filter(clip => clip.id !== pickedFollow.id)); }}><Trash2 aria-hidden="true" /></button>
        </div>
      )}

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
