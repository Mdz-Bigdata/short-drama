// The monitor wall and the 成片预演 clock: which frames the wall shows, and how a scene of shots
// plays as one strip of time. Pure, so both can be checked without a canvas.

import { FUNCTION_LABELS, type StageCamera, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import type { ResolveOptions } from './contacts';
import { cutCameraAt, stagePlanAt, timelineOf } from './sampling';
import { visibleActors } from './visibleActors';

export type MonitorRole = 'shot' | 'cut' | 'candidate' | 'filming';

export interface Monitor {
  /** Stable while the shot and lens stay the same, so a thumbnail can be kept until its picture changes. */
  key: string;
  shotId: number;
  cameraId: string;
  role: MonitorRole;
  /** 「第 3 镜｜过肩 · 林夏」 for a shot, the lens's own label for one of the current shot's other lenses. */
  title: string;
  /** The lens and its focal length. */
  detail: string;
  /** The stage as this monitor sees it. */
  plan: StagePlan;
  shot: StageShot;
  camera: StageCamera;
  /** Changes exactly when what this monitor would draw changes. */
  signature: string;
}

export function shotTitle(shot: StageShot): string {
  const who = shot.subjects.length ? ` · ${shot.subjects.join('、')}` : '';
  return `第 ${shot.shot_id} 镜｜${FUNCTION_LABELS[shot.function] ?? shot.function}${who}`;
}

function lensDetail(camera: StageCamera): string {
  return `${camera.label || camera.id} · ${camera.lens_mm}mm`;
}

function signatureOf(plan: StagePlan, shot: StageShot, camera: StageCamera, hidden: string[]): string {
  const props = plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`));
  return JSON.stringify([camera.position, camera.target, camera.fov_deg, visibleActors(plan, shot, hidden), props]);
}

/**
 * Every shot of the scene through the lens that films it, the current shot at the playhead and the
 * others at their first frame; under the current shot, its other lenses (a cut's, the candidates',
 * and the filming lens when a cut has it off screen right now).
 */
export function monitorsOf(
  plan: StagePlan, currentShotId: number | null | undefined, now: number, hidden: string[], options?: ResolveOptions,
): Monitor[] {
  const monitors: Monitor[] = [];
  for (const shot of plan.shots) {
    const current = shot.shot_id === currentShotId;
    const time = current ? now : 0;
    const staged = stagePlanAt(plan, shot.shot_id, time, undefined, options);
    const stagedShot = staged.shots.find(item => item.shot_id === shot.shot_id) ?? shot;
    const timeline = timelineOf(plan, shot.shot_id);
    const onScreen = cutCameraAt(timeline, time) || shot.camera_id;
    const camera = staged.cameras.find(item => item.id === onScreen);
    if (camera) {
      monitors.push({
        key: `shot:${shot.shot_id}`, shotId: shot.shot_id, cameraId: camera.id, role: 'shot', title: shotTitle(shot), detail: lensDetail(camera),
        plan: staged, shot: stagedShot, camera, signature: signatureOf(staged, stagedShot, camera, hidden),
      });
    }
    if (!current) continue;
    const cuts = (timeline.cuts ?? []).map(cut => cut.camera_id);
    const others: Array<[string, MonitorRole]> = [
      ...(onScreen !== shot.camera_id ? [[shot.camera_id, 'filming'] as [string, MonitorRole]] : []),
      ...cuts.map(id => [id, 'cut'] as [string, MonitorRole]),
      ...(shot.alt_camera_ids ?? []).map(id => [id, 'candidate'] as [string, MonitorRole]),
    ];
    const seen = new Set([onScreen]);
    for (const [id, role] of others) {
      if (seen.has(id)) continue;
      seen.add(id);
      const lens = staged.cameras.find(item => item.id === id);
      if (!lens) continue;
      monitors.push({
        key: `lens:${shot.shot_id}:${id}`, shotId: shot.shot_id, cameraId: id, role, title: lens.label || lens.id, detail: `${lens.lens_mm}mm`,
        plan: staged, shot: stagedShot, camera: lens, signature: signatureOf(staged, stagedShot, lens, hidden),
      });
    }
  }
  return monitors;
}

export interface SceneSegment {
  shotId: number;
  /** Where the shot starts on the scene's clock, in seconds. */
  start: number;
  duration: number;
  title: string;
}

/** The scene's shots laid end to end, in their order, each as long as its timeline. */
export function sceneSegments(plan: Pick<StagePlan, 'shots' | 'timelines'>): SceneSegment[] {
  let start = 0;
  return plan.shots.map(shot => {
    const duration = Math.max(0, timelineOf(plan, shot.shot_id).duration_s);
    const segment = { shotId: shot.shot_id, start, duration, title: shotTitle(shot) };
    start += duration;
    return segment;
  });
}

export function sceneDuration(segments: SceneSegment[]): number {
  const last = segments[segments.length - 1];
  return last ? last.start + last.duration : 0;
}

/** The shot a point on the scene clock falls in, and how far into it; the very end belongs to the last shot. */
export function locateInScene(segments: SceneSegment[], time: number): { shotId: number; time: number } | null {
  if (!segments.length) return null;
  const clamped = Math.min(Math.max(0, Number.isFinite(time) ? time : 0), sceneDuration(segments));
  const segment = segments.find(item => clamped < item.start + item.duration - 1e-9) ?? segments[segments.length - 1];
  return { shotId: segment.shotId, time: Math.min(segment.duration, Math.max(0, clamped - segment.start)) };
}

export function sceneTimeOf(segments: SceneSegment[], shotId: number | null | undefined, time: number): number {
  const segment = segments.find(item => item.shotId === shotId);
  return segment ? segment.start + Math.min(segment.duration, Math.max(0, time)) : 0;
}

/** The shot after this one, or `undefined` at the end of the scene. */
export function nextShotId(segments: SceneSegment[], shotId: number | null | undefined): number | undefined {
  const index = segments.findIndex(item => item.shotId === shotId);
  return index >= 0 ? segments[index + 1]?.shotId : undefined;
}

/** 01:07 */
export function clockText(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds + 1e-6));
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
}
