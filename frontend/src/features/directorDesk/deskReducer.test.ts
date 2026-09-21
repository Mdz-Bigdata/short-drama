import { describe, expect, it } from 'vitest';

import { planResponse } from '../spatial/spatialFixtures';
import type { StageOperation } from '../spatial/spatialTypes';
import { deskReducer, initialDeskState, isRevisionConflict, type DeskAction, type DeskState } from './deskReducer';

const run = (state: DeskState, ...actions: DeskAction[]) => actions.reduce(deskReducer, state);
const loaded = () => run(initialDeskState, { type: 'loaded', response: planResponse() });
const edit = (id: number, operations: StageOperation[], kind: 'edit' | 'undo' | 'redo' = 'edit', label = '移动'): DeskAction => ({ type: 'edit', id, kind, label, operations });
const moveTo = (x: number): StageOperation => ({ op: 'move_actor', name: '林夏', position: [x, 0] });
const serverAt = (revision: number, x: number) => planResponse({}, {
  revision, actors: planResponse().plan.actors.map(actor => (actor.name === '林夏' ? { ...actor, position: [x, 0] as [number, number] } : actor)),
});

describe('selection', () => {
  it('replaces on a plain click, toggles with shift, and forgets what no longer exists', () => {
    let state = run(loaded(), { type: 'select', ref: { kind: 'actor', name: '林夏' } }, { type: 'select', ref: { kind: 'landmark', name: '录音笔' }, additive: true });
    expect(state.selection).toEqual([{ kind: 'actor', name: '林夏' }, { kind: 'landmark', name: '录音笔' }]);

    state = run(state, { type: 'select', ref: { kind: 'actor', name: '林夏' }, additive: true });
    expect(state.selection).toEqual([{ kind: 'landmark', name: '录音笔' }]);

    state = run(state, { type: 'select', ref: { kind: 'camera', id: 'cam-02' } });
    expect(state.selection).toEqual([{ kind: 'camera', id: 'cam-02' }]);

    state = run(state, { type: 'select', ref: { kind: 'landmark', name: '录音笔' } }, edit(1, [{ op: 'remove_landmark', name: '录音笔' }]));
    expect(state.selection).toEqual([]);
    expect(run(state, { type: 'clearSelection' })).toBe(state);
  });

  it('keeps tool, layout, snap, shot and measure state', () => {
    let state = run(loaded(), { type: 'setTool', tool: 'measure' }, { type: 'measure', point: { label: 'A', point: [0, 0, 0] } }, { type: 'measure', point: { label: 'B', point: [3, 0, 4] } });
    expect(state.measure).toHaveLength(2);
    state = run(state, { type: 'measure', point: { label: 'C', point: [1, 0, 1] } });
    expect(state.measure.map(item => item.label)).toEqual(['C']);
    state = run(state, { type: 'setTool', tool: 'move' }, { type: 'setLayout', layout: 'lens' }, { type: 'setSnap', snap: { gridSize: 0.5 } }, { type: 'setLensCamera', cameraId: 'cam-02' }, { type: 'setShot', shotId: 2 });
    expect(state).toMatchObject({ measure: [], tool: 'move', layout: 'lens', shotId: 2, lensCameraId: '' });
    expect(state.snap).toEqual({ grid: true, gridSize: 0.5, faces: true, angle: true });
    state = run(state, { type: 'toggleHidden', key: 'actor:林夏' }, { type: 'toggleLocked', key: 'actor:林夏' }, { type: 'toggleHidden', key: 'actor:林夏' });
    expect(state).toMatchObject({ hidden: [], locked: ['actor:林夏'] });
  });
});

