import { describe, expect, it } from 'vitest';

import type { ActorKey, FollowClip, ShotTimeline, StageActor, StageCamera, StagePlan, StageShot } from '../../spatial/spatialTypes';
import { actionBlockAt, cutCameraAt, followPose, sampleActor, sampleShot } from './sampling';
import { addAction, addCut, addFollow, bakeFollow, figureForAction, moveBlock, nextBlockId, placeBlock, trimBlock, FOLLOW_PRESETS } from './timelineClips';
import { verticalFov } from './stageMath';

const FPS = 24;
const blocks = [{ id: 'a', start: 1, end: 2 }, { id: 'b', start: 3, end: 4 }];

const actor: StageActor = {
  id: 'a1', name: '林晚', position: [0, 0], yaw_deg: 0, height_m: 1.7, posture: 'stand', role: 'principal', screen_side: 'left', figure: 'humanoid',
};
const camera: StageCamera = {
  id: 'cam', label: '机位', position: [0, 1.5, -5], target: [0, 1.5, 0], lens_mm: 50, fov_deg: 39.6, aspect: '9:16', shot_size: '中景', angle: '平视',
  function: 'single', subjects: ['林晚'], move: { kind: 'static' },
};
const shot = { shot_id: 1, camera_id: 'cam', overrides: [], subjects: ['林晚'] } as unknown as StageShot;
const walk: ActorKey[] = [{ time: 0, position: [0, 0], yaw_deg: 90, easing: 'linear' }, { time: 4, position: [4, 0], yaw_deg: 90, easing: 'linear' }];

function planWith(timeline: Partial<ShotTimeline>, extra: Partial<StageCamera> = {}): StagePlan {
  return {
    aspect_ratio: '9:16', actors: [actor], cameras: [{ ...camera, ...extra }], shots: [shot],
    timelines: { 1: { duration_s: 5, fps: 24, camera: [], actors: {}, ...timeline } },
  } as unknown as StagePlan;
}

const behind: FollowClip = { id: 'follow-01', actor: '林晚', start: 0, end: 5, offset: [0, 0.3, 2], relative: 'actor', aim: 0.9, damping_s: 0, blend_s: 0, lens_mm: 50 };

describe('moving and trimming blocks', () => {
  it('a block slides until its neighbour stops it', () => {
    expect(moveBlock(blocks, 'a', 2.9, FPS, 5).find(block => block.id === 'a')).toEqual({ id: 'a', start: 2, end: 3 });
  });

  it('a block slides no further than the ends of the shot', () => {
    expect(moveBlock(blocks, 'a', -3, FPS, 5)[0]).toEqual({ id: 'a', start: 0, end: 1 });
    expect(moveBlock(blocks, 'b', 9, FPS, 5).find(block => block.id === 'b')).toEqual({ id: 'b', start: 4, end: 5 });
  });

  it('sliding snaps to a frame and keeps the length', () => {
    const moved = moveBlock([{ id: 'a', start: 0, end: 1 }], 'a', 1.01, FPS, 5)[0];
    expect(moved.start).toBe(1);
    expect(moved.end - moved.start).toBeCloseTo(1, 6);
  });

  it('trimming stops at the neighbour and never inverts the block', () => {
    expect(trimBlock(blocks, 'a', 'end', 9, FPS, 5)[0].end).toBe(3);
    const short = trimBlock(blocks, 'a', 'end', 0, FPS, 5)[0];
    expect(short.end).toBeGreaterThan(short.start);
    expect(trimBlock(blocks, 'b', 'start', 0, FPS, 5)[1].start).toBe(2);
  });

  it('a new block lands in the gap it is dropped in, or after the block under the playhead', () => {
    expect(placeBlock(blocks, 2.5, 3, FPS, 5)).toEqual({ start: 2.5, end: 3 });
    expect(placeBlock(blocks, 1.5, 3, FPS, 5)).toEqual({ start: 2, end: 3 });
    expect(placeBlock([{ id: 'a', start: 0, end: 5 }], 1, 2, FPS, 5)).toBeNull();
  });

  it('ids count past the ones in use', () => {
    expect(nextBlockId([{ id: 'clip-01', start: 0, end: 1 }], 'clip')).toBe('clip-02');
  });
});

