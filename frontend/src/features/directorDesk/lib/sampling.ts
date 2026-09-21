// What one shot looks like at time t: the lens and everyone in it, read straight off the keys.
//
// Easing curves and the random-access rule (no clock, no frame history: the same t always gives
// the same answer, in whatever order the frames are asked for) are ported from
//   mangfufu/director-desk (MIT) src/animation/channels.ts
// The walk / run gait curves are ported from
//   lkhxxx123/jlmlh-3d-director (MIT, © 2026 YZ) src/editor/runtime/mannequin/motion.ts
// What changed: keys are whole cameras and whole figures instead of one number per channel, a
// channel a key leaves out is carried across it, yaw takes the short way round, poses blend
// through poses.blendPose, the lens interpolates in millimetres, the custom cubic-bezier easing
// is left out (the stage model has six named easings), and the gait works in degrees, takes a
// 0…1 phase instead of seconds and has no per-character phase offset.

import { parseAspect } from '../../spatial/floorPlanGeometry';
import {
  actorsInShot, type ActorKey, type CameraKey, type GroundPoint, type ShotTimeline, type SpacePoint, type StageActor, type StageCamera,
  type StageEasing, type StagePlan, type StagePose, type StageShot,
} from '../../spatial/spatialTypes';
import { clipForPosture, humanoidClip } from './humanoidClips';
import { blendPose, jointsOf, posePosture, type Joints } from './poses';
import { verticalFov } from './stageMath';

export const DEFAULT_DURATION_S = 5;
export const DEFAULT_FPS = 24;
export const FRAME_RATES = [24, 25, 30] as const;
/** Gait cycles per second; a run steps half again as fast as a walk. */
export const GAIT_RATE: Record<'walk' | 'run', number> = { walk: 1, run: 1.5 };

export interface SampledCamera {
  position: SpacePoint;
  target: SpacePoint;
  lens_mm: number;
  fov_deg: number;
}

export interface SampledActor {
  position: GroundPoint;
  yaw_deg: number;
  pose: StagePose | null;
}

export interface ShotSample {
  /** `null` when the shot has no lens to film through. */
  camera: SampledCamera | null;
  /** Everyone on stage in this shot, by name. */
  actors: Record<string, SampledActor>;
}

/** 0…1 → 0…1. A key's easing shapes the way *into* that key, so `hold` keeps the key before until this one is reached. */
export function ease(t: number, easing: StageEasing | undefined): number {
  const x = Math.min(1, Math.max(0, t));
  switch (easing) {
    case 'smooth': return x * x * (3 - 2 * x);
    case 'ease-in': return x * x;
    case 'ease-out': return 1 - (1 - x) ** 2;
    case 'hold': return x < 1 ? 0 : 1;
    case 'whip': return x < 0.5 ? 8 * x ** 4 : 1 - 8 * (1 - x) ** 4;
    default: return x;
  }
}

export function timelineOf(plan: Pick<StagePlan, 'timelines'>, shotId: number | null | undefined): ShotTimeline {
  const stored = shotId === null || shotId === undefined ? undefined : plan.timelines?.[String(shotId)];
  return stored ?? { duration_s: DEFAULT_DURATION_S, fps: DEFAULT_FPS, camera: [], actors: {} };
}

export function frameCount(durationS: number, fps: number): number {
  return Math.max(1, Math.ceil(durationS * fps - 1e-6));
}

export function frameOf(time: number, fps: number): number {
  return Math.round(time * fps);
}

/** Key times are stored to the millisecond, which is what the server keeps. */
export function timeOfFrame(frame: number, fps: number): number {
  return Math.round((frame / fps) * 1000) / 1000;
}

/** The frame a playhead is showing: preview, scrub and export all draw whole frames. */
export function snapToFrame(time: number, fps: number, durationS: number): number {
  const last = frameCount(durationS, fps) - 1;
  return Math.min(last, Math.max(0, Math.floor(time * fps + 1e-6))) / fps;
}

/** Tenths of a millimetre: fine enough for any frame, and 0.1 + 0.2 stops showing up in the inspector. */
function lerp(a: number, b: number, t: number): number {
  return Math.round((a + (b - a) * t) * 1e4) / 1e4 + 0;
}

/** From `a` to `b` the short way round; the result stays within (−180, 180]. */
export function lerpYaw(a: number, b: number, t: number): number {
  const delta = ((b - a + 540) % 360 + 360) % 360 - 180;
  const value = ((a + delta * t + 180) % 360 + 360) % 360 - 180;
  return value === -180 ? 180 : value;
}

