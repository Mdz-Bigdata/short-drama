import { Group, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import { actorsInShot, type StageActor, type StageContact, type StagePlan, type StagePosture } from '../../spatial/spatialTypes';
import {
  carriedAlongFist, clampToFootprint, contactPhrase, contactsAt, dragRefusal, formulaHandPoint, heldTargets, isSeat, resolveContacts, type HandLocator,
} from './contacts';
import { mannequinHandPoint } from './handBones';
import { boneLocals, groundLift, proportionsOf } from './mannequinRig';
import { jointsOf } from './poses';

const LIN: StageActor = { id: 'actor-01', name: '林夏', position: [-1.3, 0], yaw_deg: 90, height_m: 1.7, posture: 'stand', role: 'principal', screen_side: 'left' };

function contact(fields: Partial<StageContact>): StageContact {
  return { id: 'contact-09', kind: 'hold', actor: '', target: '', support: '', hand: '', shot_ids: [], source: 'manual', ...fields };
}

function landmarkOf(plan: StagePlan, name: string) {
  return plan.landmarks.find(item => item.name === name)!;
}

function close(actual: readonly number[], expected: readonly number[], digits = 6) {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, index) => expect(actual[index], `[${index}]`).toBeCloseTo(value, digits));
}

describe('the formula hand', () => {
  it('puts the right hand 0.22 m to the right and 0.18 m ahead, the left mirrored, both hands 0.25 m ahead on the centre line', () => {
    // Facing +X (yaw 90): ahead is +X, the actor's right is +Z.
    close(formulaHandPoint(LIN, 'right'), [-1.12, 0.799, 0.22]);
    close(formulaHandPoint(LIN, 'left'), [-1.12, 0.799, -0.22]);
    close(formulaHandPoint(LIN, 'both'), [-1.05, 0.799, 0]);
    // Facing +Z (yaw 0): the right is −X.
    close(formulaHandPoint({ ...LIN, position: [0, 0], yaw_deg: 0 }, 'right'), [-0.22, 0.799, 0.18]);
    close(formulaHandPoint({ ...LIN, position: [0, 0], yaw_deg: 0 }, 'left'), [0.22, 0.799, 0.18]);
  });

  it('holds the hand at the posture share of standing height, and a pose preset speaks before the posture', () => {
    const heights: Array<[StagePosture, number]> = [
      ['stand', 0.799], ['walk', 0.799], ['run', 0.799], ['fight', 0.799], ['lean', 0.799], ['bow', 0.799],
      ['sit', 0.935], ['crouch', 0.85], ['kneel', 0.85], ['lie', 0.204],
    ];
    heights.forEach(([posture, height]) => expect(formulaHandPoint({ ...LIN, posture }, 'right')[1], posture).toBeCloseTo(height, 6));
    expect(formulaHandPoint({ ...LIN, posture: 'stand', pose: { preset: 'sit', joints: {} } }, 'right')[1]).toBeCloseTo(0.935, 6);
  });
});

