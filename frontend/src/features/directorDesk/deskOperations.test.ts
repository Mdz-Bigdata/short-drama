import { describe, expect, it } from 'vitest';

import { PLAN } from '../spatial/spatialFixtures';
import { actorsInShot, type StagePlan } from '../spatial/spatialTypes';
import { actorMoveOperation, applyAll, applyLocal, inverseFromDiff, inverseOf, poseOperation } from './deskOperations';

const CROWD = { id: 'crowd-01', label: '围观', rows: 1, columns: 2, spacing: 1, center: [4, 4] as [number, number], yaw_deg: 0, body_type: 'standard', seed: 7 };
const STAGE: StagePlan = {
  ...PLAN,
  crowds: [CROWD],
  actors: [
    ...PLAN.actors,
    { id: 'crowd-01-001', name: '围观-01', position: [3.5, 4], yaw_deg: 5, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
    { id: 'crowd-01-002', name: '围观-02', position: [4.5, 4], yaw_deg: -5, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
  ],
  cameras: [...PLAN.cameras, { ...PLAN.cameras[0], id: 'alt-01-01', label: '候选', position: [3, 1.5, 3] }],
  shots: [{ ...PLAN.shots[0], alt_camera_ids: ['alt-01-01'] }, PLAN.shots[1]],
};

describe('applyLocal', () => {
  it('previews moves, lens changes and landmark edits the way the server will answer them', () => {
    const next = applyAll(STAGE, [
      { op: 'move_actor', name: '林夏', position: [0, 1] },
      { op: 'move_camera', camera_id: 'cam-01', lens_mm: 50 },
      { op: 'transform_landmark', name: '录音笔', size: [1, 2, 3], shape: 'cone', yaw_deg: 45 },
      { op: 'add_landmark', name: '椅子', shape: 'cylinder', position: [2, 2], size: [0.5, 0.5, 1] },
    ]);
    expect(next.actors[0].position).toEqual([0, 1]);
    expect(next.cameras[0].lens_mm).toBe(50);
    expect(next.cameras[0].fov_deg).toBeCloseTo(39.6, 1);   // 36 mm tall back on a portrait frame
    expect(next.landmarks[0]).toMatchObject({ size: [1, 2, 3], shape: 'cone', yaw_deg: 45 });
    expect(next.landmarks[1]).toMatchObject({ name: '椅子', shape: 'cylinder', kind: 'prop' });
    expect(STAGE.actors[0].position).toEqual([-1.3, 0]);
  });

  it('carries a crowd as one rigid piece, the way crowds.moved does', () => {
    const moved = applyLocal(STAGE, { op: 'transform_crowd', crowd_id: 'crowd-01', center: [0, 0], yaw_deg: 90, spacing: 2 });
    const members = moved.actors.filter(actor => actor.crowd_id === 'crowd-01');
    // Offsets (∓0.5, 0) doubled to (∓1, 0), then turned a quarter: +X becomes -Z.
    expect(members.map(actor => actor.position)).toEqual([[0, 1], [0, -1]]);
    expect(members.map(actor => actor.yaw_deg)).toEqual([95, 85]);
    expect(moved.crowds?.[0]).toMatchObject({ center: [0, 0], yaw_deg: 90, spacing: 2 });
  });

  it('swaps the filming lens into the promoted candidate’s slot', () => {
    const next = applyLocal(STAGE, { op: 'use_camera', shot_id: 1, camera_id: 'alt-01-01' });
    expect(next.shots[0]).toMatchObject({ camera_id: 'alt-01-01', alt_camera_ids: ['cam-01'] });
  });

  it('sets the scene backdrop field by field and undoes it to what was there', () => {
    const lit = applyLocal(STAGE, { op: 'set_backdrop', kind: 'color', color: '#101820' });
    expect(lit.backdrop).toEqual({ kind: 'color', color: '#101820', url: '', yaw_deg: 0, opacity: 1 });
    // A plan stored before the desk had backdrops reads as one without a backdrop.
    expect(STAGE.backdrop).toBeUndefined();

    const shown = applyLocal(lit, { op: 'set_backdrop', kind: 'panorama', url: 'https://cdn.test/a.png', opacity: 0.4 });
    expect(shown.backdrop).toMatchObject({ kind: 'panorama', url: 'https://cdn.test/a.png', opacity: 0.4, color: '#101820' });

    expect(inverseOf(lit, [{ op: 'set_backdrop', kind: 'panorama', url: 'https://cdn.test/a.png', opacity: 0.4 }]))
      .toEqual([{ op: 'set_backdrop', kind: 'color', url: '', opacity: 1 }]);
    expect(inverseOf(STAGE, [{ op: 'set_backdrop', kind: 'color', color: '#101820' }]))
      .toEqual([{ op: 'set_backdrop', kind: 'none', color: '' }]);
  });

  it('leaves the plan alone for what only the server can resolve', () => {
    expect(applyLocal(STAGE, { op: 'frame_shot', shot_id: 1, size: '近景' })).toBe(STAGE);
    expect(applyLocal(STAGE, { op: 'add_camera', shot_id: 1 })).toBe(STAGE);
  });

  it('draws a new crowd before the server answers, under the id it will get', () => {
    const next = applyLocal(STAGE, { op: 'add_crowd', label: '士兵', rows: 2, columns: 3, spacing: 1, center: [0, -3], yaw_deg: 0, body_type: 'heavy', seed: 5 });
    expect(next.crowds?.[1]).toMatchObject({ id: 'crowd-02', label: '士兵', rows: 2, columns: 3 });
    expect(next.actors.filter(actor => actor.crowd_id === 'crowd-02')).toHaveLength(6);
    // A label the server would refuse is not drawn.
    expect(applyLocal(STAGE, { op: 'add_crowd', label: '围观', rows: 1, columns: 1 })).toBe(STAGE);
  });
});

describe('inverseOf', () => {
  it('restores exactly the fields an edit touched', () => {
    expect(inverseOf(STAGE, [{ op: 'move_actor', name: '林夏', position: [0, 1] }])).toEqual([{ op: 'move_actor', name: '林夏', position: [-1.3, 0] }]);
    expect(inverseOf(STAGE, [{ op: 'transform_landmark', name: '录音笔', yaw_deg: 30, color: '#ff0000' }]))
      .toEqual([{ op: 'transform_landmark', name: '录音笔', yaw_deg: 0, color: '' }]);
    expect(inverseOf(STAGE, [{ op: 'move_camera', camera_id: 'cam-01', lens_mm: 85 }])).toEqual([{ op: 'move_camera', camera_id: 'cam-01', lens_mm: 28 }]);
    expect(inverseOf(STAGE, [{ op: 'transform_crowd', crowd_id: 'crowd-01', center: [1, 1] }])).toEqual([{ op: 'transform_crowd', crowd_id: 'crowd-01', center: [4, 4] }]);
  });

  it('undoes a batch back to front, against the state each operation found', () => {
    expect(inverseOf(STAGE, [
      { op: 'move_actor', name: '林夏', position: [0, 1] },
      { op: 'move_actor', name: '林夏', position: [5, 5] },
      { op: 'add_landmark', name: '椅子' },
    ])).toEqual([
      { op: 'remove_landmark', name: '椅子' },
      { op: 'move_actor', name: '林夏', position: [0, 1] },
      { op: 'move_actor', name: '林夏', position: [-1.3, 0] },
    ]);
  });

  it('rebuilds what a removal took away', () => {
    expect(inverseOf(STAGE, [{ op: 'remove_landmark', name: '录音笔' }])).toEqual([
      { op: 'add_landmark', name: '录音笔', kind: 'prop', position: [0, -0.9], size: [0.5, 0.5, 0.5], yaw_deg: 0, shape: 'box', color: '' },
    ]);
    expect(inverseOf(STAGE, [{ op: 'remove_camera', camera_id: 'alt-01-01' }])).toEqual([
      { op: 'add_camera', shot_id: 1, label: '候选', position: [3, 1.5, 3], target: [0, 0.9, 0], lens_mm: 28 },
    ]);
    expect(inverseOf(STAGE, [{ op: 'remove_crowd', crowd_id: 'crowd-01' }])).toEqual([
      { op: 'add_crowd', label: '围观', rows: 1, columns: 2, spacing: 1, center: [4, 4], yaw_deg: 0, body_type: 'standard', seed: 7 },
    ]);
    expect(inverseOf(STAGE, [{ op: 'use_camera', shot_id: 1, camera_id: 'alt-01-01' }])).toEqual([{ op: 'use_camera', shot_id: 1, camera_id: 'cam-01' }]);
    expect(inverseOf(STAGE, [{ op: 'frame_shot', shot_id: 1, size: '特写' }])).toEqual([
      { op: 'move_camera', camera_id: 'cam-01', position: [0, 1.45, 5.2], target: [0, 0.9, 0], lens_mm: 28 },
    ]);
  });

  it('puts a shot override back, or clears one that was not there', () => {
    expect(inverseOf(STAGE, [{ op: 'set_shot_override', shot_id: 2, name: '助手', position: [1, 1] }]))
      .toEqual([{ op: 'set_shot_override', shot_id: 2, name: '助手', offstage: true, reason: '已退下' }]);
    expect(inverseOf(STAGE, [{ op: 'set_shot_override', shot_id: 1, name: '林夏', position: [1, 1] }]))
      .toEqual([{ op: 'clear_shot_override', shot_id: 1, name: '林夏' }]);
  });

  it('leaves a per-shot pose to set_pose', () => {
    const pose = { preset: 'wave', joints: { 'arm.r': 120 } };
    const posed: StagePlan = { ...STAGE, shots: [STAGE.shots[0], { ...STAGE.shots[1], overrides: [{ name: '林夏', position: [0, 2], pose }] }] };
    // Restaging keeps the pose server-side, so neither the edit nor its undo carries one.
    expect(actorMoveOperation(posed.shots[1], '林夏', { position: [1, 1] })).toEqual({ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [1, 1] });
    expect(inverseOf(posed, [{ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [1, 1] }]))
      .toEqual([{ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [0, 2] }]);
    // Clearing the override takes the pose with it: undo restages, then poses again.
    expect(inverseOf(posed, [{ op: 'clear_shot_override', shot_id: 2, name: '林夏' }])).toEqual([
      { op: 'set_shot_override', shot_id: 2, name: '林夏', position: [0, 2] },
      { op: 'set_pose', name: '林夏', shot_id: 2, preset: 'wave', joints: { 'arm.r': 120 } },
    ]);
  });

  it('defers to the server’s answer when ids are made there', () => {
    expect(inverseOf(STAGE, [{ op: 'add_camera', shot_id: 1 }])).toBeNull();
    expect(inverseOf(STAGE, [{ op: 'add_crowd', label: '士兵' }])).toBeNull();
  });
});

describe('inverseFromDiff', () => {
  it('removes whatever appeared and restores a lens that moved', () => {
    const after: StagePlan = {
      ...STAGE,
      actors: [...STAGE.actors, { ...STAGE.actors[3], id: 'crowd-02-001', name: '士兵-01', crowd_id: 'crowd-02' }],
      cameras: [{ ...STAGE.cameras[0], position: [0, 1.45, 2] }, ...STAGE.cameras.slice(1), { ...STAGE.cameras[0], id: 'alt-01-02' }],
    };
    expect(inverseFromDiff(STAGE, after)).toEqual([
      { op: 'remove_crowd', crowd_id: 'crowd-02' },
      { op: 'remove_camera', camera_id: 'alt-01-02' },
      { op: 'move_camera', camera_id: 'cam-01', position: [0, 1.45, 5.2], target: [0, 0.9, 0], lens_mm: 28 },
    ]);
  });
});

describe('actorMoveOperation', () => {
  it('edits the base mark unless the shot re-marks that actor', () => {
    expect(actorMoveOperation(PLAN.shots[0], '林夏', { position: [1, 1] })).toEqual({ op: 'move_actor', name: '林夏', position: [1, 1] });
    const shot = { ...PLAN.shots[1], overrides: [{ name: '林夏', position: [0, 2] as [number, number], hold: true }] };
    expect(actorMoveOperation(shot, '林夏', { position: [1, 1] })).toEqual({ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [1, 1], hold: true });
    // Only the position is pinned in that shot: turning the actor still turns the base mark.
    expect(actorMoveOperation(shot, '林夏', { yaw_deg: 30 })).toEqual({ op: 'move_actor', name: '林夏', yaw_deg: 30 });
  });
});

describe('figures and poses', () => {
  const SIT = { preset: 'sit', joints: { 'leftKnee.bend': 80 }, clip: '', clip_phase: 0 };
  const WAVE = { preset: 'wave', joints: { 'rightElbow.bend': 100 }, clip: '', clip_phase: 0 };

  it('previews a figure change and takes it back field by field', () => {
    const op = { op: 'set_figure', name: '林夏', figure: 'mannequin', body_type: 'slim' };
    const next = applyLocal(STAGE, op);
    expect(next.actors[0]).toMatchObject({ figure: 'mannequin', body_type: 'slim' });
    expect(inverseOf(STAGE, [op])).toEqual([{ op: 'set_figure', name: '林夏', figure: 'standin', body_type: 'standard' }]);
    expect(inverseOf(next, [{ op: 'set_figure', name: '林夏', color: '#ff0000' }])).toEqual([{ op: 'set_figure', name: '林夏', color: '' }]);
  });

  it('switches a whole crowd at once and takes every member back to what it was', () => {
    const mixed = applyLocal(STAGE, { op: 'set_figure', name: '围观-02', figure: 'humanoid' });
    const whole = { op: 'set_figure', crowd_id: 'crowd-01', figure: 'mannequin', body_type: 'heavy' };
    const next = applyLocal(mixed, whole);

    expect(next.actors.filter(actor => actor.crowd_id === 'crowd-01').map(actor => actor.figure)).toEqual(['mannequin', 'mannequin']);
    // The array records its own body type, so a member added later matches the rest.
    expect(next.crowds?.[0].body_type).toBe('heavy');
    expect(next.actors[0].figure).toBeUndefined();   // nobody outside the array is touched

    // The array's record goes back first; each member is then restored to its own figure.
    expect(inverseOf(mixed, [whole])).toEqual([
      { op: 'set_figure', crowd_id: 'crowd-01', body_type: 'standard' },
      { op: 'set_figure', name: '围观-01', figure: 'standin', body_type: 'standard' },
      { op: 'set_figure', name: '围观-02', figure: 'humanoid', body_type: 'standard' },
    ]);
    expect(applyAll(next, inverseOf(mixed, [whole]) || []).actors.filter(actor => actor.crowd_id).map(actor => actor.figure)).toEqual(['standin', 'humanoid']);
  });

  it('writes a pose to the mark, and to one shot only when the shot is named', () => {
    const posed = applyLocal(STAGE, poseOperation('林夏', undefined, SIT));
    expect(posed.actors[0].pose).toEqual(SIT);
    expect(actorsInShot(posed, posed.shots[1])[0].pose).toEqual(SIT);

    const oneShot = applyLocal(posed, poseOperation('林夏', 2, WAVE));
    expect(oneShot.actors[0].pose).toEqual(SIT);
    expect(actorsInShot(oneShot, oneShot.shots[0]).find(actor => actor.name === '林夏')?.pose).toEqual(SIT);
    expect(actorsInShot(oneShot, oneShot.shots[1]).find(actor => actor.name === '林夏')?.pose).toEqual(WAVE);
    // Someone else's override in that shot is untouched.
    expect(oneShot.shots[1].overrides.find(item => item.name === '助手')).toEqual({ name: '助手', offstage: true, reason: '已退下' });
  });

  it('takes a pose off with an empty set_pose, and an override that says nothing more goes with it', () => {
    const oneShot = applyLocal(STAGE, poseOperation('林夏', 2, WAVE));
    const cleared = applyLocal(oneShot, poseOperation('林夏', 2, null));
    expect(cleared.shots[1].overrides.map(item => item.name)).toEqual(['助手']);
    // An override that still re-marks the actor stays, without the pose.
    const staged = applyAll(STAGE, [{ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [1, 1] }, poseOperation('林夏', 2, WAVE)]);
    expect(staged.shots[1].overrides.find(item => item.name === '林夏')).toEqual({ name: '林夏', position: [1, 1], pose: WAVE });
    expect(applyLocal(staged, poseOperation('林夏', 2, null)).shots[1].overrides.find(item => item.name === '林夏')).toEqual({ name: '林夏', position: [1, 1] });
    // Restaging someone does not un-pose them (the server keeps the pose too).
    const restaged = applyLocal(staged, { op: 'set_shot_override', shot_id: 2, name: '林夏', position: [2, 2] });
    expect(restaged.shots[1].overrides.find(item => item.name === '林夏')).toEqual({ name: '林夏', position: [2, 2], pose: WAVE });
    expect(applyLocal(applyLocal(STAGE, poseOperation('林夏', undefined, SIT)), poseOperation('林夏', undefined, null)).actors[0].pose).toBeNull();
  });

  it('undoes a pose with the pose that was there, in the place it was', () => {
    expect(inverseOf(STAGE, [poseOperation('林夏', undefined, SIT)])).toEqual([poseOperation('林夏', undefined, null)]);
    const posed = applyLocal(STAGE, poseOperation('林夏', undefined, SIT));
    expect(inverseOf(posed, [poseOperation('林夏', undefined, WAVE)])).toEqual([poseOperation('林夏', undefined, SIT)]);
    // The base pose is not the per-shot one: undoing a first per-shot pose removes the override's pose.
    expect(inverseOf(posed, [poseOperation('林夏', 2, WAVE)])).toEqual([poseOperation('林夏', 2, null)]);
    expect(applyAll(posed, [poseOperation('林夏', 2, WAVE), ...inverseOf(posed, [poseOperation('林夏', 2, WAVE)])!])).toEqual(posed);
  });
});

describe('timelines', () => {
  const KEYS = [
    { time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
    { time: 3, position: [0, 1.5, 3], target: [0, 1, 0], lens_mm: 28, easing: 'smooth' },
  ];
  const WALK = { 林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 3, position: [0, 1], yaw_deg: 40, easing: 'smooth' }] };
  const first = { op: 'set_timeline', shot_id: 1, camera: KEYS };

  it('merges like the server: a sent field replaces the stored one whole, the rest stays', () => {
    const timed = applyLocal(STAGE, first);
    expect(timed.timelines?.['1']).toEqual({ duration_s: 5, fps: 24, camera: KEYS, actors: {} });
    const walked = applyAll(timed, [{ op: 'set_timeline', shot_id: 1, actors: WALK }, { op: 'set_timeline', shot_id: 1, duration_s: 8, fps: 30 }]);
    expect(walked.timelines?.['1']).toEqual({ duration_s: 8, fps: 30, camera: KEYS, actors: WALK });
    // An actor track with no keys left is not a track.
    expect(applyLocal(walked, { op: 'set_timeline', shot_id: 1, actors: { 林夏: [] } }).timelines?.['1'].actors).toEqual({});
    expect(applyLocal(walked, { op: 'clear_timeline', shot_id: 1 }).timelines).toEqual({});
    expect(applyLocal(STAGE, { op: 'set_timeline', shot_id: 77, duration_s: 3 })).toBe(STAGE);
    expect(applyLocal(STAGE, { op: 'clear_timeline', shot_id: 1 })).toBe(STAGE);
  });

  it('undoes a first key by clearing, a later edit by restoring exactly the fields it touched', () => {
    expect(inverseOf(STAGE, [first])).toEqual([{ op: 'clear_timeline', shot_id: 1 }]);
    const timed = applyLocal(STAGE, first);
    const edit = { op: 'set_timeline', shot_id: 1, camera: [KEYS[0]], duration_s: 9 };
    expect(inverseOf(timed, [edit])).toEqual([{ op: 'set_timeline', shot_id: 1, camera: KEYS, duration_s: 5 }]);
    expect(applyAll(timed, [edit, ...inverseOf(timed, [edit])!])).toEqual(timed);
    expect(inverseOf(timed, [{ op: 'clear_timeline', shot_id: 1 }])).toEqual([{ op: 'set_timeline', shot_id: 1, duration_s: 5, fps: 24, camera: KEYS, actors: {} }]);
    expect(inverseOf(STAGE, [{ op: 'clear_timeline', shot_id: 1 }])).toEqual([]);
    // Two edits of one track inside a batch restore the first state.
    const batch = [{ op: 'set_timeline', shot_id: 1, actors: WALK }, { op: 'set_timeline', shot_id: 1, actors: {} }];
    expect(applyAll(timed, [...batch, ...inverseOf(timed, batch)!])).toEqual(timed);
  });

  it('undoes a camera-move preset with the keys that were there before it', () => {
    const move = { op: 'apply_camera_move', shot_id: 1, preset: 'push', amplitude: 1 };
    expect(inverseOf(STAGE, [move])).toEqual([{ op: 'clear_timeline', shot_id: 1 }]);
    expect(inverseOf(applyLocal(STAGE, first), [move])).toEqual([{ op: 'set_timeline', shot_id: 1, camera: KEYS }]);
    // The keys themselves are the server's to lay out.
    expect(applyLocal(STAGE, move)).toBe(STAGE);
  });

  it('drops camera keys when another lens takes over the shot, and brings them back on undo', () => {
    const timed: StagePlan = { ...applyLocal(STAGE, first), shots: STAGE.shots.map(shot => (shot.shot_id === 1 ? { ...shot, alt_camera_ids: ['cam-02'] } : shot)) };
    const swap = { op: 'use_camera', shot_id: 1, camera_id: 'cam-02' };
    expect(applyLocal(timed, swap).timelines?.['1'].camera).toEqual([]);
    expect(inverseOf(timed, [swap])).toEqual([{ op: 'use_camera', shot_id: 1, camera_id: 'cam-01' }, { op: 'set_timeline', shot_id: 1, camera: KEYS }]);
    expect(applyAll(timed, [swap, ...inverseOf(timed, [swap])!]).timelines).toEqual(timed.timelines);
  });
});

