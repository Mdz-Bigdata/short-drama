import type {
  ActorKey, CameraKey, ShotTimeline, StageActor, StageCamera, StageEasing, StageOperation, StagePlan, StagePose, StageShot,
} from '../../spatial/spatialTypes';
import { round2 } from './stageMath';
import { frameOf, timeOfFrame, timelineOf } from './sampling';

// Key edits as data. Every one of them ends in a `set_timeline` that carries a whole track: the
// server replaces `camera` and `actors` wholesale, so a track is never half-written.

export type TrackRef = { kind: 'camera' } | { kind: 'actor'; name: string };
export type TimelineKey = CameraKey | ActorKey;

export const MAX_TRACK_KEYS = 120;
export const DURATION_RANGE: [number, number] = [1, 30];

export const EASING_LABELS: Record<StageEasing, string> = {
  linear: '匀速', smooth: '缓入缓出', 'ease-in': '加速', 'ease-out': '减速', hold: '保持后跳变', whip: '快速甩动',
};

export function trackKey(track: TrackRef): string {
  return track.kind === 'camera' ? 'camera' : `actor:${track.name}`;
}

export function trackLabel(track: TrackRef): string {
  return track.kind === 'camera' ? '机位' : `「${track.name}」`;
}

export function keysOf(timeline: ShotTimeline, track: TrackRef): TimelineKey[] {
  return track.kind === 'camera' ? timeline.camera : timeline.actors[track.name] || [];
}

/** The whole track, as the server wants it; an actor track with no keys left is dropped. */
export function trackOperation(shotId: number, timeline: ShotTimeline, track: TrackRef, keys: TimelineKey[]): StageOperation {
  if (track.kind === 'camera') return { op: 'set_timeline', shot_id: shotId, camera: keys };
  return { op: 'set_timeline', shot_id: shotId, actors: { ...timeline.actors, [track.name]: keys as ActorKey[] } };
}

export function keyIndexAtFrame(keys: Array<{ time: number }>, frame: number, fps: number): number {
  return keys.findIndex(key => frameOf(key.time, fps) === frame);
}

/** `key` takes the place of whatever sits on its frame; the track stays in time order. */
export function upsertKey<K extends { time: number }>(keys: K[], key: K, fps: number): K[] {
  const frame = frameOf(key.time, fps);
  return [...keys.filter(item => frameOf(item.time, fps) !== frame), key].sort((a, b) => a.time - b.time);
}

export function removeKey<K>(keys: K[], index: number): K[] {
  return keys.filter((_, position) => position !== index);
}

/** Drag a key in time: whole frames only, and never onto or past a neighbour. */
export function retimeKey<K extends { time: number }>(keys: K[], index: number, time: number, fps: number, durationS: number): K[] {
  const lowest = index > 0 ? frameOf(keys[index - 1].time, fps) + 1 : 0;
  const highest = index < keys.length - 1 ? frameOf(keys[index + 1].time, fps) - 1 : Math.floor(durationS * fps + 1e-6);
  const frame = Math.min(Math.max(frameOf(time, fps), lowest), Math.max(lowest, highest));
  return keys.map((key, position) => (position === index ? { ...key, time: timeOfFrame(frame, fps) } : key));
}

export function lastKey(timeline: ShotTimeline): { track: TrackRef; time: number } | null {
  const tracks: TrackRef[] = [{ kind: 'camera' }, ...Object.keys(timeline.actors).map(name => ({ kind: 'actor' as const, name }))];
  let latest: { track: TrackRef; time: number } | null = null;
  tracks.forEach(track => {
    const keys = keysOf(timeline, track);
    const time = keys.length ? keys[keys.length - 1].time : -1;
    if (time >= 0 && (!latest || time > latest.time)) latest = { track, time };
  });
  return latest;
}

/** Why `durationS` cannot be this shot's length, or '' when it can. */
export function durationRefusal(timeline: ShotTimeline, durationS: number): string {
  if (!Number.isFinite(durationS) || durationS < DURATION_RANGE[0] || durationS > DURATION_RANGE[1]) return `时长只能在 ${DURATION_RANGE[0]} 到 ${DURATION_RANGE[1]} 秒之间`;
  const last = lastKey(timeline);
  if (last && last.time > durationS + 1e-6) {
    return `时长不能短于最后一个关键帧：${trackLabel(last.track)}轨在 ${last.time.toFixed(2)} 秒还有一帧，请先移动或删除它`;
  }
  return '';
}

export function cameraKeyAt(camera: Pick<StageCamera, 'position' | 'target' | 'lens_mm'>, time: number, easing: StageEasing = 'smooth'): CameraKey {
  const point = (values: readonly number[]) => values.map(round2) as [number, number, number];
  return { time, position: point(camera.position), target: point(camera.target), lens_mm: Math.round(camera.lens_mm * 10) / 10, easing };
}