describe('optimistic edits and history', () => {
  it('draws an edit at once, and only trusts it with history once the server has it', () => {
    let state = run(loaded(), edit(1, [moveTo(1)]));
    expect(state.plan?.actors[0].position).toEqual([1, 0]);
    expect(state.response?.plan.actors[0].position).toEqual([-1.3, 0]);
    expect(state).toMatchObject({ saveState: 'saving', undo: [] });
    expect(state.pending[0].inverse).toEqual([{ op: 'move_actor', name: '林夏', position: [-1.3, 0] }]);

    state = run(state, { type: 'applied', response: serverAt(4, 1), editIds: [1] });
    expect(state).toMatchObject({ saveState: 'saved', pending: [] });
    expect(state.undo).toEqual([{ label: '移动', forward: [moveTo(1)], inverse: [moveTo(-1.3)] }]);
    expect(state.plan?.revision).toBe(4);
  });

  it('keeps later unconfirmed edits on top of the plan an earlier one brought back', () => {
    const state = run(loaded(), edit(1, [moveTo(1)]), edit(2, [moveTo(2)]), { type: 'applied', response: serverAt(4, 1), editIds: [1] });
    expect(state.plan?.actors[0].position).toEqual([2, 0]);
    expect(state.saveState).toBe('saving');
    // The second edit's inverse was taken against the first edit's result, not against the server.
    expect(state.pending[0].inverse).toEqual([moveTo(1)]);
  });

  it('undoes and redoes through the same edit path, as inverse batches', () => {
    let state = run(loaded(), edit(1, [moveTo(1)]), { type: 'applied', response: serverAt(4, 1), editIds: [1] });
    const entry = state.undo[0];

    state = run(state, edit(2, entry.inverse, 'undo'));
    expect(state.undo).toEqual([]);                       // a second Ctrl+Z reaches the entry below
    expect(state.plan?.actors[0].position).toEqual([-1.3, 0]);
    state = run(state, { type: 'applied', response: serverAt(5, -1.3), editIds: [2] });
    expect(state.redo).toEqual([{ label: '移动', forward: [moveTo(1)], inverse: [moveTo(-1.3)] }]);

    state = run(state, edit(3, state.redo[0].forward, 'redo'), { type: 'applied', response: serverAt(6, 1), editIds: [3] });
    expect(state.redo).toEqual([]);
    expect(state.undo).toEqual([entry]);

    // A fresh edit is a new branch: what could be redone is gone.
    state = run(state, edit(4, entry.inverse, 'undo'), { type: 'applied', response: serverAt(7, -1.3), editIds: [4] }, edit(5, [moveTo(3)]), { type: 'applied', response: serverAt(8, 3), editIds: [5] });
    expect(state.redo).toEqual([]);
    expect(state.undo).toHaveLength(1);
  });

  it('reads the inverse of a server-made id off the answer', () => {
    const before = planResponse();
    const after = planResponse({}, {
      revision: 4,
      cameras: [...before.plan.cameras, { ...before.plan.cameras[0], id: 'alt-01-01' }],
      shots: [{ ...before.plan.shots[0], alt_camera_ids: ['alt-01-01'] }, before.plan.shots[1]],
    });
    let state = run(loaded(), edit(1, [{ op: 'add_camera', shot_id: 1, lens_mm: 35 }], 'edit', '添加机位'));
    expect(state.pending[0].inverse).toBeNull();
    state = run(state, { type: 'applied', response: after, editIds: [1] });
    expect(state.undo[0].inverse).toEqual([{ op: 'remove_camera', camera_id: 'alt-01-01' }]);

    // Undoing it is a removal, whose own inverse is known up front: add the same lens again.
    state = run(state, edit(2, state.undo[0].inverse, 'undo', '添加机位'), { type: 'applied', response: planResponse({}, { revision: 5 }), editIds: [2] });
    expect(state.redo[0].forward[0]).toMatchObject({ op: 'add_camera', shot_id: 1, position: [0, 1.45, 5.2] });
  });

  it('clears the history after an edit that cannot be taken back', () => {
    let state = run(loaded(), edit(1, [moveTo(1)]), { type: 'applied', response: serverAt(4, 1), editIds: [1] });
    state = run(state, { type: 'edit', id: 2, kind: 'edit', label: '删除群演', operations: [{ op: 'remove_crowd', crowd_id: 'crowd-01' }], irreversible: true }, { type: 'applied', response: serverAt(5, 1), editIds: [2] });
    expect(state).toMatchObject({ undo: [], redo: [] });
  });
});