interface Span<K> { from: K; to: K; weight: number }

/** The two keys around `t` and how far between them the easing has got; before the first and after the last, that key alone. */
function spanAt<K extends { time: number; easing?: StageEasing }>(keys: K[], t: number): Span<K> | null {
  if (!keys.length) return null;
  if (t <= keys[0].time) return { from: keys[0], to: keys[0], weight: 0 };
  for (let index = 1; index < keys.length; index += 1) {
    const to = keys[index];
    if (t < to.time) {
      const from = keys[index - 1];
      return { from, to, weight: ease((t - from.time) / (to.time - from.time), to.easing) };
    }
  }
  const last = keys[keys.length - 1];
  return { from: last, to: last, weight: 0 };
}

/** A camera that only has the planner's `move` is the same thing as two keys over the whole shot. */
export function cameraKeysOf(timeline: ShotTimeline, camera: StageCamera | undefined): CameraKey[] {
  if (timeline.camera.length || !camera) return timeline.camera;
  const { end_position: endPosition, end_target: endTarget } = camera.move || {};
  if (!endPosition && !endTarget) return [];
  return [
    { time: 0, position: camera.position, target: camera.target, lens_mm: camera.lens_mm, easing: 'linear' },
    { time: timeline.duration_s, position: endPosition ?? camera.position, target: endTarget ?? camera.target, lens_mm: camera.lens_mm, easing: 'smooth' },
  ];
}

export function sampleCamera(keys: CameraKey[], camera: StageCamera, aspect: number, t: number): SampledCamera {
  const span = spanAt(keys, t);
  if (!span) return { position: camera.position, target: camera.target, lens_mm: camera.lens_mm, fov_deg: camera.fov_deg };
  const { from, to, weight } = span;
  const point = (a: SpacePoint, b: SpacePoint): SpacePoint => [lerp(a[0], b[0], weight), lerp(a[1], b[1], weight), lerp(a[2], b[2], weight)];
  // Millimetres are what a person keyed; the angle follows from them, never the other way round.
  const lens = lerp(from.lens_mm, to.lens_mm, weight);
  return { position: point(from.position, to.position), target: point(from.target, to.target), lens_mm: lens, fov_deg: verticalFov(lens, aspect) };
}

function swing(forward: number, back: number, theta: number): number {
  const s = Math.sin(theta);
  return s >= 0 ? forward * s : back * s;
}

/**
 * Joint angles (degrees) of one instant of a gait cycle; `phase` runs 0…1. A leg is furthest
 * forward at a quarter of its cycle and its knee only bends while it swings through, which is
 * what separates a walk from a march. The right side runs half a cycle behind the left, and an
 * arm goes with the opposite leg.
 */
export function gaitJoints(kind: 'walk' | 'run', phase: number): Joints {
  const left = phase * 2 * Math.PI;
  const right = left + Math.PI;
  if (kind === 'walk') {
    return {
      'leftHip.pitch': swing(25, 12, left), 'rightHip.pitch': swing(25, 12, right),
      'leftKnee.bend': 45 * Math.max(0, Math.cos(left)), 'rightKnee.bend': 45 * Math.max(0, Math.cos(right)),
      'leftShoulder.pitch': swing(24, 16, right), 'rightShoulder.pitch': swing(24, 16, left),
      'leftElbow.bend': 12 + 6 * Math.sin(right), 'rightElbow.bend': 12 + 6 * Math.sin(left),
      'torso.yaw': 4 * Math.sin(left),
    };
  }
  // A runner never locks a knee: bent on landing, folded as the leg comes through.
  const knee = (theta: number) => 30 + 25 * Math.max(0, Math.sin(theta)) + 60 * Math.max(0, Math.cos(theta));
  return {
    'leftHip.pitch': swing(52, 26, left), 'rightHip.pitch': swing(52, 26, right),
    'leftKnee.bend': knee(left), 'rightKnee.bend': knee(right),
    'leftShoulder.pitch': 36 * Math.sin(right), 'rightShoulder.pitch': 36 * Math.sin(left),
    'leftShoulder.twist': 8, 'rightShoulder.twist': 8, 'leftShoulder.spread': -8, 'rightShoulder.spread': 8,
    'leftElbow.bend': 55 + 7 * Math.sin(right), 'rightElbow.bend': 55 + 7 * Math.sin(left),
    'leftHand.pitch': 12, 'rightHand.pitch': 12,
    'torso.yaw': 7 * Math.sin(left),
    'body.pitch': -14 + 2 * Math.sin(left * 2),
  };
}

