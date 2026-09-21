import type { GroundPoint, StageActor, StageCrowd, StagePlan } from '../../spatial/spatialTypes';

// Mirrors backend geometry.py: a full-frame sensor whose long side follows the frame's long side.
const SENSOR_LONG_SIDE_MM = 36;

export function round2(value: number): number {
  // `+ 0` turns -0 into 0: a negative zero would otherwise travel into a PATCH body as "-0".
  return Math.round(value * 100) / 100 + 0;
}

export function verticalFov(lensMm: number, aspect: number): number {
  const lens = Math.max(1, lensMm);
  const sensorHeight = aspect < 1 ? SENSOR_LONG_SIDE_MM : SENSOR_LONG_SIDE_MM / Math.max(aspect, 1e-6);
  return (2 * Math.atan(sensorHeight / (2 * lens)) * 180) / Math.PI;
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