/** A whole-figure key: where they stand, which way they face and how they hold themselves. */
export function actorKeyAt(actor: Pick<StageActor, 'position' | 'yaw_deg' | 'pose'>, time: number, easing: StageEasing = 'smooth'): ActorKey {
  return {
    time, position: [round2(actor.position[0]), round2(actor.position[1])], yaw_deg: round2(actor.yaw_deg),
    ...(actor.pose ? { pose: actor.pose } : {}), easing,
  };
}

function poseOfOperation(op: StageOperation): StagePose | null {
  const joints = (op.joints && typeof op.joints === 'object' ? op.joints : {}) as Record<string, number>;
  const preset = String(op.preset || '');
  const clip = String(op.clip || '');
  if (!preset && !clip && !Object.keys(joints).length) return null;
  return { preset, joints, clip, clip_phase: Number(op.clip_phase) || 0 };
}

export interface Retargeted {
  operations: StageOperation[];
  /** Tracks whose key on the playhead took the edit. */
  tracks: TrackRef[];
}

/**
 * An edit made while the playhead sits on a key belongs to that key: what the viewport shows at
 * that instant *is* the key, so moving the base mark underneath it would change nothing on screen.
 * Everything else passes through untouched.
 */
export function retargetToKeys(plan: StagePlan, shot: StageShot | undefined, time: number, operations: StageOperation[]): Retargeted {
  if (!shot || !operations.length) return { operations, tracks: [] };
  const timeline = timelineOf(plan, shot.shot_id);
  const frame = frameOf(time, timeline.fps);
  let camera = timeline.camera;
  let actors = timeline.actors;
  const tracks: TrackRef[] = [];
  const kept: StageOperation[] = [];

  operations.forEach(op => {
    if (op.op === 'move_camera' && op.camera_id === shot.camera_id) {
      const index = keyIndexAtFrame(camera, frame, timeline.fps);
      if (index >= 0) {
        const key = camera[index];
        camera = camera.map((item, position) => (position !== index ? item : {
          ...key,
          position: (op.position as CameraKey['position']) ?? key.position, target: (op.target as CameraKey['target']) ?? key.target,
          lens_mm: 'lens_mm' in op ? Number(op.lens_mm) : key.lens_mm,
        }));
        tracks.push({ kind: 'camera' });
        return;
      }
    }
    const name = String(op.name || '');
    const staged = op.op === 'move_actor' || op.op === 'set_shot_override';
    const posed = op.op === 'set_pose';
    if ((staged || posed) && (op.op === 'move_actor' || Number(op.shot_id ?? shot.shot_id) === shot.shot_id)) {
      const keys = actors[name] || [];
      const index = keyIndexAtFrame(keys, frame, timeline.fps);
      const speaks = posed || 'position' in op || 'yaw_deg' in op;
      if (index >= 0 && speaks) {
        const key = keys[index];
        const next: ActorKey = posed
          ? { ...key, pose: poseOfOperation(op) }
          : { ...key, position: (op.position as ActorKey['position']) ?? key.position, yaw_deg: 'yaw_deg' in op && op.yaw_deg != null ? Number(op.yaw_deg) : key.yaw_deg };
        // A key has to say something; a pose taken off a pose-only key leaves the pose it had.
        const says = next.position || (next.yaw_deg !== null && next.yaw_deg !== undefined) || next.pose;
        actors = { ...actors, [name]: keys.map((item, position) => (position === index && says ? next : item)) };
        tracks.push({ kind: 'actor', name });
        if (op.op !== 'set_shot_override') return;
        // The rest of a re-mark (offstage, hold, posture…) is still the shot's; its place and facing stay as stored.
        const stored = shot.overrides.find(item => item.name === name);
        const rest: StageOperation = { ...op };
        delete rest.position;
        delete rest.yaw_deg;
        if (stored?.position) rest.position = stored.position;
        if (stored?.yaw_deg !== null && stored?.yaw_deg !== undefined) rest.yaw_deg = stored.yaw_deg;
        const same = stored && Object.keys(rest).every(field => field === 'op' || field === 'shot_id'
          || JSON.stringify(rest[field] ?? null) === JSON.stringify((stored as unknown as Record<string, unknown>)[field] ?? null));
        if (!same) kept.push(rest);
        return;
      }
    }
    kept.push(op);
  });

  if (!tracks.length) return { operations, tracks };
  const write: StageOperation = { op: 'set_timeline', shot_id: shot.shot_id };
  if (camera !== timeline.camera) write.camera = camera;
  if (actors !== timeline.actors) write.actors = actors;
  return { operations: [...kept, write], tracks };
}