describe('action clips', () => {
  const timeline: ShotTimeline = { duration_s: 5, fps: 24, camera: [], actors: {} };

  it('a one-off runs once, a loop runs a few seconds', () => {
    expect(addAction(timeline, '林晚', 'human-sit-enter-v1', 0)).toMatchObject({ start: 0, end: expect.closeTo(1.3, 1) });
    expect(addAction(timeline, '林晚', 'human-walk-v1', 1)).toMatchObject({ start: 1, end: 4 });
  });

  it('a skinned figure plays the motion from the start of the block, whatever frame is asked for', () => {
    const clips = [{ id: 'c', clip: 'human-walk-v1', start: 1, end: 3 }];
    expect(sampleActor(actor, [], 0.5, false, clips).pose?.clip).toBe('human-idle-v1');
    const at = sampleActor(actor, [], 1.5, false, clips);
    expect(at.pose?.clip).toBe('human-walk-v1');
    expect(at.pose?.clip_phase).toBeCloseTo(0.5 / 1.3333, 2);
    expect(sampleActor(actor, [], 1.5, false, clips)).toEqual(at);
  });

  it('a block owns its first instant and hands over at its last', () => {
    const clips = [{ id: 'c', clip: 'human-walk-v1', start: 1, end: 3 }];
    expect(actionBlockAt(clips, 1)?.id).toBe('c');
    expect(actionBlockAt(clips, 3)).toBeUndefined();
  });

  it('a one-off holds its last frame instead of looping', () => {
    const clips = [{ id: 'c', clip: 'human-sit-enter-v1', start: 0, end: 5 }];
    expect(sampleActor(actor, [], 4, false, clips).pose?.clip_phase).toBe(1);
  });

  it('speed plays the motion faster', () => {
    const clips = [{ id: 'c', clip: 'human-walk-v1', start: 0, end: 5, speed: 2 }];
    expect(sampleActor(actor, [], 0.5, false, clips).pose?.clip_phase).toBeCloseTo(1 / 1.3333, 2);
  });

  it('a jointed figure takes the matching preset and its walk moves', () => {
    const jointed = { ...actor, figure: 'mannequin' as const };
    const clips = [{ id: 'c', clip: 'human-walk-v1', start: 0, end: 5 }];
    const early = sampleActor(jointed, [], 0.25, false, clips).pose;
    const later = sampleActor(jointed, [], 0.75, false, clips).pose;
    expect(early?.preset).toBe('walk');
    expect(early?.joints?.['leftHip.pitch']).not.toBe(later?.joints?.['leftHip.pitch']);
  });

  it('a new key records the pose as authored, not a frame of the block', () => {
    const clips = [{ id: 'c', clip: 'human-walk-v1', start: 0, end: 5 }];
    expect(sampleActor(actor, [], 1, true, clips).pose).toBeNull();
  });

  it('a stand-in is switched to a figure with limbs; anyone else is left alone', () => {
    expect(figureForAction({ ...actor, figure: 'standin' })).toEqual([{ op: 'set_figure', name: '林晚', figure: 'humanoid' }]);
    expect(figureForAction({ ...actor, figure: undefined })).toHaveLength(1);
    expect(figureForAction(actor)).toEqual([]);
  });
});

describe('follow clips', () => {
  it('the lens stands behind the character and aims at them', () => {
    // Facing +X (yaw 90), so "back" is -X.
    const pose = followPose(behind, actor, walk, 2, 9 / 16, 36, 50);
    expect(pose.position).toEqual([0, 1.83, 0]);
    expect(pose.target).toEqual([2, 1.53, 0]);
  });

  it('"right" is the right of the way they face', () => {
    const side = { ...behind, offset: [1, 0, 0] as [number, number, number] };
    // Facing +X, a person's right hand points to -Z: geometry.py's right = (-fz, fx) on (x, z).
    const pose = followPose(side, actor, [{ time: 0, position: [0, 0], yaw_deg: 90, easing: 'linear' }], 0, 9 / 16, 36, 50);
    expect(pose.position[0]).toBeCloseTo(0, 5);
    expect(Math.abs(pose.position[2])).toBeCloseTo(1, 5);
  });

  it('world offsets ignore which way they turn', () => {
    const world = { ...behind, relative: 'world' as const };
    const pose = followPose(world, actor, walk, 2, 9 / 16, 36, 50);
    expect(pose.position).toEqual([2, 1.83, -2]);
  });

  it('damping lags behind a moving character by an average, and is the same frame in any order', () => {
    const damped = { ...behind, damping_s: 1 };
    const first = followPose(damped, actor, walk, 3, 9 / 16, 36, 50);
    expect(first.target[0]).toBeLessThan(3);
    expect(first.target[0]).toBeCloseTo(2.5, 5);
    followPose(damped, actor, walk, 1, 9 / 16, 36, 50);
    expect(followPose(damped, actor, walk, 3, 9 / 16, 36, 50)).toEqual(first);
  });

  it('sampleShot only ties the lens during the clip', () => {
    const plan = planWith({ actors: { 林晚: walk }, follow: [{ ...behind, start: 1, end: 3 }] });
    expect(sampleShot(plan, shot, 0.5).camera?.position).toEqual(camera.position);
    expect(sampleShot(plan, shot, 2).camera?.position).toEqual([0, 1.83, 0]);
    expect(sampleShot(plan, shot, 3.5).camera?.position).toEqual(camera.position);
  });

  it('a blend eases between the lens and the follow pose', () => {
    const plan = planWith({ follow: [{ ...behind, start: 0, end: 4, blend_s: 2 }] });
    const midway = sampleShot(plan, shot, 1).camera!;
    expect(midway.position[2]).toBeGreaterThan(camera.position[2]);
    expect(midway.position[2]).toBeLessThan(-2);
  });

  it('only the lens that films is tied; a candidate stays where it is', () => {
    const other = { ...camera, id: 'other', position: [9, 1, 9] as [number, number, number] };
    const plan = { ...planWith({ follow: [behind] }), cameras: [camera, other] } as StagePlan;
    expect(sampleShot(plan, shot, 1, 'other').camera?.position).toEqual([9, 1, 9]);
  });

  it('the sensor sets the field of view during a follow', () => {
    const plan = planWith({ follow: [behind] }, { sensor_mm: 18 });
    expect(sampleShot(plan, shot, 1).camera?.fov_deg).toBeCloseTo(verticalFov(50, 9 / 16, 18), 5);
  });

  it('presets add a block at the playhead', () => {
    const timeline: ShotTimeline = { duration_s: 8, fps: 24, camera: [], actors: {} };
    const preset = FOLLOW_PRESETS.find(item => item.id === 'top')!;
    expect(addFollow(timeline, '林晚', preset, 1)).toMatchObject({ actor: '林晚', start: 1, end: 6, relative: 'world', lens_mm: 28 });
  });

  it('baking writes the same travel as keys and takes the clip off', () => {
    const plan = planWith({ actors: { 林晚: walk }, follow: [behind] });
    const baked = bakeFollow(plan, shot) as unknown as { camera: Array<{ time: number; position: number[] }>; follow: FollowClip[] };
    expect(baked.follow).toEqual([]);
    expect(baked.camera.length).toBeGreaterThan(10);
    expect(baked.camera.length).toBeLessThanOrEqual(120);
    const middle = baked.camera.find(key => key.time === 2.5) ?? baked.camera[Math.floor(baked.camera.length / 2)];
    const live = sampleShot(plan, shot, middle.time).camera!;
    expect(middle.position[0]).toBeCloseTo(live.position[0], 1);
    expect(middle.position[2]).toBeCloseTo(live.position[2], 1);
  });
});

