import { describe, expect, it } from 'vitest';

import { contactPlan } from '../spatial/spatialFixtures';
import type { StageContact, StageOperation, StagePlan } from '../spatial/spatialTypes';
import { applyAll, applyLocal, inverseOf } from './deskOperations';
import { deskReducer, initialDeskState, type DeskState } from './deskReducer';
import { detachOperations } from './lib/contacts';

const SEAT: StageContact = { id: 'contact-02', kind: 'sit', actor: '周教授', target: '扶手椅', support: '', hand: '', shot_ids: [2], source: 'auto' };

function stage(contacts: StageContact[] = contactPlan().contacts!): StagePlan {
  return contactPlan({ contacts });
}

/** What a contact is, leaving out the id the server hands out and who made it. */
function shapes(plan: StagePlan) {
  return (plan.contacts || []).map(item => ({ kind: item.kind, actor: item.actor, target: item.target, support: item.support, hand: item.hand, shot_ids: item.shot_ids }));
}

function roundTrip(plan: StagePlan, operations: StageOperation[]) {
  const after = applyAll(plan, operations);
  const inverse = inverseOf(plan, operations);
  expect(inverse).not.toBeNull();
  return { after, back: applyAll(after, inverse!) };
}

describe('contact operations', () => {
  it('adds a contact by hand, numbered after the ones there are', () => {
    const next = applyLocal(stage(), { op: 'set_contact', kind: 'rest', target: '茶杯', support: '书案', shot_ids: [1] });
    expect(next.contacts).toHaveLength(2);
    expect(next.contacts![1]).toEqual({ id: 'contact-02', kind: 'rest', actor: '', target: '茶杯', support: '书案', hand: '', shot_ids: [1], source: 'manual' });
  });

  it('replaces the contact on the same target in the same shots, and keeps one in other shots', () => {
    const scoped = stage([{ ...contactPlan().contacts![0], shot_ids: [2] }]);
    const elsewhere = applyLocal(scoped, { op: 'set_contact', kind: 'rest', target: '录音笔', support: '书案', shot_ids: [1] });
    expect(shapes(elsewhere).map(item => [item.kind, item.shot_ids])).toEqual([['hold', [2]], ['rest', [1]]]);
    // A whole-scene contact shares every shot.
    const everywhere = applyLocal(scoped, { op: 'set_contact', kind: 'hold', actor: '周教授', target: '录音笔', hand: 'left', shot_ids: [] });
    expect(shapes(everywhere)).toEqual([{ kind: 'hold', actor: '周教授', target: '录音笔', support: '', hand: 'left', shot_ids: [] }]);
  });

  it('keeps only what a kind may say', () => {
    const next = applyLocal(stage([]), { op: 'set_contact', kind: 'sit', actor: '周教授', target: '扶手椅', support: '书案', hand: 'left' });
    expect(shapes(next)).toEqual([{ kind: 'sit', actor: '周教授', target: '扶手椅', support: '', hand: '', shot_ids: [] }]);
    expect(applyLocal(stage([]), { op: 'set_contact', kind: 'hold', actor: '林夏', target: '不存在' }).contacts).toEqual([]);
  });

  it('removes every contact on a target, or takes one shot out of them', () => {
    const plan = stage([contactPlan().contacts![0], { ...SEAT, shot_ids: [1, 2] }]);
    expect(shapes(applyLocal(plan, { op: 'remove_contact', target: '扶手椅' })).map(item => item.target)).toEqual(['录音笔']);
    expect(shapes(applyLocal(plan, { op: 'remove_contact', target: '扶手椅', shot_id: 2 }))[1].shot_ids).toEqual([1]);
    // A whole-scene contact taken out of one shot stays in the scene's other shots.
    expect(shapes(applyLocal(plan, { op: 'remove_contact', target: '录音笔', shot_id: 1 }))[0].shot_ids).toEqual([2]);
    // Out of its last shot, it is gone.
    const single = stage([SEAT]);
    expect(applyLocal(single, { op: 'remove_contact', target: '扶手椅', shot_id: 2 }).contacts).toEqual([]);
  });

  it('undoes a new contact, a changed one and a removed one back to exactly what was there', () => {
    const plan = stage([contactPlan().contacts![0], SEAT]);
    const cases: StageOperation[][] = [
      [{ op: 'set_contact', kind: 'rest', target: '茶杯', support: '书案', shot_ids: [] }],
      [{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'both', shot_ids: [1] }],
      [{ op: 'remove_contact', target: '录音笔' }],
      [{ op: 'remove_contact', target: '扶手椅', shot_id: 2 }],
      [{ op: 'remove_contact', target: '扶手椅' }, { op: 'set_contact', kind: 'sit', actor: '周教授', target: '扶手椅', shot_ids: [1] }],
    ];
    cases.forEach(operations => {
      const { after, back } = roundTrip(plan, operations);
      expect(shapes(after), JSON.stringify(operations)).not.toEqual(shapes(plan));
      expect(shapes(back).sort((a, b) => a.target.localeCompare(b.target)), JSON.stringify(operations))
        .toEqual(shapes(plan).sort((a, b) => a.target.localeCompare(b.target)));
    });
  });

  it('spells the inverse as: off the target, its baked marks back, then each contact that was on it, as it was', () => {
    const plan = stage([contactPlan().contacts![0]]);
    const pen = { op: 'transform_landmark', name: '录音笔', position: [0, -0.9], elevation_m: 0, yaw_deg: 0 };
    const lin = { op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [] };
    expect(inverseOf(plan, [{ op: 'set_contact', kind: 'hold', actor: '周教授', target: '录音笔', hand: 'left' }])).toEqual([{ op: 'remove_contact', target: '录音笔' }, pen, lin]);
    expect(inverseOf(plan, [{ op: 'set_contact', kind: 'rest', target: '茶杯', support: '书案' }])).toEqual([
      { op: 'remove_contact', target: '茶杯' },
      { op: 'transform_landmark', name: '茶杯', position: [5, -2], elevation_m: 0, yaw_deg: 0 },
    ]);
    // A contact tied to shots never touches the stored marks: nothing of them to put back.
    expect(inverseOf(plan, [{ op: 'set_contact', kind: 'rest', target: '茶杯', support: '书案', shot_ids: [1] }])).toEqual([{ op: 'remove_contact', target: '茶杯' }]);
    // Removed, there is nothing on the target to take off first (the server would refuse it).
    expect(inverseOf(plan, [{ op: 'remove_contact', target: '录音笔' }])).toEqual([pen, lin]);
    // Nothing on it: nothing to undo.
    expect(inverseOf(plan, [{ op: 'remove_contact', target: '茶杯' }])).toEqual([]);
    // A sit puts the sitter's own mark back too.
    expect(inverseOf(plan, [{ op: 'set_contact', kind: 'sit', actor: '周教授', target: '扶手椅' }])).toEqual([
      { op: 'remove_contact', target: '扶手椅' },
      { op: 'transform_landmark', name: '扶手椅', position: [2.5, 0], elevation_m: 0, yaw_deg: -90 },
      { op: 'move_actor', name: '周教授', position: [1.3, 0], posture: 'stand' },
    ]);
  });

  it('takes the new contact’s shots out of the others on the target, as the server does', () => {
    const plan = stage();
    const next = applyLocal(plan, { op: 'set_contact', kind: 'rest', target: '录音笔', support: '书案', shot_ids: [1] });
    expect(shapes(next).map(item => [item.kind, item.shot_ids])).toEqual([['hold', [2]], ['rest', [1]]]);
    expect(next.contacts!.map(item => item.id)).toEqual(['contact-01', 'contact-02']);
    const { back } = roundTrip(plan, [{ op: 'set_contact', kind: 'rest', target: '录音笔', support: '书案', shot_ids: [1] }]);
    expect(shapes(back)).toEqual(shapes(plan));
  });

  it('bakes whole-scene contacts into the stored marks after every batch, and drops those naming something gone', () => {
    const plan = stage([contactPlan().contacts![0], SEAT, { ...SEAT, id: 'contact-03', actor: '林夏', target: '书案', shot_ids: [] }]);
    const moved = applyAll(plan, [{ op: 'move_actor', name: '周教授', position: [0, 3] }]);
    // The professor's sit is for shot 2 only: his mark stays where he was put.
    expect(moved.actors.find(actor => actor.name === '周教授')!.position).toEqual([0, 3]);
    // (The server would not take a desk as a seat; the local preview leaves that to it.)
    // 林夏 sits on the desk all scene long, so her mark is its centre, and the recorder is in her sitting hand.
    expect(moved.actors.find(actor => actor.name === '林夏')).toMatchObject({ position: [0, -2], posture: 'sit' });
    // Facing +X: ahead is +X, her right is +Z.
    expect(moved.landmarks.find(item => item.name === '录音笔')!.position).toEqual([0.18, -1.78]);
    expect(moved.landmarks.find(item => item.name === '录音笔')!.elevation_m).toBeCloseTo(0.935 - 0.02, 6);
    // A plan with no contacts comes back untouched.
    const bare = contactPlan({ contacts: [] });
    expect(applyAll(bare, [])).toBe(bare);
    expect(applyAll(plan, [{ op: 'remove_landmark', name: '扶手椅' }]).contacts!.map(item => item.id)).toEqual(['contact-01', 'contact-03']);
  });

  it('takes a removed piece’s contacts with it and brings them back with it', () => {
    const plan = stage([contactPlan().contacts![0], { id: 'contact-02', kind: 'rest', actor: '', target: '茶杯', support: '书案', hand: '', shot_ids: [], source: 'manual' }]);
    const operations = [...detachOperations(plan, '书案'), { op: 'remove_landmark', name: '书案' }];
    expect(operations).toEqual([{ op: 'remove_contact', target: '茶杯' }, { op: 'remove_landmark', name: '书案' }]);
    const { after, back } = roundTrip(plan, operations);
    expect(after.landmarks.some(item => item.name === '书案')).toBe(false);
    expect(shapes(after).map(item => item.target)).toEqual(['录音笔']);
    expect(back.landmarks.some(item => item.name === '书案')).toBe(true);
    expect(shapes(back)).toEqual(shapes(plan));
    // A bare removal (a blockout, the agent) drops what named the piece too, and its undo restores it.
    const bare = roundTrip(plan, [{ op: 'remove_landmark', name: '茶杯' }]);
    expect(shapes(bare.after).map(item => item.target)).toEqual(['录音笔']);
    expect(shapes(bare.back)).toEqual(shapes(plan));
  });

  it('goes through the desk history: an edit, its undo and its redo', () => {
    const response = { taskId: 't1', sceneId: 'E1S01', persisted: true, boardStatus: 'done', boardStale: false, plan: stage() };
    let state: DeskState = deskReducer(initialDeskState, { type: 'loaded', response });
    const forward: StageOperation[] = [{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'left', shot_ids: [1] }];
    state = deskReducer(state, { type: 'edit', id: 1, kind: 'edit', label: '录音笔 交到 林夏 左手', operations: forward });
    // Shot 1 is taken out of the whole-scene hold, which keeps shot 2.
    expect(shapes(state.plan!)).toEqual([
      { kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [2] },
      { kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'left', shot_ids: [1] },
    ]);
    state = deskReducer(state, { type: 'applied', response: { ...response, plan: { ...state.plan!, revision: 4 } }, editIds: [1] });
    const entry = state.undo[state.undo.length - 1];
    expect(entry.inverse).toEqual([
      { op: 'remove_contact', target: '录音笔' },
      { op: 'transform_landmark', name: '录音笔', position: [0, -0.9], elevation_m: 0, yaw_deg: 0 },
      { op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [] },
    ]);
    state = deskReducer(state, { type: 'edit', id: 2, kind: 'undo', label: entry.label, operations: entry.inverse });
    expect(shapes(state.plan!)).toEqual(shapes(stage()));
    state = deskReducer(state, { type: 'applied', response: { ...response, plan: { ...state.plan!, revision: 5 } }, editIds: [2] });
    const redo = state.redo[state.redo.length - 1];
    state = deskReducer(state, { type: 'edit', id: 3, kind: 'redo', label: redo.label, operations: redo.forward });
    expect(shapes(state.plan!).find(item => item.shot_ids.includes(1))).toMatchObject({ hand: 'left' });
  });
});