describe('resolveContacts', () => {
  it('puts a held prop in the hand: centred on it, underside half its height below, turned with the holder', () => {
    const plan = resolveContacts(contactPlan(), 1);
    const pen = landmarkOf(plan, '录音笔');
    expect(pen.position).toEqual([-1.12, 0.22]);
    expect(pen.elevation_m).toBeCloseTo(0.779, 6);
    expect(pen.yaw_deg).toBe(90);

    const left = resolveContacts(contactPlan({ contacts: [contact({ actor: '林夏', target: '录音笔', hand: 'left' })] }), 1);
    expect(landmarkOf(left, '录音笔').position).toEqual([-1.12, -0.22]);
    const both = resolveContacts(contactPlan({ contacts: [contact({ actor: '林夏', target: '录音笔', hand: 'both' })] }), 1);
    expect(landmarkOf(both, '录音笔').position).toEqual([-1.05, 0]);
    // '' is the right hand.
    const unnamed = resolveContacts(contactPlan({ contacts: [contact({ actor: '林夏', target: '录音笔', hand: '' })] }), 1);
    expect(landmarkOf(unnamed, '录音笔').position).toEqual([-1.12, 0.22]);
  });

  it('leans a long held thing the way the fist points it, gripped near its end', () => {
    const base = contactPlan();
    const sword = { id: 'mark-09', name: '长剑', kind: 'prop' as const, position: [3, 3] as [number, number], size: [0.05, 0.05, 0.9] as [number, number, number] };
    const plan = { ...base, landmarks: [...base.landmarks, sword], contacts: [contact({ actor: '林夏', target: '长剑', hand: 'right' })] };
    // The fist is at (1, 1.2, 2) and points what it holds straight ahead along +X, knuckles down.
    const hand: HandLocator = () => ({ point: [1, 1.2, 2], along: [1, 0, 0], forward: [0, -1, 0] });
    const held = landmarkOf(resolveContacts(plan, 1, { hand }), '长剑');
    // The hilt is 0.12 m of a 0.9 m sword: its foot sits that far behind the hand, and the blade runs on from there.
    expect(held.position).toEqual([0.88, 2]);
    expect(held.elevation_m).toBe(1.2);
    expect(held.tilt).toEqual({ up: [1, 0, 0], forward: [0, -1, 0] });

    // A short blade is gripped at a share of its length; a facing nobody gave is the holder's own.
    const dagger = landmarkOf(resolveContacts({ ...plan, landmarks: plan.landmarks.map(item => (item.name === '长剑' ? { ...item, size: [0.04, 0.04, 0.4] as [number, number, number] } : item)) }, 1, { hand: () => ({ point: [1, 1.2, 2], along: [0, 1, 0] }) }), '长剑');
    expect(dagger.elevation_m).toBeCloseTo(1.14, 6);
    expect(dagger.tilt!.up).toEqual([0, 1, 0]);
    close(dagger.tilt!.forward, [1, 0, 0]);
  });

  it('keeps a small or squat thing upright in the palm whatever the fist does, and a plain point as it always was', () => {
    const hand: HandLocator = () => ({ point: [1, 1.2, 2], along: [1, 0, 0], forward: [0, -1, 0] });
    const pen = landmarkOf(resolveContacts(contactPlan(), 1, { hand }), '录音笔');
    expect(pen.tilt).toBeUndefined();
    expect(pen.position).toEqual([1, 2]);
    expect(pen.elevation_m).toBeCloseTo(1.18, 6);
    expect(pen.yaw_deg).toBe(90);
    expect(landmarkOf(resolveContacts(contactPlan(), 1, { hand: () => [1, 1.2, 2] }), '录音笔').position).toEqual([1, 2]);

    expect(carriedAlongFist({ size: [0.05, 0.05, 0.9] })).toBe(true);
    expect(carriedAlongFist({ size: [0.03, 0.03, 0.2] })).toBe(false);   // a pen: slender, but it stands in the hand
    expect(carriedAlongFist({ size: [0.4, 0.4, 0.9] })).toBe(false);     // a crate: tall, not slender
  });

  it('never sinks a big held thing under the floor', () => {
    const base = contactPlan();
    const plan = resolveContacts({ ...base, landmarks: base.landmarks.map(item => (item.name === '录音笔' ? { ...item, size: [0.5, 0.5, 2] as [number, number, number] } : item)) }, 1);
    expect(landmarkOf(plan, '录音笔').elevation_m).toBe(0);
  });

  it('reads the holder as the shot stages them, and leaves a prop alone when its holder is off stage', () => {
    const base = contactPlan();
    const moved = resolveContacts({ ...base, shots: [{ ...base.shots[0], overrides: [{ name: '林夏', position: [0, 0], yaw_deg: 0 }] }, base.shots[1]] }, 1);
    expect(landmarkOf(moved, '录音笔').position).toEqual([-0.22, 0.18]);
    const gone = { ...base, shots: [{ ...base.shots[0], overrides: [{ name: '林夏', offstage: true }] }, base.shots[1]] };
    expect(resolveContacts(gone, 1).landmarks).toBe(gone.landmarks);
  });

  it('seats an actor on the seat centre, sitting, facing kept, and their hand is a sitting hand', () => {
    const plan = resolveContacts(contactPlan({
      contacts: [
        contact({ id: 'contact-01', kind: 'sit', actor: '周教授', target: '扶手椅' }),
        contact({ id: 'contact-02', actor: '周教授', target: '茶杯' }),
      ],
    }), 1);
    const zhou = actorsInShot(plan, plan.shots[0]).find(actor => actor.name === '周教授')!;
    expect(zhou.position).toEqual([2.5, 0]);
    expect(zhou.posture).toBe('sit');
    expect(zhou.yaw_deg).toBe(-90);
    // Facing −X: ahead is −X, the right is −Z; the hand is at 1.7 × 0.55.
    const cup = landmarkOf(plan, '茶杯');
    expect(cup.position).toEqual([2.32, -0.22]);
    expect(cup.elevation_m).toBeCloseTo(0.935 - 0.05, 6);
  });

  it('sits a figure posed in another named posture down, and keeps a pose shaped by hand', () => {
    const sit = [contact({ kind: 'sit', actor: '周教授', target: '扶手椅' })];
    const standing = contactPlan({ contacts: sit, actors: contactPlan().actors.map(actor => (actor.name === '周教授' ? { ...actor, figure: 'mannequin' as const, pose: { preset: 'stand', joints: {} } } : actor)) });
    expect(resolveContacts(standing, 1).actors.find(actor => actor.name === '周教授')!.pose).toEqual({ preset: 'sit', joints: {} });
    const shaped = { preset: '', joints: { 'leftElbow.bend': 40 } };
    const custom = contactPlan({ contacts: sit, actors: contactPlan().actors.map(actor => (actor.name === '周教授' ? { ...actor, figure: 'mannequin' as const, pose: shaped } : actor)) });
    expect(resolveContacts(custom, 1).actors.find(actor => actor.name === '周教授')!.pose).toBe(shaped);
  });

  it('moves a re-marked seated actor through the shot override, which is what the shot reads', () => {
    const base = contactPlan({ contacts: [contact({ kind: 'sit', actor: '周教授', target: '扶手椅' })] });
    const plan = resolveContacts({ ...base, shots: [{ ...base.shots[0], overrides: [{ name: '周教授', position: [9, 9], posture: 'stand' }] }, base.shots[1]] }, 1);
    expect(plan.shots[0].overrides[0]).toMatchObject({ position: [2.5, 0], posture: 'sit' });
    expect(actorsInShot(plan, plan.shots[0]).find(actor => actor.name === '周教授')!.position).toEqual([2.5, 0]);
  });

  it('rests a thing on the top of its support, inside its footprint with a 2 cm margin', () => {
    const plan = resolveContacts(contactPlan({ contacts: [contact({ kind: 'rest', target: '茶杯', support: '书案' })] }), 1);
    const cup = landmarkOf(plan, '茶杯');
    expect(cup.position).toEqual([0.78, -2]);
    expect(cup.elevation_m).toBe(0.78);
  });

  it('settles a thing on a held tray on the hand that holds the tray', () => {
    const base = contactPlan();
    const plan = resolveContacts({
      ...base,
      landmarks: [...base.landmarks, { id: 'mark-05', name: '托盘', kind: 'furniture', position: [0, 0], size: [0.4, 0.3, 0.02] }],
      contacts: [contact({ id: 'contact-01', kind: 'rest', target: '茶杯', support: '托盘' }), contact({ id: 'contact-02', actor: '林夏', target: '托盘', hand: 'both' })],
    }, 1);
    const tray = landmarkOf(plan, '托盘');
    expect(tray.position).toEqual([-1.05, 0]);
    const cup = landmarkOf(plan, '茶杯');
    expect(cup.elevation_m).toBeCloseTo((tray.elevation_m ?? 0) + 0.02, 6);
    expect(Math.abs(cup.position[0] - tray.position[0])).toBeLessThanOrEqual(0.18 + 1e-9);
  });

  it('keeps contacts to their shots', () => {
    const plan = contactPlan({ contacts: [contact({ actor: '林夏', target: '录音笔', shot_ids: [2] })] });
    expect(resolveContacts(plan, 1)).toBe(plan);
    expect(landmarkOf(resolveContacts(plan, 2), '录音笔').position).toEqual([-1.12, 0.22]);
    expect(contactsAt(plan, 1)).toEqual([]);
    expect(contactsAt(plan, null)).toEqual([]);
  });

  it('hands back the very same plan when there is nothing to keep, or nothing to change', () => {
    const none = contactPlan({ contacts: undefined });
    expect(resolveContacts(none, 1)).toBe(none);
    const once = resolveContacts(contactPlan(), 1);
    expect(resolveContacts(once, 1)).toBe(once);
  });
});