describe('rejections', () => {
  const pendingTwo = () => run(loaded(), { type: 'select', ref: { kind: 'actor', name: '林夏' } }, edit(1, [moveTo(1)]), edit(2, [moveTo(2)]));

  it('rolls back to the confirmed plan and asks for a re-read on a revision conflict', () => {
    const state = run(pendingTwo(), { type: 'rejected', editIds: [1, 2], status: 409, message: '空间方案已在其他页面更新，请刷新后重试' });
    expect(state.plan?.actors[0].position).toEqual([-1.3, 0]);
    expect(state).toMatchObject({ pending: [], saveState: 'error', readOnly: '', reloadToken: 1 });
    expect(state.notice).toContain('空间方案已在其他页面更新');
    expect(state.notice).toContain('没有保存');

    // The re-read must not wipe the sentence that explains why the edit vanished.
    const reread = run(state, { type: 'loaded', response: planResponse({}, { revision: 9 }) });
    expect(reread.notice).toBe(state.notice);
    expect(reread).toMatchObject({ undo: [], saveState: 'idle' });
    expect(reread.plan?.revision).toBe(9);
  });

  it('goes read-only, in the server’s words, while generation holds the stage', () => {
    let state = run(pendingTwo(), { type: 'rejected', editIds: [1, 2], status: 409, message: '任务正在执行阶段，暂不能修改空间调度' });
    expect(state).toMatchObject({ readOnly: '任务正在执行阶段，暂不能修改空间调度', reloadToken: 0, pending: [] });
    const frozen = state;
    state = run(state, edit(3, [moveTo(5)]));
    expect(state).toBe(frozen);
    expect(run(state, { type: 'loaded', response: planResponse() }).readOnly).toBe('');
  });

  it('shows a 422 in the inspector and anything else as a notice', () => {
    const invalid = run(pendingTwo(), { type: 'rejected', editIds: [1, 2], status: 422, message: 'operations[0] move_actor：position 超出场地范围（±500 米）' });
    expect(invalid).toMatchObject({ inspectorError: 'operations[0] move_actor：position 超出场地范围（±500 米）', notice: '', readOnly: '' });
    expect(invalid.plan?.actors[0].position).toEqual([-1.3, 0]);
    expect(run(invalid, { type: 'select', ref: { kind: 'actor', name: '周教授' } }).inspectorError).toBe('');

    expect(run(pendingTwo(), { type: 'rejected', editIds: [1, 2], status: 502, message: '空间调度服务暂不可用，请稍后重试' }).notice).toBe('空间调度服务暂不可用，请稍后重试');
  });

  it('tells a newer revision from a generation lock', () => {
    expect(isRevisionConflict('空间方案已在其他页面更新，请刷新后重试')).toBe(true);
    expect(isRevisionConflict('任务正在执行阶段，暂不能修改空间调度')).toBe(false);
  });
});

describe('timeline edits', () => {
  const keys = [{ time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' }];
  const write: StageOperation = { op: 'set_timeline', shot_id: 1, camera: keys };

  it('draws a key at once and undoes it like any other edit', () => {
    const before = planResponse();
    let state = deskReducer(initialDeskState, { type: 'loaded', response: before });
    state = deskReducer(state, { type: 'edit', id: 1, kind: 'edit', label: '机位关键帧', operations: [write] });
    expect(state.plan?.timelines?.['1'].camera).toEqual(keys);
    expect(state.pending[0].inverse).toEqual([{ op: 'clear_timeline', shot_id: 1 }]);
    const after = planResponse({}, { revision: 4, timelines: { 1: { duration_s: 5, fps: 24, camera: keys as never, actors: {} } } });
    state = deskReducer(state, { type: 'applied', response: after, editIds: [1] });
    expect(state.undo).toEqual([{ label: '机位关键帧', forward: [write], inverse: [{ op: 'clear_timeline', shot_id: 1 }] }]);

    state = deskReducer(state, { type: 'edit', id: 2, kind: 'undo', label: '机位关键帧', operations: state.undo[0].inverse });
    expect(state.plan?.timelines).toEqual({});
    state = deskReducer(state, { type: 'applied', response: planResponse({}, { revision: 5 }), editIds: [2] });
    // Redo replays the inverse of the undo: the whole timeline that clear_timeline took away.
    expect(state.redo[0].forward).toEqual([{ op: 'set_timeline', shot_id: 1, duration_s: 5, fps: 24, camera: keys, actors: {} }]);
  });

  it('knows how to undo a camera-move preset before the server has answered', () => {
    let state = deskReducer(initialDeskState, { type: 'loaded', response: planResponse() });
    state = deskReducer(state, { type: 'edit', id: 1, kind: 'edit', label: '运镜：推近', operations: [{ op: 'apply_camera_move', shot_id: 1, preset: 'push' }] });
    expect(state.pending[0].inverse).toEqual([{ op: 'clear_timeline', shot_id: 1 }]);
  });
});

