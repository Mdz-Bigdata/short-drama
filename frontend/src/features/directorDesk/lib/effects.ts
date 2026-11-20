import type { GroundPoint, StageEffect, StageOperation, StagePlan } from '../../spatial/spatialTypes';
import type { SelectionRef } from '../deskTypes';

/**
 * 特效占位：导演在地面上手动放的特效标记（哪里炸、多大范围、谁发出的），给白模站位图和三维视图画圈用。
 * 只是预演占位，不模拟。种类、默认半径和圈数跟服务器的 action_marks.json 一致（effects.test.ts 逐项比对）。
 */
export interface EffectKind {
  id: string;
  label: string;
  radius: number;
  rings: number;
}

export const EFFECT_KINDS: EffectKind[] = [
  { id: 'blast', label: '爆炸', radius: 3, rings: 3 },
  { id: 'shock', label: '冲击波', radius: 3, rings: 3 },
  { id: 'fire', label: '火焰', radius: 1.5, rings: 2 },
  { id: 'bolt', label: '闪电', radius: 1.5, rings: 2 },
  { id: 'energy', label: '能量', radius: 2, rings: 3 },
  { id: 'dust', label: '烟尘', radius: 2.5, rings: 2 },
  { id: 'collapse', label: '坍塌', radius: 2.5, rings: 2 },
  { id: 'debris', label: '碎片', radius: 2, rings: 2 },
  { id: 'crack', label: '裂纹', radius: 1, rings: 1 },
  { id: 'impact', label: '冲击点', radius: 0.6, rings: 1 },
];

export const EFFECT_RADIUS = { low: 0.2, high: 30 };
export const EFFECT_COLOR = '#C0392B';
export const MAX_EFFECTS = 40;

export const kindOf = (id: string): EffectKind => EFFECT_KINDS.find(item => item.id === id) ?? EFFECT_KINDS[0];

/** What the marker is called on the stage: its own note, else its kind. */
export const effectName = (effect: Pick<StageEffect, 'kind' | 'note'>) => effect.note || kindOf(effect.kind).label;

/** Mirrors the server's rings_for: the kind's rings, fewer when the range is under a metre a ring. */
export function ringCount(kind: string, radius: number): number {
  return Math.max(1, Math.min(kindOf(kind).rings, Math.floor(radius) || 1));
}

export function effectsOf(plan: Pick<StagePlan, 'effects'>): StageEffect[] {
  return plan.effects ?? [];
}

/** The markers that are on in `shotId`, in stored order: the order the diagram numbers them in. */
export function effectsOn(plan: Pick<StagePlan, 'effects'>, shotId: number | undefined): StageEffect[] {
  return effectsOf(plan).filter(effect => !effect.shot_ids.length || (shotId !== undefined && effect.shot_ids.includes(shotId)));
}

/** VFX-01, VFX-02 … as the blocking diagram numbers the markers of a shot. */
export const effectNumber = (index: number) => `VFX-${String(index + 1).padStart(2, '0')}`;

export function nextEffectId(effects: StageEffect[]): string {
  const numbers = effects.map(effect => /^effect-(\d+)$/.exec(effect.id)?.[1]).filter(Boolean).map(Number);
  return `effect-${String(Math.max(0, ...numbers) + 1).padStart(2, '0')}`;
}

/** The operation that makes `effect` exactly as it is: what an undo sends to bring one back. */
export function effectOperation(effect: StageEffect): StageOperation {
  return {
    op: 'set_effect', id: effect.id, kind: effect.kind, position: effect.position, radius_m: effect.radius_m,
    source: effect.source, note: effect.note, shot_ids: effect.shot_ids,
  };
}

const clampRadius = (value: number) => Math.round(Math.min(EFFECT_RADIUS.high, Math.max(EFFECT_RADIUS.low, value)) * 100) / 100;