describe('clampToFootprint', () => {
  const desk = { position: [1, 1] as [number, number], size: [1, 0.6, 0.75] as [number, number, number] };

  it('brings a point inside the footprint along the piece’s own axes', () => {
    close(clampToFootprint([3, 1], desk), [1.48, 1]);
    close(clampToFootprint([1, 3], desk), [1, 1.28]);
    // Turned a quarter: the narrow side now lies along X.
    close(clampToFootprint([3, 1], { ...desk, yaw_deg: 90 }), [1.28, 1]);
    close(clampToFootprint([1, 3], { ...desk, yaw_deg: 90 }), [1, 1.48]);
    // Turned 45°: the corner region pulls a far point back onto the rotated rectangle.
    const turned = clampToFootprint([3, 3], { ...desk, yaw_deg: 45 });
    const yaw = Math.PI / 4;
    const dx = turned[0] - 1;
    const dz = turned[1] - 1;
    expect(Math.abs(dx * Math.cos(yaw) - dz * Math.sin(yaw))).toBeLessThanOrEqual(0.48 + 1e-9);
    expect(Math.abs(dx * Math.sin(yaw) + dz * Math.cos(yaw))).toBeLessThanOrEqual(0.28 + 1e-9);
  });

  it('leaves a point that is inside where it is', () => {
    const inside: [number, number] = [1.1, 0.9];
    expect(clampToFootprint(inside, desk)).toBe(inside);
  });

  it('knows a seat by the height of its top', () => {
    expect(isSeat({ size: [0.7, 0.7, 0.45] })).toBe(true);
    expect(isSeat({ size: [1.6, 0.8, 0.78] })).toBe(false);
    expect(isSeat({ size: [0.7, 0.7, 0.2], elevation_m: 0.2 })).toBe(true);
  });
});

