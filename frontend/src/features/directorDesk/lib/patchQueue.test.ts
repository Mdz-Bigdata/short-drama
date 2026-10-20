import { describe, expect, it, vi } from 'vitest';

import { planResponse } from '../../spatial/spatialFixtures';
import type { SpatialPlanResponse, StageOperation } from '../../spatial/spatialTypes';
import { coalesceOperations, createPatchQueue } from './patchQueue';

interface Call {
  revision: number;
  operations: StageOperation[];
  solve?: boolean;
  resolve: (response: SpatialPlanResponse) => void;
  reject: (error: unknown) => void;
}

function fakeApi() {
  const calls: Call[] = [];
  const patch = (revision: number, operations: StageOperation[], options: { solve?: boolean }) => (
    new Promise<SpatialPlanResponse>((resolve, reject) => { calls.push({ revision, operations, solve: options.solve, resolve, reject }); })
  );
  return { calls, patch };
}

const at = (revision: number) => planResponse({}, { revision });
const move = (name: string, x: number): StageOperation => ({ op: 'move_actor', name, position: [x, 0] });
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

describe('coalesceOperations', () => {
  it('folds back-to-back edits of one object into the later one and keeps everything else in order', () => {
    expect(coalesceOperations([
      move('林夏', 1), { op: 'move_actor', name: '林夏', yaw_deg: 30 }, move('林夏', 2),
      move('周教授', 5), { op: 'move_camera', camera_id: 'cam-01', lens_mm: 35 }, move('林夏', 3),
      { op: 'add_landmark', name: '椅子' }, { op: 'add_landmark', name: '椅子' },
    ])).toEqual([
      { op: 'move_actor', name: '林夏', position: [2, 0], yaw_deg: 30 },
      move('周教授', 5), { op: 'move_camera', camera_id: 'cam-01', lens_mm: 35 }, move('林夏', 3),
      { op: 'add_landmark', name: '椅子' }, { op: 'add_landmark', name: '椅子' },
    ]);
  });
});

describe('coalesceOperations on timelines', () => {
  it('keeps only the later write of a field, per shot', () => {
    expect(coalesceOperations([
      { op: 'set_timeline', shot_id: 1, camera: ['a'], duration_s: 4 }, { op: 'set_timeline', shot_id: 1, camera: ['b'] },
      { op: 'set_timeline', shot_id: 2, camera: ['c'] },
    ])).toEqual([{ op: 'set_timeline', shot_id: 1, camera: ['b'], duration_s: 4 }, { op: 'set_timeline', shot_id: 2, camera: ['c'] }]);
  });
});

describe('createPatchQueue', () => {
  it('keeps one request in flight, merges what queued up behind it, and pins it to the newest revision', async () => {
    const api = fakeApi();
    const onApplied = vi.fn();
    const queue = createPatchQueue({ patch: api.patch, onApplied, onRejected: vi.fn() });
    queue.reset(3);

    queue.enqueue({ id: 1, operations: [move('林夏', 1)], solve: false });
    queue.enqueue({ id: 2, operations: [move('林夏', 2)], solve: false });
    queue.enqueue({ id: 3, operations: [move('林夏', 3)], solve: false });
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]).toMatchObject({ revision: 3, operations: [move('林夏', 1)], solve: false });
    expect(queue.busy()).toBe(true);

    api.calls[0].resolve(at(4));
    await settle();
    expect(onApplied).toHaveBeenLastCalledWith(at(4), [1]);
    expect(api.calls).toHaveLength(2);
    expect(api.calls[1]).toMatchObject({ revision: 4, operations: [move('林夏', 3)] });

    api.calls[1].resolve(at(5));
    await settle();
    expect(onApplied).toHaveBeenLastCalledWith(at(5), [2, 3]);
    expect(queue.busy()).toBe(false);
  });

  it('flies a barrier edit alone, in order', async () => {
    const api = fakeApi();
    const queue = createPatchQueue({ patch: api.patch, onApplied: vi.fn(), onRejected: vi.fn() });
    queue.reset(1);
    queue.enqueue({ id: 1, operations: [move('林夏', 1)] });
    queue.enqueue({ id: 2, operations: [move('林夏', 2)] });
    queue.enqueue({ id: 3, operations: [{ op: 'add_camera', shot_id: 1 }], barrier: true });
    queue.enqueue({ id: 4, operations: [move('林夏', 4)] });

    api.calls[0].resolve(at(2));
    await settle();
    expect(api.calls[1].operations).toEqual([move('林夏', 2)]);
    api.calls[1].resolve(at(3));
    await settle();
    expect(api.calls[2].operations).toEqual([{ op: 'add_camera', shot_id: 1 }]);
    api.calls[2].resolve(at(4));
    await settle();
    expect(api.calls[3]).toMatchObject({ revision: 4, operations: [move('林夏', 4)] });
  });

  it('only forbids re-solving when every merged edit forbids it', async () => {
    const api = fakeApi();
    const queue = createPatchQueue({ patch: api.patch, onApplied: vi.fn(), onRejected: vi.fn() });
    queue.reset(1);
    queue.enqueue({ id: 1, operations: [move('林夏', 1)], solve: false });
    queue.enqueue({ id: 2, operations: [move('周教授', 1)], solve: false });
    queue.enqueue({ id: 3, operations: [{ op: 'solve_camera' }] });
    api.calls[0].resolve(at(2));
    await settle();
    expect(api.calls[1].solve).toBeUndefined();
  });

  it('drops everything that was waiting when a request fails', async () => {
    const api = fakeApi();
    const onRejected = vi.fn();
    const queue = createPatchQueue({ patch: api.patch, onApplied: vi.fn(), onRejected });
    queue.reset(1);
    queue.enqueue({ id: 1, operations: [move('林夏', 1)] });
    queue.enqueue({ id: 2, operations: [move('林夏', 2)] });
    const error = new Error('空间方案已在其他页面更新，请刷新后重试');
    api.calls[0].reject(error);
    await settle();
    expect(onRejected).toHaveBeenCalledWith(error, [1, 2]);
    expect(api.calls).toHaveLength(1);
    expect(queue.busy()).toBe(false);
  });

  it('waits for an orphaned request before sending against a re-read plan', async () => {
    const api = fakeApi();
    const onApplied = vi.fn();
    const onRejected = vi.fn();
    const queue = createPatchQueue({ patch: api.patch, onApplied, onRejected });
    queue.reset(1);
    queue.enqueue({ id: 1, operations: [move('林夏', 1)] });
    queue.reset(7);                                   // the user re-read the plan mid-flight
    queue.enqueue({ id: 2, operations: [move('林夏', 2)] });
    expect(api.calls).toHaveLength(1);

    api.calls[0].resolve(at(8));                      // it landed after all: the server is at 8 now
    await settle();
    expect(onApplied).toHaveBeenLastCalledWith(at(8), []);
    expect(api.calls[1]).toMatchObject({ revision: 8, operations: [move('林夏', 2)] });
    expect(onRejected).not.toHaveBeenCalled();
  });
});
