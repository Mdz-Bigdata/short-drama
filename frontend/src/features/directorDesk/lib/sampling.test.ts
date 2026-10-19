import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { ActorKey, CameraKey, StageActor, StagePlan } from '../../spatial/spatialTypes';
import {
  actorPathsOf, cameraPathOf, cyclePhase, ease, frameCount, gaitJoints, lerpYaw, sampleActor, sampleShot, snapToFrame, stagePlanAt, timeOfFrame,
} from './sampling';
import { verticalFov } from './stageMath';

const CAMERA_KEYS: CameraKey[] = [
  { time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
  { time: 4, position: [0, 1.5, 1], target: [0, 1, 0], lens_mm: 56, easing: 'linear' },
];

function timed(camera: CameraKey[] = CAMERA_KEYS, actors: Record<string, ActorKey[]> = {}, shotId = 1): StagePlan {
  return { ...PLAN, timelines: { [String(shotId)]: { duration_s: 4, fps: 24, camera, actors } } };
}

describe('ease', () => {
  it('shapes the way into a key, each in its own manner', () => {
    expect([0, 0.25, 0.5, 1].map(t => ease(t, 'linear'))).toEqual([0, 0.25, 0.5, 1]);
    expect(ease(0.25, 'smooth')).toBeCloseTo(0.15625);
    expect(ease(0.5, 'smooth')).toBeCloseTo(0.5);
    expect(ease(0.5, 'ease-in')).toBeCloseTo(0.25);
    expect(ease(0.5, 'ease-out')).toBeCloseTo(0.75);
    expect([0, 0.5, 0.999, 1].map(t => ease(t, 'hold'))).toEqual([0, 0, 0, 1]);
    expect(ease(0.25, 'whip')).toBeCloseTo(0.03125);
    expect(ease(0.75, 'whip')).toBeCloseTo(0.96875);
    expect(ease(-1, 'smooth')).toBe(0);
    expect(ease(2, 'whip')).toBe(1);
  });

  it('ends where it should for every easing', () => {
    (['linear', 'smooth', 'ease-in', 'ease-out', 'hold', 'whip'] as const).forEach(easing => {
      expect(ease(0, easing)).toBe(0);
      expect(ease(1, easing)).toBe(1);
    });
  });
});

describe('sampleShot', () => {
  it('lerps the lens position and interpolates the lens in millimetres before converting to an angle', () => {
    const plan = timed();
    const middle = sampleShot(plan, plan.shots[0], 2).camera!;
    expect(middle.position).toEqual([0, 1.5, 3]);
    expect(middle.lens_mm).toBe(42);
    // 9:16 delivery: the 36 mm long side is the frame's height.
    expect(middle.fov_deg).toBeCloseTo(verticalFov(42, 9 / 16));
    expect(middle.fov_deg).not.toBeCloseTo((verticalFov(28, 9 / 16) + verticalFov(56, 9 / 16)) / 2, 1);
    expect(sampleShot(plan, plan.shots[0], -3).camera!.position).toEqual([0, 1.5, 5]);
    expect(sampleShot(plan, plan.shots[0], 99).camera!.position).toEqual([0, 1.5, 1]);
  });

  it('uses the easing of the key being arrived at', () => {
    const plan = timed([CAMERA_KEYS[0], { ...CAMERA_KEYS[1], easing: 'hold' }]);
    expect(sampleShot(plan, plan.shots[0], 3.9).camera!.position).toEqual([0, 1.5, 5]);
    expect(sampleShot(plan, plan.shots[0], 4).camera!.position).toEqual([0, 1.5, 1]);
  });

  it('gives the same answer for the same t whatever was asked before', () => {
    const walk: ActorKey[] = [
      { time: 0, position: [-1.3, 0], yaw_deg: 170, pose: { preset: 'walk', joints: {}, clip: '', clip_phase: 0 }, easing: 'linear' },
      { time: 4, position: [1, 2], yaw_deg: -170, easing: 'smooth' },
    ];
    const plan = timed(CAMERA_KEYS, { 林夏: walk });
    plan.actors = plan.actors.map(actor => (actor.name === '林夏' ? { ...actor, figure: 'mannequin' } : actor));
    const times = [0, 0.5, 1.25, 2, 3.75, 4];
    const forwards = times.map(t => JSON.stringify(sampleShot(plan, plan.shots[0], t)));
    const backwards = [...times].reverse().map(t => JSON.stringify(sampleShot(plan, plan.shots[0], t))).reverse();
    const shuffled = [3, 0, 5, 1, 4, 2].map(index => [index, JSON.stringify(sampleShot(plan, plan.shots[0], times[index]))] as const);
    expect(backwards).toEqual(forwards);
    shuffled.forEach(([index, text]) => expect(text).toBe(forwards[index]));
  });

  it('falls back to the static plan without keys, and to a two-key move for a legacy camera move', () => {
    const still = sampleShot(PLAN, PLAN.shots[0], 2.5);
    expect(still.camera).toEqual({ position: [0, 1.45, 5.2], target: [0, 0.9, 0], lens_mm: 28, fov_deg: 65.5 });
    expect(still.actors['林夏']).toEqual({ position: [-1.3, 0], yaw_deg: 90, pose: null });
    expect(stagePlanAt(PLAN, 1, 2.5)).toBe(PLAN);

    // cam-02 pushes from its position to move.end_position over the default five seconds.
    const legacy = sampleShot(PLAN, PLAN.shots[1], 5).camera!;
    expect(legacy.position).toEqual([-0.2, 1.55, 0.65]);
    expect(sampleShot(PLAN, PLAN.shots[1], 0).camera!.position).toEqual([0.2, 1.58, 0.9]);
    expect(cameraPathOf(PLAN, PLAN.shots[1])!.keys.map(key => key.time)).toEqual([0, 5]);
    expect(cameraPathOf(PLAN, PLAN.shots[0])).toBeNull();
    // Whoever is offstage in the shot is not sampled at all.
    expect(Object.keys(sampleShot(PLAN, PLAN.shots[1], 0).actors)).toEqual(['林夏', '周教授']);
  });

  it('draws an actor track as the line through its placed keys, and skips a track that stays put', () => {
    const plan = timed([], {
      林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 1, yaw_deg: 45, easing: 'smooth' }, { time: 4, position: [1, 2], easing: 'smooth' }],
      助手: [{ time: 0, position: [0, -2], easing: 'linear' }, { time: 2, pose: { preset: 'sit' }, easing: 'linear' }],
    });
    expect(actorPathsOf(plan, plan.shots[0])).toEqual([
      { name: '林夏', points: [[-1.3, 0, 0], [1, 0, 2]], keys: [{ time: 0, position: [-1.3, 0, 0] }, { time: 4, position: [1, 0, 2] }] },
    ]);
    expect(actorPathsOf(plan, undefined)).toEqual([]);
    expect(actorPathsOf(PLAN, PLAN.shots[0])).toEqual([]);
  });

  it('leaves a candidate lens where it is: keys belong to the lens that films', () => {
    const plan = timed();
    expect(sampleShot(plan, plan.shots[0], 2, 'cam-02').camera!.position).toEqual([0.2, 1.58, 0.9]);
  });

  it('draws the sampled stage through the plan, re-marks included', () => {
    const plan = timed([], { 助手: [{ time: 0, position: [0, -2], easing: 'linear' }, { time: 4, position: [2, -2], easing: 'linear' }] });
    plan.shots = plan.shots.map(shot => (shot.shot_id === 1 ? { ...shot, overrides: [{ name: '助手', position: [0, -2], reason: '' }] } : shot));
    const staged = stagePlanAt(plan, 1, 2);
    expect(staged.actors.find(actor => actor.name === '助手')!.position).toEqual([1, -2]);
    expect(staged.shots[0].overrides[0].position).toEqual([1, -2]);
    expect(staged.actors.find(actor => actor.name === '林夏')).toBe(plan.actors[0]);
  });
});

