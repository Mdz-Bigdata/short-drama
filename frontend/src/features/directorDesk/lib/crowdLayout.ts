import type { StageActor, StageCrowd } from '../../spatial/spatialTypes';

// A line-for-line port of backend spatial_stage/crowds.py, so the desk can draw a new crowd the
// moment it is asked for: the same seed gives the same people on both sides. Each member draws
// four numbers, in this order: sideways offset, depth offset, turn, height.

const POSITION_JITTER = 0.18;
const YAW_JITTER_DEG = 12;
const HEIGHT_JITTER = 0.04;
const BASE_HEIGHT_M = 1.7;

const round3 = (value: number) => Math.round(value * 1000) / 1000 + 0;

export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1) >>> 0;
    value = (value ^ ((value + (Math.imul(value ^ (value >>> 7), value | 61) >>> 0)) >>> 0)) >>> 0;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function wrapYaw(degrees: number): number {
  const wrapped = ((degrees + 180) % 360 + 360) % 360 - 180;
  return round3(wrapped === -180 ? 180 : wrapped);
}

/** The people of `crowd`, front row first, each row from the array's left to its right. */
export function crowdMembersOf(crowd: StageCrowd): StageActor[] {
  const radians = (crowd.yaw_deg * Math.PI) / 180;
  const forward: [number, number] = [Math.sin(radians), Math.cos(radians)];
  const right: [number, number] = [-forward[1], forward[0]];
  return Array.from({ length: crowd.rows * crowd.columns }, (_, index) => {
    const row = Math.floor(index / crowd.columns);
    const column = index % crowd.columns;
    const draw = mulberry32(crowd.seed + index);
    const along = (column - (crowd.columns - 1) / 2 + (draw() * 2 - 1) * POSITION_JITTER) * crowd.spacing;
    const back = (row - (crowd.rows - 1) / 2 + (draw() * 2 - 1) * POSITION_JITTER) * crowd.spacing;
    const turn = (draw() * 2 - 1) * YAW_JITTER_DEG;
    const height = BASE_HEIGHT_M * (1 + (draw() * 2 - 1) * HEIGHT_JITTER);
    return {
      id: `${crowd.id}-${String(index + 1).padStart(3, '0')}`,
      name: `${crowd.label}-${String(index + 1).padStart(2, '0')}`,
      position: [round3(crowd.center[0] + right[0] * along - forward[0] * back), round3(crowd.center[1] + right[1] * along - forward[1] * back)],
      yaw_deg: wrapYaw(crowd.yaw_deg + turn), height_m: round3(height), posture: 'stand', role: 'crowd', screen_side: 'center',
      body_type: crowd.body_type, crowd_id: crowd.id,
    };
  });
}

/** The id the server will give the next crowd: one past the highest `crowd-NN` on stage. */
export function nextCrowdId(crowds: StageCrowd[]): string {
  const highest = Math.max(0, ...crowds.map(crowd => Number(crowd.id.replace(/^crowd-/, '').split('-')[0])).filter(Number.isInteger));
  return `crowd-${String(highest + 1).padStart(2, '0')}`;
}
