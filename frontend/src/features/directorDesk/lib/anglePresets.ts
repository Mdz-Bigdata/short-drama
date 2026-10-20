import type { GroundPoint, SpacePoint, StageActor } from '../../spatial/spatialTypes';
import { round2, verticalFov } from './stageMath';

// Quick candidate lenses around the shot's subjects. Distance comes from the film-back equation
// (ported from mangfufu/director-desk, MIT): how far back a lens must stand for a given height
// of the world to fill a given share of the frame.

export type AnglePresetId = 'front' | 'side' | 'over_shoulder' | 'high' | 'low' | 'close_up';

export interface AnglePreset {
  id: AnglePresetId;
  label: string;
}

export interface CameraPlacement {
  label: string;
  position: SpacePoint;
  target: SpacePoint;
  lens_mm: number;
}

export const ANGLE_PRESETS: AnglePreset[] = [
  { id: 'front', label: '正面' }, { id: 'side', label: '侧面' }, { id: 'over_shoulder', label: '过肩' },
  { id: 'high', label: '俯拍' }, { id: 'low', label: '仰拍' }, { id: 'close_up', label: '特写' },
];

type Subject = Pick<StageActor, 'name' | 'position' | 'yaw_deg' | 'height_m'>;

const FILL = 0.8;
const MIN_DISTANCE_M = 0.6;
const MIN_CAMERA_HEIGHT_M = 0.25;

function normalize(vector: GroundPoint, fallback: GroundPoint): GroundPoint {
  const length = Math.hypot(vector[0], vector[1]);
  return length > 1e-6 ? [vector[0] / length, vector[1] / length] : fallback;
}

function rotate(vector: GroundPoint, degrees: number): GroundPoint {
  const radians = (degrees * Math.PI) / 180;
  return [vector[0] * Math.cos(radians) + vector[1] * Math.sin(radians), -vector[0] * Math.sin(radians) + vector[1] * Math.cos(radians)];
}

/** Distance at which `worldHeight` metres fill `fill` of a frame `fovDeg` tall. */
export function framingDistance(worldHeight: number, fovDeg: number, fill = FILL): number {
  return worldHeight / fill / (2 * Math.tan((fovDeg * Math.PI) / 360));
}

/**
 * Where the subjects face, as one direction. Two people facing each other cancel out, and then
 * the lens belongs on the perpendicular of the line between them — the side nearer +Z, which is
 * where the planner's master camera stands.
 */
export function facingOf(subjects: Subject[]): GroundPoint {
  const sum = subjects.reduce<GroundPoint>((total, actor) => {
    const radians = (actor.yaw_deg * Math.PI) / 180;
    return [total[0] + Math.sin(radians), total[1] + Math.cos(radians)];
  }, [0, 0]);
  if (Math.hypot(sum[0], sum[1]) > 0.3 * subjects.length) return normalize(sum, [0, 1]);
  if (subjects.length < 2) return [0, 1];
  const first = subjects[0].position;
  const last = subjects[subjects.length - 1].position;
  const across = normalize([last[0] - first[0], last[1] - first[1]], [1, 0]);
  const perpendicular: GroundPoint = [-across[1], across[0]];
  return perpendicular[1] >= 0 ? perpendicular : [-perpendicular[0], -perpendicular[1]];
}

function place(center: GroundPoint, targetY: number, direction: GroundPoint, distance: number, pitchDeg: number): SpacePoint {
  const pitch = (pitchDeg * Math.PI) / 180;
  const reach = Math.max(MIN_DISTANCE_M, distance);
  return [
    round2(center[0] + direction[0] * reach * Math.cos(pitch)),
    round2(Math.max(MIN_CAMERA_HEIGHT_M, targetY + reach * Math.sin(pitch))),
    round2(center[1] + direction[1] * reach * Math.cos(pitch)),
  ];
}

/**
 * A candidate lens for `preset` on `subjects`; `others` are the rest of the cast (an over-shoulder
 * of one person shoots past whoever stands nearest). `null` when there is nobody to frame.
 */
export function anglePresetCamera(preset: AnglePresetId, subjects: Subject[], aspect: number, others: Subject[] = []): CameraPlacement | null {
  if (!subjects.length) return null;
  const label = ANGLE_PRESETS.find(item => item.id === preset)?.label ?? preset;
  const center: GroundPoint = [
    subjects.reduce((sum, actor) => sum + actor.position[0], 0) / subjects.length,
    subjects.reduce((sum, actor) => sum + actor.position[1], 0) / subjects.length,
  ];
  const tallest = Math.max(...subjects.map(actor => actor.height_m));
  const spread = Math.max(0, ...subjects.map(actor => Math.hypot(actor.position[0] - center[0], actor.position[1] - center[1]))) * 2;
  const facing = facingOf(subjects);
  const distanceFor = (lens: number, worldHeight: number, worldWidth: number) => {
    const fov = verticalFov(lens, aspect);
    // Whichever of height and width runs out of frame first decides how far back the lens stands.
    return Math.max(framingDistance(worldHeight, fov), framingDistance(worldWidth / aspect, fov));
  };
  const build = (lens: number, targetY: number, direction: GroundPoint, distance: number, pitch: number, origin = center): CameraPlacement => ({
    label, lens_mm: lens, target: [round2(origin[0]), round2(targetY), round2(origin[1])], position: place(origin, targetY, direction, distance, pitch),
  });

  if (preset === 'over_shoulder') {
    const far = subjects[0];
    const near = subjects[1] ?? [...others].sort((a, b) => (
      Math.hypot(a.position[0] - far.position[0], a.position[1] - far.position[1]) - Math.hypot(b.position[0] - far.position[0], b.position[1] - far.position[1])
    ))[0];
    // Nobody to shoot past: a three-quarter front is the closest honest substitute.
    if (!near) return build(50, far.height_m * 0.85, rotate(facingOf([far]), 35), distanceFor(50, far.height_m * 0.55, 0.8), 0, far.position);
    const toward = normalize([far.position[0] - near.position[0], far.position[1] - near.position[1]], [0, 1]);
    const right: GroundPoint = [toward[1], -toward[0]];
    return {
      label, lens_mm: 50,
      position: [round2(near.position[0] - toward[0] * 0.9 + right[0] * 0.45), round2(near.height_m * 0.92), round2(near.position[1] - toward[1] * 0.9 + right[1] * 0.45)],
      target: [round2(far.position[0]), round2(far.height_m * 0.88), round2(far.position[1])],
    };
  }
  switch (preset) {
    case 'side':
      return build(35, tallest / 2, rotate(facing, 90), distanceFor(35, tallest, spread + 1), 0);
    case 'high':
      return build(28, tallest / 2, facing, distanceFor(28, tallest, spread + 1), 50);
    case 'low': {
      const distance = distanceFor(28, tallest, spread + 1);
      const placement = build(28, tallest * 0.9, facing, distance, 0);
      return { ...placement, position: [placement.position[0], 0.35, placement.position[2]] };
    }
    case 'close_up': {
      const hero = subjects[0];
      return build(85, hero.height_m * 0.9, rotate(facingOf([hero]), 20), distanceFor(85, 0.45, 0.4), 0, hero.position);
    }
    default:
      return build(35, tallest / 2, facing, distanceFor(35, tallest, spread + 1), 0);
  }
}
