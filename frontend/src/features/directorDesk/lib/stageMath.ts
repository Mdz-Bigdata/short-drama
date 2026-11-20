import type { GroundPoint, StageActor, StageCrowd, StagePlan } from '../../spatial/spatialTypes';
import { visibleActors } from './visibleActors';

// Mirrors backend geometry.py: a sensor (full frame unless the camera says otherwise) whose long side follows the frame's long side.
const SENSOR_LONG_SIDE_MM = 36;

export function round2(value: number): number {
  // `+ 0` turns -0 into 0: a negative zero would otherwise travel into a PATCH body as "-0".
  return Math.round(value * 100) / 100 + 0;
}

export function verticalFov(lensMm: number, aspect: number, sensorMm: number = SENSOR_LONG_SIDE_MM): number {
  const lens = Math.max(1, lensMm);
  const sensorHeight = aspect < 1 ? sensorMm : sensorMm / Math.max(aspect, 1e-6);
  return (2 * Math.atan(sensorHeight / (2 * lens)) * 180) / Math.PI;
}

/** How far the set and cast spread on the floor: enough to aim a view at all of it, or to size its shadows. */
export function stageReach(plan: { actors: ReadonlyArray<Pick<StageActor, 'position'>>; landmarks: StagePlan['landmarks'] }): { center: GroundPoint; radius: number } {
  const points: Array<[number, number, number]> = [
    ...plan.actors.map(actor => [actor.position[0], actor.position[1], 1] as [number, number, number]),
    ...plan.landmarks.map(item => [item.position[0], item.position[1], Math.hypot(item.size[0], item.size[1]) / 2] as [number, number, number]),
  ];
  if (!points.length) return { center: [0, 0], radius: 6 };
  const left = Math.min(...points.map(([x, , r]) => x - r));
  const right = Math.max(...points.map(([x, , r]) => x + r));
  const near = Math.min(...points.map(([, z, r]) => z - r));
  const far = Math.max(...points.map(([, z, r]) => z + r));
  return { center: [(left + right) / 2, (near + far) / 2], radius: Math.max(2, Math.hypot(right - left, far - near) / 2) };
}

/**
 * What the key light covers while shot `shotId` plays: the set, the cast where they stand now, and
 * every place a key of the shot moves someone to. Moves run between keys, so the reach (and the
 * shadows sized from it) holds still for the whole shot instead of stepping as people walk.
 */
export function lightReach(plan: StagePlan, shotId: number | undefined, actors: ReadonlyArray<Pick<StageActor, 'position'>>): { center: GroundPoint; radius: number } {
  const keys = shotId === undefined ? undefined : plan.timelines?.[String(shotId)]?.actors;
  const keyed = Object.values(keys || {}).flatMap(track => track.flatMap(key => (key.position ? [{ position: key.position }] : [])));
  return stageReach({ actors: [...actors, ...keyed], landmarks: plan.landmarks });
}

/**
 * What the plan and elevation panes take in: the set and the cast of shot `shotId` where they
 * stand in `plan` (their marks, or the shot's re-marks), leaving out whatever is hidden. Given the
 * plan as stored rather than as played, the panes hold still while a shot plays.
 */
export function paneReach(plan: StagePlan, shotId: number | undefined, hidden: string[]): { center: GroundPoint; radius: number } {
  const shot = plan.shots.find(item => item.shot_id === shotId);
  return stageReach({
    actors: visibleActors(plan, shot, hidden),
    landmarks: plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`)),
  });
}

/** The key light and the box its shadows are computed in. */
export interface ShadowRig {
  /** Half the side of the square the shadow map covers, in metres. */
  span: number;
  position: [number, number, number];
  target: [number, number, number];
  far: number;
}

/**
 * Where the key light stands so its shadow map covers a set of `reach` metres around `center`.
 * The light keeps one direction; the centre moves in whole metres and the span in whole metres too,
 * so dragging a prop does not re-aim the light (and shimmer every shadow) on each pointer move.
 */
export function shadowRig(reach: number, center: GroundPoint = [0, 0]): ShadowRig {
  // One metre more than the set needs: the rounded centre can sit up to 0.71 m off the real one.
  const span = Math.max(12, Math.ceil(reach * 1.3 + 1));
  const x = Math.round(center[0]) + 0;
  const z = Math.round(center[1]) + 0;
  return { span, position: [x + span * 0.55, span * 0.9, z + span * 0.4], target: [x, 0, z], far: span * 4 };
}

export function normalizeYaw(degrees: number): number {
  const wrapped = ((degrees + 180) % 360 + 360) % 360 - 180;
  return round2(wrapped === -180 ? 180 : wrapped);
}

export function distance2(a: GroundPoint, b: GroundPoint): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function crowdMembers(plan: Pick<StagePlan, 'actors'>, crowdId: string): StageActor[] {
  return crowdId ? plan.actors.filter(actor => actor.crowd_id === crowdId) : [];
}

export function crowdIds(plan: Pick<StagePlan, 'actors'>): string[] {
  return [...new Set(plan.actors.map(actor => actor.crowd_id || '').filter(Boolean))];
}

/**
 * The array's own record. A plan written before crowds were recorded has members but no record,
 * so the layout is then read back off the members: their centroid, the first one's facing, and
 * the closest pair of neighbours.
 */
export function crowdOf(plan: Pick<StagePlan, 'actors' | 'crowds'>, crowdId: string): StageCrowd | null {
  const recorded = plan.crowds?.find(crowd => crowd.id === crowdId);
  if (recorded) return recorded;
  const members = crowdMembers(plan, crowdId);
  if (!members.length) return null;
  let spacing = Infinity;
  for (let i = 0; i < members.length; i += 1) {
    for (let j = i + 1; j < members.length; j += 1) spacing = Math.min(spacing, distance2(members[i].position, members[j].position));
  }
  return {
    id: crowdId, label: crowdId, rows: 1, columns: members.length, seed: 0, body_type: members[0].body_type || 'standard',
    center: [
      round2(members.reduce((sum, actor) => sum + actor.position[0], 0) / members.length),
      round2(members.reduce((sum, actor) => sum + actor.position[1], 0) / members.length),
    ],
    yaw_deg: members[0].yaw_deg,
    spacing: Number.isFinite(spacing) && spacing > 0 ? round2(spacing) : 1,
  };
}

export function rotateAbout(point: GroundPoint, center: GroundPoint, degrees: number): GroundPoint {
  // Yaw turns +Z toward +X, the same handedness as forward = (sin yaw, cos yaw).
  const radians = (degrees * Math.PI) / 180;
  const dx = point[0] - center[0];
  const dz = point[1] - center[1];
  return [
    round2(center[0] + dx * Math.cos(radians) + dz * Math.sin(radians)),
    round2(center[1] - dx * Math.sin(radians) + dz * Math.cos(radians)),
  ];
}