/** The palm the way Mannequin.tsx draws it: a scene graph of the rig's bones, read in world space. */
function drawnPalm(actor: StageActor, side: 'left' | 'right'): Vector3 {
  const joints = jointsOf(actor);
  const root = new Group();
  root.position.set(actor.position[0], 0, actor.position[1]);
  root.rotation.set(0, (actor.yaw_deg * Math.PI) / 180, 0);
  const lifted = new Group();
  lifted.position.set(0, groundLift(joints, actor.body_type) * actor.height_m + (joints['body.offsetY'] ?? 0), 0);
  lifted.scale.setScalar(actor.height_m);
  root.add(lifted);
  const groups = new Map<string, Group>();
  boneLocals(joints, actor.body_type).forEach(bone => {
    const group = new Group();
    group.position.set(...bone.offset);
    group.rotation.set(bone.rotation[0], bone.rotation[1], bone.rotation[2], bone.order);
    (bone.parent ? groups.get(bone.parent)! : lifted).add(group);
    groups.set(bone.id, group);
  });
  root.updateMatrixWorld(true);
  return groups.get(`${side}Hand`)!.localToWorld(new Vector3(0, -proportionsOf(actor.body_type).palm * 0.6, 0));
}

describe('the mannequin hand', () => {
  const posed: StageActor = {
    ...LIN, position: [0.4, -0.6], yaw_deg: 30, figure: 'mannequin', body_type: 'slim',
    pose: { preset: '', joints: { 'rightShoulder.pitch': 80, 'rightElbow.bend': 30, 'leftShoulder.pitch': 20 } },
  };

  it('is the palm of the drawn figure, for each hand and for both', () => {
    (['left', 'right'] as const).forEach(side => close(mannequinHandPoint(posed, side)!, drawnPalm(posed, side).toArray(), 9));
    const middle = drawnPalm(posed, 'left').add(drawnPalm(posed, 'right')).multiplyScalar(0.5);
    close(mannequinHandPoint(posed, 'both')!, middle.toArray(), 9);
  });

  it('carries a held prop where the raised hand is, not where the formula would put it', () => {
    const base = contactPlan();
    const plan = { ...base, actors: base.actors.map(actor => (actor.name === '林夏' ? posed : actor)) };
    const pen = landmarkOf(resolveContacts(plan, 1, { hand: mannequinHandPoint }), '录音笔');
    const palm = drawnPalm(posed, 'right');
    close(pen.position, [palm.x, palm.z], 3);
    expect(pen.elevation_m).toBeCloseTo(palm.y - 0.02, 3);
    // The arm is raised: the hand is well above where the formula holds it.
    expect(palm.y).toBeGreaterThan(formulaHandPoint(posed, 'right')[1] + 0.2);
  });

  it('leaves an unposed mannequin and any other figure to the formula', () => {
    expect(mannequinHandPoint({ ...posed, pose: null }, 'right')).toBeNull();
    expect(mannequinHandPoint({ ...posed, figure: 'humanoid' }, 'right')).toBeNull();
    expect(mannequinHandPoint({ ...posed, figure: 'standin' }, 'right')).toBeNull();
    const base = contactPlan();
    const plan = { ...base, actors: base.actors.map(actor => (actor.name === '林夏' ? { ...posed, pose: null } : actor)) };
    expect(landmarkOf(resolveContacts(plan, 1, { hand: mannequinHandPoint }), '录音笔').position)
      .toEqual(formulaHandPoint({ ...posed, pose: null }, 'right').filter((_, index) => index !== 1).map(value => Math.round(value * 1000) / 1000));
  });
});

