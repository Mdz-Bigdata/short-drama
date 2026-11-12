import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { ActionClip, ActorKey, CameraKey, StageActor, StagePlan } from '../../spatial/spatialTypes';
import {
  FRAME_RATES, actionBlockAt, actorPathsOf, cameraPathOf, cutCameraAt, cyclePhase, ease, frameCount, frameOf, gaitJoints, lastPlayheadFrame, lerpYaw, playheadFrame,
  sampleActor, sampleShot, snapToFrame, stagePlanAt, timeOfFrame,
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
    expect(snapToFrame(119.5 / 24, 24, 5)).toBeCloseTo(119 / 24);
    expect(snapToFrame(-1, 24, 5)).toBe(0);
    expect(timeOfFrame(5, 24)).toBe(0.208);
  });

  it('lets the playhead stand on the end of the shot, one frame past the last one an export draws', () => {
    expect(lastPlayheadFrame(5, 24)).toBe(120);
    expect(snapToFrame(5, 24, 5)).toBe(5);
    expect(snapToFrame(99, 24, 5)).toBe(5);
    expect(playheadFrame(5, 24, 5)).toBe(120);
    expect(playheadFrame(119.9 / 24, 24, 5)).toBe(119);
    // A move's last key is written at the duration itself; its frame is where the playhead ends.
    ([[5, 24], [2.5, 25], [3.5, 25], [3.7, 24], [3.3, 24], [4.1, 30], [1, 30]] as const).forEach(([duration, fps]) => {
      expect(lastPlayheadFrame(duration, fps)).toBe(frameOf(duration, fps));
      expect(playheadFrame(duration, fps, duration)).toBe(frameOf(duration, fps));
      expect(frameOf(snapToFrame(duration, fps, duration), fps)).toBe(frameOf(duration, fps));
      expect(snapToFrame(duration, fps, duration)).toBeLessThanOrEqual(duration);
      expect(lastPlayheadFrame(duration, fps)).toBeGreaterThanOrEqual(frameCount(duration, fps) - 1);
    });
  });

  it('shows the end of the shot on the last frame, though that frame starts a little before it', () => {
    // 3.3 s at 24 fps is 79.2 frames: the end rounds to frame 79, which starts at 3.2917 s.
    expect(snapToFrame(3.3, 24, 3.3)).toBe(3.3);
    expect(snapToFrame(79 / 24, 24, 3.3)).toBe(3.3);
    expect(snapToFrame(78.4 / 24, 24, 3.3)).toBeCloseTo(78 / 24);
    // A key that holds until the end is the picture of that frame, as the diamond under the playhead says.
    const held: CameraKey[] = [CAMERA_KEYS[0], { ...CAMERA_KEYS[1], time: 3.3, easing: 'hold' }];
    const plan: StagePlan = { ...PLAN, timelines: { 1: { duration_s: 3.3, fps: 24, camera: held, actors: {} } } };
    expect(frameOf(held[1].time, 24)).toBe(playheadFrame(79 / 24, 24, 3.3));
    expect(sampleShot(plan, plan.shots[0], snapToFrame(79 / 24, 24, 3.3)).camera!.position).toEqual([0, 1.5, 1]);
    expect(sampleShot(plan, plan.shots[0], snapToFrame(78 / 24, 24, 3.3)).camera!.position).toEqual([0, 1.5, 5]);
  });

  it('never stamps a key past the end of a shot that is not a whole number of frames long', () => {
    expect(timeOfFrame(63, 25)).toBe(2.52);
    expect(timeOfFrame(63, 25, 2.5)).toBe(2.5);
    expect(timeOfFrame(62, 25, 2.5)).toBe(2.48);
    expect(timeOfFrame(120, 24, 5)).toBe(5);
  });
});