/** Mirrors the server's set_effect: a new marker, or the one with this id changed; what the operation leaves out is kept. */
export function setEffect(plan: StagePlan, op: StageOperation): StagePlan {
  const effects = effectsOf(plan);
  const id = String(op.id || '');
  const held = effects.find(item => item.id === id);
  const kind = String(op.kind || held?.kind || '');
  if (!EFFECT_KINDS.some(item => item.id === kind)) return plan;
  if (!held && (!Array.isArray(op.position) || effects.length >= MAX_EFFECTS)) return plan;
  const source = 'source' in op ? String(op.source || '') : held?.source ?? '';
  if (source && !plan.actors.some(actor => actor.name === source)) return plan;
  const radius = op.radius_m !== undefined && op.radius_m !== null
    ? Number(op.radius_m)
    : held && !('kind' in op) ? held.radius_m : kindOf(kind).radius;
  if (!Number.isFinite(radius) || radius < EFFECT_RADIUS.low || radius > EFFECT_RADIUS.high) return plan;
  const effect: StageEffect = {
    id: held ? held.id : id || nextEffectId(effects), kind,
    position: (Array.isArray(op.position) ? op.position : held!.position) as GroundPoint,
    radius_m: clampRadius(radius), source,
    note: 'note' in op ? String(op.note ?? '').trim().slice(0, 40) : held?.note ?? '',
    shot_ids: 'shot_ids' in op ? [...new Set((op.shot_ids as number[] | null) ?? [])].sort((a, b) => a - b) : held?.shot_ids ?? [],
  };
  return { ...plan, effects: held ? effects.map(item => (item.id === held.id ? effect : item)) : [...effects, effect] };
}

/** Mirrors the server's remove_effect. */
export function removeEffect(plan: StagePlan, op: StageOperation): StagePlan {
  const effects = effectsOf(plan);
  return effects.some(item => item.id === op.id) ? { ...plan, effects: effects.filter(item => item.id !== op.id) } : plan;
}

/** The puck at a marker's centre that the pointer grabs, in metres. */
export const EFFECT_HANDLE_RADIUS = 0.16;
const STAGE_REACH = 500;

/**
 * Where a marker's centre is while it is dragged: it keeps the offset it was grabbed at (the puck does
 * not jump under the pointer), then snaps to the grid when the desk snaps, and stays on the stage.
 */
export function draggedCentre(start: GroundPoint, grab: GroundPoint, now: GroundPoint, snap: { grid: boolean; gridSize: number }): GroundPoint {
  const step = snap.grid && snap.gridSize > 0 ? snap.gridSize : 0;
  const settle = (value: number) => {
    const snapped = step ? Math.round(value / step) * step : value;
    return Math.round(Math.min(STAGE_REACH, Math.max(-STAGE_REACH, snapped)) * 100) / 100;
  };
  return [settle(start[0] + now[0] - grab[0]), settle(start[1] + now[1] - grab[1])];
}

/** The edit a drag ends in, or `null` when the marker is where it started (a click, or a drag back). */
export function effectMove(effect: Pick<StageEffect, 'id' | 'position'>, position: GroundPoint): StageOperation | null {
  if (position[0] === effect.position[0] && position[1] === effect.position[1]) return null;
  return { op: 'set_effect', id: effect.id, position };
}

/** A circle of `radius` on the floor as 3D points, closed, for a line. */
export function floorRing(center: GroundPoint, radius: number, lift = 0.03, samples = 64): Array<[number, number, number]> {
  const points: Array<[number, number, number]> = [];
  for (let index = 0; index <= samples; index += 1) {
    const angle = (2 * Math.PI * index) / samples;
    points.push([center[0] + Math.cos(angle) * radius, lift, center[1] + Math.sin(angle) * radius]);
  }
  return points;
}

const round = (value: number) => Math.round(value * 100) / 100;

/** Where a new marker goes: a metre in front of the selected character, on the selected piece, else the middle of the cast. */
export function placeFor(plan: StagePlan, selection: SelectionRef[]): { position: GroundPoint; source: string } {
  const picked = selection[0];
  if (picked?.kind === 'actor') {
    const actor = plan.actors.find(item => item.name === picked.name);
    if (actor) {
      const yaw = (actor.yaw_deg * Math.PI) / 180;
      return { position: [round(actor.position[0] + Math.sin(yaw)), round(actor.position[1] + Math.cos(yaw))], source: actor.crowd_id ? '' : actor.name };
    }
  }
  if (picked?.kind === 'landmark') {
    const piece = plan.landmarks.find(item => item.name === picked.name);
    if (piece) return { position: [round(piece.position[0]), round(piece.position[1])], source: '' };
  }
  const cast = plan.actors.filter(actor => !actor.crowd_id);
  if (!cast.length) return { position: [0, 0], source: '' };
  return {
    position: [round(cast.reduce((sum, actor) => sum + actor.position[0], 0) / cast.length), round(cast.reduce((sum, actor) => sum + actor.position[1], 0) / cast.length)],
    source: '',
  };
}
