import type { GroundPoint, StageActor, StageCamera, StagePlan } from './spatialTypes';

// The floor plan is drawn the way the master camera looks at the stage: +X to the right and the
// camera side (+Z) at the bottom, so "screen left" of the master is the left of the drawing.

export interface FloorBounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
}

export interface FloorTransform {
  scale: number;
  toView: (point: GroundPoint) => [number, number];
  toWorld: (x: number, y: number) => GroundPoint;
}

const PADDING_M = 1.2;
const MIN_SPAN_M = 6;

export function floorBounds(plan: StagePlan, actors: StageActor[] = plan.actors): FloorBounds {
  const xs: number[] = [];
  const zs: number[] = [];
  const add = (x: number, z: number) => { xs.push(x); zs.push(z); };
  actors.forEach(actor => add(actor.position[0], actor.position[1]));
  plan.actors.forEach(actor => add(actor.position[0], actor.position[1]));
  plan.landmarks.forEach(item => add(item.position[0], item.position[1]));
  plan.cameras.forEach(camera => {
    add(camera.position[0], camera.position[2]);
    if (camera.move.end_position) add(camera.move.end_position[0], camera.move.end_position[2]);
  });
  if (xs.length === 0) add(0, 0);
  let minX = Math.min(...xs) - PADDING_M;
  let maxX = Math.max(...xs) + PADDING_M;
  let minZ = Math.min(...zs) - PADDING_M;
  let maxZ = Math.max(...zs) + PADDING_M;
  // A lone mark would otherwise be drawn at an absurd zoom.
  if (maxX - minX < MIN_SPAN_M) { const mid = (minX + maxX) / 2; minX = mid - MIN_SPAN_M / 2; maxX = mid + MIN_SPAN_M / 2; }
  if (maxZ - minZ < MIN_SPAN_M) { const mid = (minZ + maxZ) / 2; minZ = mid - MIN_SPAN_M / 2; maxZ = mid + MIN_SPAN_M / 2; }
  return { minX, maxX, minZ, maxZ };
}

export function floorTransform(bounds: FloorBounds, width: number, height: number): FloorTransform {
  const spanX = bounds.maxX - bounds.minX;
  const spanZ = bounds.maxZ - bounds.minZ;
  const scale = Math.min(width / spanX, height / spanZ);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanZ * scale) / 2;
  return {
    scale,
    toView: ([x, z]) => [offsetX + (x - bounds.minX) * scale, offsetY + (z - bounds.minZ) * scale],
    toWorld: (x, y) => [
      round((x - offsetX) / scale + bounds.minX),
      round((y - offsetY) / scale + bounds.minZ),
    ],
  };
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}

/** Yaw 0 faces +Z and forward = (sin yaw, cos yaw): the same convention as the backend and three.js. */
export function forwardOf(yawDegrees: number): GroundPoint {
  const radians = (yawDegrees * Math.PI) / 180;
  return [Math.sin(radians), Math.cos(radians)];
}

export function parseAspect(value: string): number {
  const [w, h] = value.replace('：', ':').split(':').map(Number);
  return w > 0 && h > 0 ? w / h : 9 / 16;
}

export function horizontalFov(camera: Pick<StageCamera, 'fov_deg' | 'aspect'>): number {
  const half = Math.tan((camera.fov_deg * Math.PI) / 360) * parseAspect(camera.aspect);
  return (2 * Math.atan(half) * 180) / Math.PI;
}

/** The ground footprint of what a camera sees: apex at the lens, opening by its horizontal field of view. */
export function cameraCone(camera: StageCamera, reach?: number, end = false): GroundPoint[] {
  const position = end && camera.move.end_position ? camera.move.end_position : camera.position;
  const target = end && camera.move.end_target ? camera.move.end_target : camera.target;
  const dx = target[0] - position[0];
  const dz = target[2] - position[2];
  const length = Math.hypot(dx, dz);
  if (length < 0.05) return [];   // looking straight down: no cone to draw
  const distance = reach ?? Math.max(length * 1.35, 1.5);
  const heading = Math.atan2(dx, dz);
  const half = (horizontalFov(camera) * Math.PI) / 360;
  return [
    [position[0], position[2]],
    [position[0] + Math.sin(heading - half) * distance, position[2] + Math.cos(heading - half) * distance],
    [position[0] + Math.sin(heading + half) * distance, position[2] + Math.cos(heading + half) * distance],
  ];
}

export function isOverhead(camera: StageCamera): boolean {
  const drop = camera.position[1] - camera.target[1];
  return drop > 0 && Math.hypot(camera.position[0] - camera.target[0], camera.position[2] - camera.target[2]) < 0.05 * drop;
}

export function yawToward(from: GroundPoint, to: GroundPoint): number {
  return round((Math.atan2(to[0] - from[0], to[1] - from[1]) * 180) / Math.PI);
}