describe('sampleActor', () => {
  const actor: StageActor = { ...PLAN.actors[0], figure: 'mannequin' };

  it('turns the short way round', () => {
    expect(lerpYaw(170, -170, 0.5)).toBeCloseTo(180);
    expect(lerpYaw(-170, 170, 0.25)).toBeCloseTo(-175);
    expect(lerpYaw(10, 50, 0.5)).toBeCloseTo(30);
    const keys: ActorKey[] = [{ time: 0, yaw_deg: 170, easing: 'linear' }, { time: 2, yaw_deg: -170, easing: 'linear' }];
    expect(sampleActor(actor, keys, 0.5).yaw_deg).toBeCloseTo(175);
    expect(sampleActor(actor, keys, 1.5).yaw_deg).toBeCloseTo(-175);
  });

  it('carries a channel across keys that do not speak about it', () => {
    const keys: ActorKey[] = [
      { time: 0, position: [0, 0], easing: 'linear' },
      { time: 1, pose: { preset: '', joints: { 'head.yaw': 40 }, clip: '', clip_phase: 0 }, easing: 'linear' },
      { time: 2, position: [2, 0], easing: 'linear' },
    ];
    const middle = sampleActor(actor, keys, 1);
    expect(middle.position).toEqual([1, 0]);
    expect(middle.yaw_deg).toBe(actor.yaw_deg);
    expect(middle.pose?.joints?.['head.yaw']).toBe(40);
  });

  it('blends whole poses between keys', () => {
    const keys: ActorKey[] = [
      { time: 0, pose: { preset: '', joints: { 'leftElbow.bend': 0, 'head.yaw': 20 }, clip: '', clip_phase: 0 }, easing: 'linear' },
      { time: 2, pose: { preset: '', joints: { 'leftElbow.bend': 90 }, clip: '', clip_phase: 0 }, easing: 'linear' },
    ];
    expect(sampleActor(actor, keys, 1).pose?.joints).toEqual({ 'leftElbow.bend': 45, 'head.yaw': 10 });
  });

  it('advances the gait from t alone: phase = (t · rate) mod 1', () => {
    expect(cyclePhase(0.25, 1)).toBeCloseTo(0.25);
    expect(cyclePhase(2.25, 1)).toBeCloseTo(0.25);
    expect(cyclePhase(0.5, 1.5)).toBeCloseTo(0.75);
    expect(cyclePhase(7 / 24, 1)).toBeCloseTo(cyclePhase(24 * 3 / 24 + 7 / 24, 1));
    // A quarter of the way round the left leg is furthest forward with a straight knee; the right arm goes with it.
    const stride = gaitJoints('walk', 0.25);
    expect(stride['leftHip.pitch']).toBeCloseTo(25);
    expect(stride['leftKnee.bend']).toBeCloseTo(0);
    expect(stride['rightHip.pitch']).toBeCloseTo(-12);
    expect(stride['rightShoulder.pitch']).toBeCloseTo(24);
    expect(gaitJoints('run', 0)['leftKnee.bend']).toBeCloseTo(90);

    const walk: ActorKey[] = [
      { time: 0, position: [0, 0], pose: { preset: 'walk', joints: {}, clip: '', clip_phase: 0 }, easing: 'linear' },
      { time: 4, position: [4, 0], easing: 'linear' },
    ];
    const early = sampleActor(actor, walk, 0.25);
    expect(early.pose?.preset).toBe('walk');
    expect(early.pose?.joints?.['leftHip.pitch']).toBeCloseTo(25);
    // One whole cycle later the figure is in the same stride, further along.
    expect(sampleActor(actor, walk, 1.25).pose?.joints).toEqual(early.pose?.joints);
    // A key records the pose somebody set, not one frame of the stride.
    expect(sampleActor(actor, walk, 0.25, true).pose).toEqual(walk[0].pose);
    // A stand-in has no legs to swing.
    expect(sampleActor({ ...actor, figure: 'standin' }, walk, 0.25).pose).toEqual(walk[0].pose);
  });

  it('scrubs a skinned figure by t: loops wrap, one-shot clips start at their key and stop at the end', () => {
    const human: StageActor = { ...actor, figure: 'humanoid', pose: { preset: 'walk', joints: {}, clip: 'human-walk-v1', clip_phase: 0.25 } };
    expect(sampleActor(human, undefined, 0).pose).toBe(human.pose);
    // human-walk-v1 lasts 1.3333 s.
    expect(sampleActor(human, undefined, 1.3333 / 2).pose?.clip_phase).toBeCloseTo(0.75);
    expect(sampleActor(human, undefined, 1.3333).pose?.clip_phase).toBeCloseTo(0.25);

    const sit: ActorKey[] = [
      { time: 0, pose: { preset: 'stand', joints: {}, clip: 'human-idle-v1', clip_phase: 0 }, easing: 'linear' },
      { time: 2, pose: { preset: 'sit', joints: {}, clip: 'human-sit-enter-v1', clip_phase: 0 }, easing: 'hold' },
    ];
    expect(sampleActor(human, sit, 1).pose?.clip).toBe('human-idle-v1');
    expect(sampleActor(human, sit, 2).pose).toMatchObject({ clip: 'human-sit-enter-v1', clip_phase: 0 });
    expect(sampleActor(human, sit, 2.65).pose?.clip_phase).toBeCloseTo(0.5);
    expect(sampleActor(human, sit, 4).pose?.clip_phase).toBe(1);
  });
});

describe('frames', () => {
  it('counts and snaps whole frames', () => {
    expect(frameCount(5, 24)).toBe(120);
    expect(frameCount(3.5, 25)).toBe(88);
    expect(frameCount(4, 30)).toBe(120);
    expect(snapToFrame(0.2099, 24, 5)).toBeCloseTo(5 / 24);
    expect(snapToFrame(5, 24, 5)).toBeCloseTo(119 / 24);
    expect(snapToFrame(-1, 24, 5)).toBe(0);
    expect(timeOfFrame(5, 24)).toBe(0.208);
  });
});
