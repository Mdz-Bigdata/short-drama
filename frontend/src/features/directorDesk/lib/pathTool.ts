import { actorsInShot, type GroundPoint, type StageOperation, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { round2 } from './stageMath';

// A freehand stroke on the ground and what it becomes. The viewport hands over ground hits one at a
// time; this module decides which hits count, when a stroke is a route, who it belongs to and what
// is sent. Resampling and keying happen on the server (`set_path`), so nothing is applied locally.

/** Pointer jitter is below this; anything closer to the last point is the same point. */
export const MIN_POINT_SPACING_M = 0.05;
/** The server's limit on a route; past it the stroke keeps its first 400 points. */
export const MAX_PATH_POINTS = 400;
export const MIN_PATH_POINTS = 2;
/** The stage's limit on any coordinate; a hit further out is off the stage. */
export const STAGE_LIMIT_M = 500;

export type PathTarget =
  | { kind: 'actor'; name: string }
  /** `lookAt` is sent as `look_at`: the camera's first subject, or straight ahead along the route. */
  | { kind: 'camera'; id: string; lookAt: string };

/** `points` with `hit` on the end when it is worth keeping; the very same array otherwise, so a caller can skip a render. */
export function appendStrokePoint(points: GroundPoint[], hit: GroundPoint): GroundPoint[] {
  if (points.length >= MAX_PATH_POINTS) return points;
  if (!Number.isFinite(hit[0]) || !Number.isFinite(hit[1])) return points;
  const point: GroundPoint = [round2(hit[0]), round2(hit[1])];
  if (Math.abs(point[0]) > STAGE_LIMIT_M || Math.abs(point[1]) > STAGE_LIMIT_M) return points;
  const last = points[points.length - 1];
  if (last && Math.hypot(point[0] - last[0], point[1] - last[1]) < MIN_POINT_SPACING_M) return points;
  return [...points, point];
}

export function strokeFull(points: GroundPoint[]): boolean {
  return points.length >= MAX_PATH_POINTS;
}

/** A stroke that never left its first point is a click, not a route. */
export function strokeIsRoute(points: GroundPoint[]): boolean {
  return points.length >= MIN_PATH_POINTS;
}

type Resolution = { target: PathTarget; refusal: '' } | { target: null; refusal: string };

function resolve(plan: StagePlan | undefined, shot: StageShot | undefined, ref: SelectionRef | undefined): Resolution {
  const refuse = (refusal: string): Resolution => ({ target: null, refusal });
  if (!plan || !shot) return refuse('请先选择一个镜头');
  if (!ref) return refuse('先选择一个角色，或本镜的拍摄机位');
  switch (ref.kind) {
    case 'crowd':
      return refuse('群演阵列不能画走位：请选择一个主要角色');
    case 'landmark':
      return refuse('道具不能画路径：只有角色和本镜的拍摄机位可以');
    case 'camera-target':
      return refuse('请选择机位本身，而不是它的朝向点');
    case 'actor': {
      const actor = actorsInShot(plan, shot).find(item => item.name === ref.name);
      if (!actor) return refuse(`「${ref.name}」本镜不在场，无法画走位`);
      // A crowd member's keys would be overwritten by the next crowd re-layout, so the array stays as one piece.
      if (actor.crowd_id) return refuse('群演成员不能单独画走位');
      return { target: { kind: 'actor', name: actor.name }, refusal: '' };
    }
    default: {
      const camera = plan.cameras.find(item => item.id === ref.id);
      if (!camera) return refuse('这个机位不在方案里');
      if (camera.id !== shot.camera_id) {
        const name = camera.label || camera.id;
        // The server writes the filming camera's track whatever camera was selected; a candidate's route would land on
        // the wrong lens, so it is refused rather than silently redirected.
        return refuse(shot.alt_camera_ids?.includes(camera.id)
          ? `「${name}」是候选机位：路径只写入本镜拍摄机位的轨道，请先把它设为主机位`
          : `「${name}」不拍摄本镜：路径只能画给本镜的拍摄机位`);
      }
      return { target: { kind: 'camera', id: camera.id, lookAt: camera.subjects[0] || 'ahead' }, refusal: '' };
    }
  }
}

/** Who a drawn route in `shot` would belong to, or `null` when `ref` cannot take one. */
export function pathTargetOf(plan: StagePlan | undefined, shot: StageShot | undefined, ref: SelectionRef | undefined): PathTarget | null {
  return resolve(plan, shot, ref).target;
}

/** Why `ref` cannot take a drawn route in `shot`; '' when it can. */
export function pathRefusal(plan: StagePlan | undefined, shot: StageShot | undefined, ref: SelectionRef | undefined): string {
  return resolve(plan, shot, ref).refusal;
}

export function pathLabel(target: PathTarget): string {
  return target.kind === 'actor' ? `手绘走位：${target.name}` : '手绘机位路径';
}

/** The `set_path` operation for a route; camera points are 2-D, so the server keeps the lens at its current height. */
export function pathOperation(shotId: number, target: PathTarget, points: GroundPoint[]): StageOperation {
  if (target.kind === 'actor') return { op: 'set_path', shot_id: shotId, target: target.name, points };
  return { op: 'set_path', shot_id: shotId, target: 'camera', points, look_at: target.lookAt };
}

/** Sent alone (`barrier`): the server keys the route, and the desk takes the plan it returns. */
export function pathEdit(shotId: number, target: PathTarget, points: GroundPoint[]): EditRequest {
  return { operations: [pathOperation(shotId, target, points)], label: pathLabel(target), barrier: true };
}