/** Where in its cycle something that repeats `rate` times a second is at `t`. Nothing else may advance a cycle. */
export function cyclePhase(t: number, rate: number, offset = 0): number {
  const phase = (offset + t * rate) % 1;
  return phase < 0 ? phase + 1 : phase;
}

function gaitOf(pose: StagePose | null | undefined): 'walk' | 'run' | null {
  const posture = posePosture(pose?.preset);
  return posture === 'walk' || posture === 'run' ? posture : null;
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000 + 0;
}

/** A walk or run pose at `t`: the pose's own angles with the gait laid over the joints it drives. */
function strideOver(actor: StageActor, pose: StagePose | null, t: number): StagePose | null {
  const kind = actor.figure === 'mannequin' ? gaitOf(pose) : null;
  if (!kind || !pose) return pose;
  const joints: Joints = { ...jointsOf({ ...actor, pose }) };
  Object.entries(gaitJoints(kind, cyclePhase(t, GAIT_RATE[kind]))).forEach(([key, value]) => { joints[key] = round3(value); });
  return { ...pose, joints };
}

/**
 * The clip frame of a skinned figure at `t`. A clip runs from the first of the consecutive keys
 * that ask for it, so a sit-down keyed at 2 s starts sitting at 2 s, not at the top of the shot.
 */
function clipOver(actor: StageActor, pose: StagePose | null, poseKeys: ActorKey[], t: number): StagePose | null {
  if (actor.figure !== 'humanoid') return pose;
  const clipId = pose?.clip || clipForPosture(posePosture(pose?.preset) || actor.posture);
  const clip = humanoidClip(clipId);
  const reached = poseKeys.filter(key => key.time <= t);
  // Blending towards a key that asks for another clip shows that clip's opening frame until the key is reached.
  let started = reached.length && (reached[reached.length - 1].pose?.clip || '') !== clipId && pose?.clip ? t : 0;
  for (let index = reached.length - 1; index >= 0 && (reached[index].pose?.clip || '') === clipId; index -= 1) {
    started = index === 0 ? 0 : reached[index].time;
  }
  if (t <= started) return pose;
  const elapsed = (t - started) / clip.duration;
  const base = pose?.clip_phase ?? 0;
  const phase = clip.loop ? cyclePhase(elapsed, 1, base) : Math.min(1, base + elapsed);
  return { preset: pose?.preset || '', joints: pose?.joints || {}, clip: clipId, clip_phase: round3(phase) };
}

/**
 * `authored` leaves the gait and the running clip out: the pose as somebody keyed it, which is
 * what a new key has to record (a key that froze one frame of a stride would stop the walk).
 */
export function sampleActor(actor: StageActor, keys: ActorKey[] | undefined, t: number, authored = false): SampledActor {
  const strideAt = authored ? (_: StageActor, pose: StagePose | null) => pose : strideOver;
  const clipAt = authored ? (_: StageActor, pose: StagePose | null) => pose : clipOver;
  if (!keys?.length) return { position: actor.position, yaw_deg: actor.yaw_deg, pose: clipAt(actor, actor.pose ?? null, [], t) };
  // Each channel reads only the keys that speak about it: a pose key between two marks does not stop the walk.
  const placed = spanAt(keys.filter(key => key.position), t);
  const turned = spanAt(keys.filter(key => key.yaw_deg !== null && key.yaw_deg !== undefined), t);
  const poseKeys = keys.filter(key => key.pose);
  const posed = spanAt(poseKeys, t);
  const position: GroundPoint = placed
    ? [lerp(placed.from.position![0], placed.to.position![0], placed.weight), lerp(placed.from.position![1], placed.to.position![1], placed.weight)]
    : actor.position;
  const yaw = turned ? lerpYaw(turned.from.yaw_deg!, turned.to.yaw_deg!, turned.weight) : actor.yaw_deg;
  let pose: StagePose | null = actor.pose ?? null;
  if (posed) {
    const from = strideAt(actor, posed.from.pose!, t)!;
    const to = strideAt(actor, posed.to.pose!, t)!;
    // Two ends of one gait are still that gait in between; blendPose only names a preset at its ends.
    pose = posed.weight === 0 ? from : { ...blendPose(from, to, posed.weight), preset: from.preset === to.preset ? from.preset : '' };
  } else {
    pose = strideAt(actor, pose, t);
  }
  return { position, yaw_deg: yaw, pose: clipAt(actor, pose, poseKeys, t) };
}