describe('keys on the frame they were stamped on', () => {
  const DURATION = 5;

  it('reaches a hold key on its own frame though the millisecond rounding put it a little later', () => {
    // 1/24 s is stored as 0.042: export asks for 0.041667 and preview for the same instant.
    expect(timeOfFrame(1, 24)).toBe(0.042);
    FRAME_RATES.forEach(fps => {
      for (let frame = 1; frame < frameCount(DURATION, fps); frame += 1) {
        const stamped = timeOfFrame(frame, fps, DURATION);
        const camera: CameraKey[] = [CAMERA_KEYS[0], { ...CAMERA_KEYS[1], time: stamped, easing: 'hold' }];
        const actors: Record<string, ActorKey[]> = { 林夏: [{ time: 0, position: [0, 0], easing: 'linear' }, { time: stamped, position: [1, 0], easing: 'hold' }] };
        const plan: StagePlan = { ...PLAN, timelines: { 1: { duration_s: DURATION, fps, camera, actors } } };
        const at = (time: number) => sampleShot(plan, plan.shots[0], time);
        const label = `${fps} fps, frame ${frame}`;
        expect(at(frame / fps).camera!.position, label).toEqual([0, 1.5, 1]);
        expect(at(snapToFrame(frame / fps, fps, DURATION)).camera!.position, label).toEqual([0, 1.5, 1]);
        expect(at(frame / fps).actors['林夏'].position, label).toEqual([1, 0]);
        // The frame before still holds the key before.
        expect(at((frame - 1) / fps).camera!.position, label).toEqual([0, 1.5, 5]);
        expect(at((frame - 1) / fps).actors['林夏'].position, label).toEqual([0, 0]);
      }
    });
  });

  it('starts and ends a cut or a motion on the frames it was stamped between', () => {
    FRAME_RATES.forEach(fps => {
      for (let frame = 1; frame + 3 < frameCount(DURATION, fps); frame += 1) {
        const start = timeOfFrame(frame, fps, DURATION);
        const end = timeOfFrame(frame + 3, fps, DURATION);
        const timeline = { duration_s: DURATION, cuts: [{ id: 'cut-01', camera_id: 'cam-02', start, end }] };
        const clips: ActionClip[] = [{ id: 'act-01', clip: 'human-walk-v1', start, end }];
        const label = `${fps} fps, frame ${frame}`;
        expect(cutCameraAt(timeline, (frame - 1) / fps), label).toBeUndefined();
        expect(cutCameraAt(timeline, frame / fps), label).toBe('cam-02');
        expect(cutCameraAt(timeline, (frame + 2) / fps), label).toBe('cam-02');
        expect(cutCameraAt(timeline, (frame + 3) / fps), label).toBeUndefined();
        expect(actionBlockAt(clips, frame / fps, DURATION)?.id, label).toBe('act-01');
        expect(actionBlockAt(clips, (frame + 3) / fps, DURATION), label).toBeUndefined();
      }
    });
  });

  it('plays a motion reached a hair early from its first frame', () => {
    const human: StageActor = { ...PLAN.actors[0], figure: 'humanoid' };
    const clips: ActionClip[] = [{ id: 'act-01', clip: 'human-walk-v1', start: timeOfFrame(1, 24), end: 2 }];
    expect(sampleActor(human, undefined, 1 / 24, false, clips, DURATION).pose).toMatchObject({ clip: 'human-walk-v1', clip_phase: 0 });
  });

  it('exports an untouched plan whose keys sit exactly on frames just as before', () => {
    const z = [5, 1, 3, 2];
    const keys: CameraKey[] = [
      { time: 0, position: [0, 1.5, z[0]], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
      { time: 1, position: [0, 1.5, z[1]], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
      { time: 2.5, position: [0, 1.5, z[2]], target: [0, 1, 0], lens_mm: 28, easing: 'smooth' },
      { time: 4, position: [0, 1.5, z[3]], target: [0, 1, 0], lens_mm: 28, easing: 'ease-in' },
    ];
    // The plain reading of the keys: the span t falls in, eased into its later key.
    const expected = (t: number): number => {
      const index = keys.findIndex(key => t < key.time);
      if (index <= 0) return index === 0 ? z[0] : z[z.length - 1];
      const weight = ease((t - keys[index - 1].time) / (keys[index].time - keys[index - 1].time), keys[index].easing);
      return Math.round((z[index - 1] + (z[index] - z[index - 1]) * weight) * 1e4) / 1e4 + 0;
    };
    FRAME_RATES.forEach(fps => {
      const plan: StagePlan = { ...PLAN, timelines: { 1: { duration_s: 4, fps, camera: keys, actors: {} } } };
      for (let frame = 0; frame < frameCount(4, fps); frame += 1) {
        expect(sampleShot(plan, plan.shots[0], frame / fps).camera!.position[2], `${fps} fps, frame ${frame}`).toBe(expected(frame / fps));
      }
      // The keys that fall on a frame are drawn as keyed.
      keys.forEach((key, index) => {
        if (Number.isInteger(key.time * fps)) expect(sampleShot(plan, plan.shots[0], key.time).camera!.position[2]).toBe(z[index]);
      });
    });
  });
});