describe('camera cuts', () => {
  const other: StageCamera = { ...camera, id: 'alt', label: '反打', position: [5, 1.5, 0], target: [0, 1.5, 0] };
  const cutShot = { ...shot, alt_camera_ids: ['alt'] } as unknown as StageShot;
  const withCuts = (cuts: ShotTimeline['cuts']) => ({ ...planWith({ cuts }), cameras: [camera, other], shots: [cutShot] } as StagePlan);

  it('the shot is seen through the cut lens while the cut lasts, and its own lens outside it', () => {
    const plan = withCuts([{ id: 'cut-01', camera_id: 'alt', start: 1, end: 3 }]);
    expect(sampleShot(plan, cutShot, 0.5).camera?.position).toEqual(camera.position);
    expect(sampleShot(plan, cutShot, 2).camera?.position).toEqual(other.position);
    expect(sampleShot(plan, cutShot, 3).camera?.position).toEqual(camera.position);
  });

  it('a lens asked for by name wins over the cut', () => {
    const plan = withCuts([{ id: 'cut-01', camera_id: 'alt', start: 0, end: 5 }]);
    expect(sampleShot(plan, cutShot, 2, 'cam').camera?.position).toEqual(camera.position);
  });

  it('the cut lens is static: it does not take the filming lens keys', () => {
    const plan = { ...withCuts([{ id: 'c', camera_id: 'alt', start: 0, end: 5 }]), timelines: { 1: { duration_s: 5, fps: 24 as const, actors: {}, cuts: [{ id: 'c', camera_id: 'alt', start: 0, end: 5 }], camera: [
      { time: 0, position: [0, 1, -5] as [number, number, number], target: [0, 1, 0] as [number, number, number], lens_mm: 50, easing: 'linear' as const },
      { time: 5, position: [0, 9, -5] as [number, number, number], target: [0, 1, 0] as [number, number, number], lens_mm: 50, easing: 'linear' as const },
    ] } } } as StagePlan;
    expect(sampleShot(plan, cutShot, 2.5).camera?.position).toEqual(other.position);
  });

  it('cutCameraAt owns the first instant and hands over at the last', () => {
    const timeline = { cuts: [{ id: 'c', camera_id: 'alt', start: 1, end: 3 }] };
    expect(cutCameraAt(timeline, 1)).toBe('alt');
    expect(cutCameraAt(timeline, 3)).toBeUndefined();
    expect(cutCameraAt({}, 1)).toBeUndefined();
  });

  it('a new cut lands at the playhead and runs a couple of seconds', () => {
    const timeline: ShotTimeline = { duration_s: 5, fps: 24, camera: [], actors: {} };
    expect(addCut(timeline, 'alt', 1)).toEqual({ id: 'cut-01', camera_id: 'alt', start: 1, end: 3 });
    expect(addCut({ ...timeline, cuts: [{ id: 'cut-01', camera_id: 'alt', start: 0, end: 5 }] }, 'alt', 1)).toBeNull();
  });
});