describe('what the operator may drag', () => {
  const plan = contactPlan({
    contacts: [
      contact({ id: 'contact-01', actor: '林夏', target: '录音笔', hand: 'right' }),
      contact({ id: 'contact-02', kind: 'sit', actor: '周教授', target: '扶手椅', shot_ids: [2] }),
    ],
  });

  it('refuses moving or turning a held prop with the reason, and lets it be scaled', () => {
    expect(dragRefusal(plan, 1, { kind: 'landmark', name: '录音笔' }, 'translate')).toBe('「录音笔」在林夏右手里：先解除接触再单独移动');
    expect(dragRefusal(plan, 1, { kind: 'landmark', name: '录音笔' }, 'rotate')).toBe('「录音笔」在林夏右手里：先解除接触再单独移动');
    expect(dragRefusal(plan, 1, { kind: 'landmark', name: '录音笔' }, 'scale')).toBe('');
    expect(dragRefusal(plan, 1, { kind: 'landmark', name: '书案' }, 'translate')).toBe('');
    expect(dragRefusal(plan, 1, { kind: 'actor', name: '林夏' }, 'translate')).toBe('');
  });

  it('keeps a seated actor on the seat in the shots the sit is for, and lets them turn', () => {
    expect(dragRefusal(plan, 2, { kind: 'actor', name: '周教授' }, 'translate')).toBe('「周教授」坐在扶手椅上：先解除接触再单独移动');
    expect(dragRefusal(plan, 2, { kind: 'actor', name: '周教授' }, 'rotate')).toBe('');
    expect(dragRefusal(plan, 1, { kind: 'actor', name: '周教授' }, 'translate')).toBe('');
  });

  it('names what each hand holds and where things are', () => {
    expect(heldTargets(plan, 1)).toEqual(new Set(['录音笔']));
    expect(contactPhrase(contact({ actor: '林夏', target: '录音笔', hand: 'both' }))).toBe('在林夏双手里');
    expect(contactPhrase(contact({ kind: 'rest', target: '录音笔', support: '书案' }))).toBe('放在书案上');
    expect(contactPhrase(contact({ kind: 'sit', actor: '周教授', target: '扶手椅' }))).toBe('坐在扶手椅上');
  });
});
