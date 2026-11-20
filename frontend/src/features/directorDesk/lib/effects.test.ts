import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import type { StageEffect, StageOperation, StagePlan } from '../../spatial/spatialTypes';
import { applyAll, inverseOf } from '../deskOperations';
import {
  EFFECT_COLOR, EFFECT_KINDS, EFFECT_RADIUS, draggedCentre, effectMove, effectName, effectNumber, effectOperation, effectsOn, floorRing, nextEffectId,
  removeEffect, ringCount, setEffect,
} from './effects';

const MARK: StageEffect = { id: 'effect-01', kind: 'shock', position: [1, 0], radius_m: 3, source: '林夏', note: '', shot_ids: [] };
const stage = (effects: StageEffect[] = []): StagePlan => contactPlan({ effects });

describe('effect markers', () => {
  it('keeps the kinds, sizes, radius range and colour the server uses', () => {
    const data = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/data/prompt/action_marks.json'), 'utf8'));
    const kinds = Object.entries(data.effect_kinds as Record<string, { name: string; radius_m: number; rings: number }>)
      .map(([id, item]) => ({ id, label: item.name, radius: item.radius_m, rings: item.rings }));
    expect([...EFFECT_KINDS].sort((a, b) => a.id.localeCompare(b.id))).toEqual(kinds.sort((a, b) => a.id.localeCompare(b.id)));
    expect(EFFECT_RADIUS).toEqual(data.effect_radius);
    expect(EFFECT_COLOR).toBe(data.effect_color.hex);
    expect(data.ring_step_m).toBe(1);
  });

  it('places a marker with the id it was given and changes one without losing what the edit leaves out', () => {
    const placed = setEffect(stage(), { op: 'set_effect', id: 'effect-01', kind: 'fire', position: [2, 1], radius_m: 1.5, source: '', note: '', shot_ids: [2] });
    expect(placed.effects).toEqual([{ id: 'effect-01', kind: 'fire', position: [2, 1], radius_m: 1.5, source: '', note: '', shot_ids: [2] }]);
    const moved = setEffect(stage([MARK]), { op: 'set_effect', id: 'effect-01', position: [0, -2] });
    expect(moved.effects![0]).toEqual({ ...MARK, position: [0, -2] });
    // A new kind brings its own size; an empty sender clears it.
    const other = setEffect(stage([{ ...MARK, radius_m: 5 }]), { op: 'set_effect', id: 'effect-01', kind: 'crack', source: '' });
    expect(other.effects![0]).toMatchObject({ kind: 'crack', radius_m: 1, source: '' });
  });

  it('leaves the plan alone when the server would refuse', () => {
    const plan = stage([MARK]);
    for (const op of [
      { op: 'set_effect', id: 'effect-02', kind: 'tornado', position: [0, 0] },
      { op: 'set_effect', id: 'effect-02', kind: 'fire' },
      { op: 'set_effect', id: 'effect-01', radius_m: 99 },
      { op: 'set_effect', id: 'effect-01', source: '路人' },
    ] as StageOperation[]) expect(setEffect(plan, op)).toBe(plan);
    expect(removeEffect(plan, { op: 'remove_effect', id: 'effect-09' })).toBe(plan);
    expect(removeEffect(plan, { op: 'remove_effect', id: 'effect-01' }).effects).toEqual([]);
  });

  it('undoes a placement, a change and a removal', () => {
    const empty = stage();
    const place: StageOperation[] = [effectOperation(MARK)];
    const placed = applyAll(empty, place);
    expect(inverseOf(empty, place)).toEqual([{ op: 'remove_effect', id: 'effect-01' }]);
    expect(applyAll(placed, inverseOf(empty, place)!).effects).toEqual([]);

    const change: StageOperation[] = [{ op: 'set_effect', id: 'effect-01', radius_m: 1.2, shot_ids: [1] }];
    const changed = applyAll(placed, change);
    expect(changed.effects![0]).toMatchObject({ radius_m: 1.2, shot_ids: [1] });
    expect(applyAll(changed, inverseOf(placed, change)!).effects).toEqual([MARK]);

    const remove: StageOperation[] = [{ op: 'remove_effect', id: 'effect-01' }];
    expect(applyAll(applyAll(placed, remove), inverseOf(placed, remove)!).effects).toEqual([MARK]);
    expect(inverseOf(empty, remove)).toEqual([]);
  });

  it('numbers the markers of a shot in stored order and names them', () => {
    const plan = stage([MARK, { ...MARK, id: 'effect-02', kind: 'fire', shot_ids: [2], note: '掌风' }, { ...MARK, id: 'effect-05', shot_ids: [1] }]);
    expect(effectsOn(plan, 1).map(item => item.id)).toEqual(['effect-01', 'effect-05']);
    expect(effectsOn(plan, 2).map(item => item.id)).toEqual(['effect-01', 'effect-02']);
    expect(effectsOn(plan, undefined).map(item => item.id)).toEqual(['effect-01']);
    expect(effectNumber(1)).toBe('VFX-02');
    expect(effectName(plan.effects![1])).toBe('掌风');
    expect(effectName(MARK)).toBe('冲击波');
    expect(nextEffectId(plan.effects!)).toBe('effect-06');
    expect(nextEffectId([])).toBe('effect-01');
  });

  it('drags a marker by the offset it was grabbed at, snaps to the grid when the desk does, and stays on the stage', () => {
    const free = { grid: false, gridSize: 0.25 };
    // Grabbed 10 cm off-centre: the centre moves by what the pointer moved, not to the pointer.
    expect(draggedCentre([1, 0], [1.1, 0.05], [2.1, -0.95], free)).toEqual([2, -1]);
    expect(draggedCentre([1, 0], [1, 0], [1.337, 0.618], free)).toEqual([1.34, 0.62]);
    expect(draggedCentre([1, 0], [1, 0], [1.337, 0.618], { grid: true, gridSize: 0.25 })).toEqual([1.25, 0.5]);
    expect(draggedCentre([1, 0], [1, 0], [1.337, 0.618], { grid: true, gridSize: 0 })).toEqual([1.34, 0.62]);
    expect(draggedCentre([0, 0], [0, 0], [9999, -9999], free)).toEqual([500, -500]);
  });

  it('ends a drag in one edit, and in none when the marker is back where it began', () => {
    expect(effectMove(MARK, [2, -1])).toEqual({ op: 'set_effect', id: 'effect-01', position: [2, -1] });
    expect(effectMove(MARK, [1, 0])).toBeNull();
    const plan = stage([MARK]);
    const moved = applyAll(plan, [effectMove(MARK, [2, -1])!]);
    expect(moved.effects![0]).toEqual({ ...MARK, position: [2, -1] });
    // Undo puts it back with everything else as it was.
    expect(applyAll(moved, inverseOf(plan, [effectMove(MARK, [2, -1])!])!).effects).toEqual([MARK]);
  });

  it('draws as many rings as the range can hold and closes each ring on the floor', () => {
    expect(ringCount('shock', 3)).toBe(3);
    expect(ringCount('shock', 1.5)).toBe(1);
    expect(ringCount('shock', 2.4)).toBe(2);
    expect(ringCount('crack', 8)).toBe(1);
    const ring = floorRing([1, -2], 2, 0.03, 8);
    expect(ring).toHaveLength(9);
    expect(ring[0]).toEqual(ring[8].map((value, index) => (index === 1 ? value : Number(value.toFixed(10)))));
    for (const [x, y, z] of ring) {
      expect(Math.hypot(x - 1, z + 2)).toBeCloseTo(2);
      expect(y).toBe(0.03);
    }
  });
});