/**
 * The shot at `t` seconds. `cameraId` is the lens being looked through: keys belong to the lens
 * that films the shot, so a candidate lens stays where it is.
 */
export function sampleShot(plan: StagePlan, shot: StageShot | undefined, t: number, cameraId?: string): ShotSample {
  const timeline = timelineOf(plan, shot?.shot_id);
  const time = Math.min(Math.max(0, Number.isFinite(t) ? t : 0), timeline.duration_s);
  const lensId = cameraId || shot?.camera_id;
  const camera = plan.cameras.find(item => item.id === lensId);
  const filming = Boolean(camera) && camera?.id === shot?.camera_id;
  const actors: Record<string, SampledActor> = {};
  actorsInShot(plan, shot).forEach(actor => { actors[actor.name] = sampleActor(actor, timeline.actors[actor.name], time); });
  return {
    camera: camera ? sampleCamera(filming ? cameraKeysOf(timeline, camera) : [], camera, parseAspect(plan.aspect_ratio), time) : null,
    actors,
  };
}

function sameNumbers(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/**
 * The plan as it is drawn at `t`: marks, per-shot overrides and the filming lens replaced by
 * their sampled values. Anything the sample leaves as it was keeps its identity, so a still
 * stage (no keys, t = 0) comes back as the very same plan.
 */
export function stagePlanAt(plan: StagePlan, shotId: number | null | undefined, t: number, cameraId?: string): StagePlan {
  const shot = plan.shots.find(item => item.shot_id === shotId);
  if (!shot) return plan;
  const sample = sampleShot(plan, shot, t, cameraId);
  const staged = new Map(actorsInShot(plan, shot).map(actor => [actor.name, actor]));
  const moved = new Set<string>();
  const actors = plan.actors.map(actor => {
    const now = sample.actors[actor.name];
    const was = staged.get(actor.name);
    if (!now || !was) return actor;
    if (sameNumbers(now.position, was.position) && now.yaw_deg === was.yaw_deg && JSON.stringify(now.pose ?? null) === JSON.stringify(was.pose ?? null)) return actor;
    moved.add(actor.name);
    return { ...actor, position: now.position, yaw_deg: now.yaw_deg, pose: now.pose, posture: was.posture };
  });
  const lensId = cameraId || shot.camera_id;
  let cameraMoved = false;
  const cameras = plan.cameras.map(camera => {
    const now = camera.id === lensId ? sample.camera : null;
    if (!now || (sameNumbers(now.position, camera.position) && sameNumbers(now.target, camera.target) && now.lens_mm === camera.lens_mm)) return camera;
    cameraMoved = true;
    return { ...camera, position: now.position, target: now.target, lens_mm: now.lens_mm, fov_deg: now.fov_deg };
  });
  if (!moved.size && !cameraMoved) return plan;
  return {
    ...plan, actors, cameras,
    // A re-mark wins over the mark when the cast is read, so whatever it pins has to move with the sample too.
    shots: plan.shots.map(item => (item.shot_id !== shot.shot_id ? item : {
      ...item,
      overrides: item.overrides.map(override => {
        const now = moved.has(override.name) ? sample.actors[override.name] : undefined;
        if (!now) return override;
        return {
          ...override,
          ...(override.position ? { position: now.position } : {}),
          ...(override.yaw_deg !== null && override.yaw_deg !== undefined ? { yaw_deg: now.yaw_deg } : {}),
          ...(override.pose ? { pose: now.pose } : {}),
        };
      }),
    })),
  };
}

export interface CameraPath {
  /** The lens position along the shot, evenly spaced in time. */
  points: SpacePoint[];
  keys: Array<{ time: number; position: SpacePoint }>;
}

/** Where the filming lens travels during the shot; `null` when it does not move at all. */
export function cameraPathOf(plan: StagePlan, shot: StageShot | undefined, steps = 48): CameraPath | null {
  const camera = plan.cameras.find(item => item.id === shot?.camera_id);
  if (!shot || !camera) return null;
  const timeline = timelineOf(plan, shot.shot_id);
  const keys = cameraKeysOf(timeline, camera);
  if (keys.length < 2) return null;
  const aspect = parseAspect(plan.aspect_ratio);
  const points = Array.from({ length: steps + 1 }, (_, index) => sampleCamera(keys, camera, aspect, (timeline.duration_s * index) / steps).position);
  return { points, keys: keys.map(key => ({ time: key.time, position: key.position })) };
}
