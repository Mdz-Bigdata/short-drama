import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { ActorKey, CameraKey, ShotTimeline, StagePlan } from '../../spatial/spatialTypes';
import {
  actorKeyAt, cameraKeyAt, durationRefusal, keyIndexAtFrame, lastKey, removeKey, retargetToKeys, retimeKey, trackOperation, upsertKey,
} from './timelineEdits';

const CAMERA: CameraKey[] = [
  { time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
  { time: 2, position: [0, 1.5, 3], target: [0, 1, 0], lens_mm: 28, easing: 'smooth' },
];
const WALK: ActorKey[] = [{ time: 0, position: [-1.3, 0], yaw_deg: 90, easing: 'linear' }, { time: 3.5, position: [1, 1], yaw_deg: 0, easing: 'smooth' }];
const TIMELINE: ShotTimeline = { duration_s: 4, fps: 24, camera: CAMERA, actors: { 林夏: WALK } };
const TIMED: StagePlan = { ...PLAN, timelines: { 1: TIMELINE } };

describe('timeline edits', () => {
  it('writes whole tracks', () => {
    expect(trackOperation(1, TIMELINE, { kind: 'camera' }, [CAMERA[0]])).toEqual({ op: 'set_timeline', shot_id: 1, camera: [CAMERA[0]] });
    const added = trackOperation(1, TIMELINE, { kind: 'actor', name: '周教授' }, [WALK[0]]);
    expect(added).toEqual({ op: 'set_timeline', shot_id: 1, actors: { 林夏: WALK, 周教授: [WALK[0]] } });
  });

  it('replaces the key on the same frame and keeps the track in order', () => {
    const replaced = upsertKey(CAMERA, { ...CAMERA[1], time: 2.001, lens_mm: 50 }, 24);
    expect(replaced.map(key => [key.time, key.lens_mm])).toEqual([[0, 28], [2.001, 50]]);
    expect(upsertKey(CAMERA, { ...CAMERA[1], time: 1 }, 24).map(key => key.time)).toEqual([0, 1, 2]);
    expect(removeKey(CAMERA, 0)).toEqual([CAMERA[1]]);
    expect(keyIndexAtFrame(CAMERA, 48, 24)).toBe(1);
    expect(keyIndexAtFrame(CAMERA, 47, 24)).toBe(-1);
  });

  it('retimes a key on whole frames and never onto a neighbour', () => {
    const three = upsertKey(CAMERA, { ...CAMERA[1], time: 1 }, 24);
    expect(retimeKey(three, 1, 1.26, 24, 4)[1].time).toBe(1.25);
    expect(retimeKey(three, 1, 5, 24, 4)[1].time).toBe(1.958);      // one frame before the key at 2 s
    expect(retimeKey(three, 1, -1, 24, 4)[1].time).toBe(0.042);     // one frame after the key at 0 s
    expect(retimeKey(three, 2, 99, 24, 4)[2].time).toBe(4);
  });

  it('refuses a duration that would cut a key off, naming it', () => {
    expect(lastKey(TIMELINE)).toEqual({ track: { kind: 'actor', name: '林夏' }, time: 3.5 });
    expect(durationRefusal(TIMELINE, 3)).toBe('时长不能短于最后一个关键帧：「林夏」轨在 3.50 秒还有一帧，请先移动或删除它');
    expect(durationRefusal({ ...TIMELINE, actors: {} }, 1.5)).toContain('机位轨在 2.00 秒');
    expect(durationRefusal(TIMELINE, 3.5)).toBe('');
    expect(durationRefusal(TIMELINE, 0.5)).toContain('1 到 30 秒');
    expect(durationRefusal(TIMELINE, 31)).toContain('1 到 30 秒');
    expect(durationRefusal(TIMELINE, Number.NaN)).toContain('1 到 30 秒');
  });

  it('captures the lens and a whole figure as keys', () => {
    expect(cameraKeyAt({ position: [0.123, 1.456, 2.789], target: [0, 1, 0], lens_mm: 35.04 }, 1.5)).toEqual({
      time: 1.5, position: [0.12, 1.46, 2.79], target: [0, 1, 0], lens_mm: 35, easing: 'smooth',
    });
    const pose = { preset: 'wave', joints: { 'leftShoulder.pitch': 120 }, clip: '', clip_phase: 0 };
    expect(actorKeyAt({ position: [1.004, 2], yaw_deg: 45.678, pose }, 2)).toEqual({ time: 2, position: [1, 2], yaw_deg: 45.68, pose, easing: 'smooth' });
    expect('pose' in actorKeyAt({ position: [1, 2], yaw_deg: 0, pose: null }, 2)).toBe(false);
  });
});

describe('retargetToKeys', () => {
  const shot = TIMED.shots[0];

  it('sends an edit made on a key into that key', () => {
    const drag = [{ op: 'move_actor', name: '林夏', position: [0, 0.5] }];
    const onKey = retargetToKeys(TIMED, shot, 3.5, drag);
    expect(onKey.tracks).toEqual([{ kind: 'actor', name: '林夏' }]);
    expect(onKey.operations).toEqual([{ op: 'set_timeline', shot_id: 1, actors: { 林夏: [WALK[0], { ...WALK[1], position: [0, 0.5] }] } }]);

    const turned = retargetToKeys(TIMED, shot, 0, [{ op: 'move_actor', name: '林夏', yaw_deg: 30 }]).operations[0];
    expect((turned.actors as Record<string, ActorKey[]>)['林夏'][0]).toEqual({ ...WALK[0], yaw_deg: 30 });
  });

  it('leaves the base plan to every other edit', () => {
    const drag = [{ op: 'move_actor', name: '林夏', position: [0, 0.5] }];
    expect(retargetToKeys(TIMED, shot, 1, drag)).toEqual({ operations: drag, tracks: [] });
    const other = [{ op: 'move_actor', name: '周教授', position: [2, 2] }];
    expect(retargetToKeys(TIMED, shot, 0, other).operations).toBe(other);
    expect(retargetToKeys(PLAN, PLAN.shots[0], 0, drag).operations).toBe(drag);
  });

  it('moves the filming lens through its key, and only that lens', () => {
    const edit = [{ op: 'move_camera', camera_id: 'cam-01', position: [1, 2, 3], lens_mm: 40 }, { op: 'move_camera', camera_id: 'cam-02', lens_mm: 85 }];
    const result = retargetToKeys(TIMED, shot, 2, edit);
    expect(result.operations).toEqual([
      edit[1],
      { op: 'set_timeline', shot_id: 1, camera: [CAMERA[0], { ...CAMERA[1], position: [1, 2, 3], lens_mm: 40 }] },
    ]);
  });

  it('writes a pose set on a key into the key, and batches a multi-select drag into one write', () => {
    const posed = retargetToKeys(TIMED, shot, 0, [{ op: 'set_pose', name: '林夏', preset: 'wave', joints: { 'leftElbow.bend': 60 }, clip: '', clip_phase: 0 }]);
    expect((posed.operations[0].actors as Record<string, ActorKey[]>)['林夏'][0].pose).toEqual({ preset: 'wave', joints: { 'leftElbow.bend': 60 }, clip: '', clip_phase: 0 });

    const both = retargetToKeys(TIMED, shot, 0, [{ op: 'move_actor', name: '林夏', position: [0, 0] }, { op: 'move_camera', camera_id: 'cam-01', position: [0, 2, 6] }]);
    expect(both.operations).toHaveLength(1);
    expect(Object.keys(both.operations[0]).sort()).toEqual(['actors', 'camera', 'op', 'shot_id']);
  });

  it('keeps the rest of a re-mark with the shot while its place goes to the key', () => {
    const plan: StagePlan = { ...TIMED, shots: TIMED.shots.map(item => (item.shot_id === 1 ? { ...item, overrides: [{ name: '林夏', position: [-1, 0], hold: true, reason: '' }] } : item)) };
    const dragged = retargetToKeys(plan, plan.shots[0], 0, [{ op: 'set_shot_override', shot_id: 1, name: '林夏', position: [0, 0], hold: true, reason: '' }]);
    // Nothing about the re-mark itself changed, so only the key is written.
    expect(dragged.operations.map(op => op.op)).toEqual(['set_timeline']);
    const released = retargetToKeys(plan, plan.shots[0], 0, [{ op: 'set_shot_override', shot_id: 1, name: '林夏', position: [0, 0], hold: false, reason: '' }]);
    expect(released.operations[0]).toEqual({ op: 'set_shot_override', shot_id: 1, name: '林夏', position: [-1, 0], hold: false, reason: '' });
  });
});
