// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../api/client';
import { fetchSpatialPlan, patchSpatialPlan } from '../spatial/spatialApi';
import { planResponse } from '../spatial/spatialFixtures';
import type { SpatialPlanResponse, StageOperation } from '../spatial/spatialTypes';
import { useDeskSession } from './useDeskSession';

vi.mock('../spatial/spatialApi', () => ({ fetchSpatialPlan: vi.fn(), patchSpatialPlan: vi.fn() }));

const moveTo = (x: number): StageOperation => ({ op: 'move_actor', name: '林夏', position: [x, 0] });
const serverAt = (revision: number, x: number) => planResponse({}, {
  revision, actors: planResponse().plan.actors.map(actor => (actor.name === '林夏' ? { ...actor, position: [x, 0] as [number, number] } : actor)),
});

describe('useDeskSession', () => {
  // Every PATCH waits here until the test answers it, so "still saving" is a state the test can stand in.
  let flights: Array<{ operations: StageOperation[]; resolve: (response: SpatialPlanResponse) => void; reject: (error: unknown) => void }> = [];
  const answer = (index: number, response: SpatialPlanResponse) => act(async () => { flights[index].resolve(response); });
  const fail = (index: number, error: unknown) => act(async () => { flights[index].reject(error); });

  beforeEach(() => {
    flights = [];
    vi.mocked(fetchSpatialPlan).mockReset().mockResolvedValue(planResponse());
    vi.mocked(patchSpatialPlan).mockReset().mockImplementation((_task, _scene, _revision, operations) => (
      new Promise((resolve, reject) => { flights.push({ operations, resolve, reject }); })
    ));
  });

  const open = async () => {
    const hook = renderHook(() => useDeskSession('task-1', 'scene-1'));
    await waitFor(() => expect(hook.result.current.editable).toBe(true));
    return hook;
  };

  it('holds an undo pressed while the edit is still saving, then takes back that edit', async () => {
    const { result } = await open();
    act(() => result.current.commit({ label: '第一步', operations: [moveTo(1)] }));
    await answer(0, serverAt(4, 1));
    act(() => result.current.commit({ label: '第二步', operations: [moveTo(2)] }));
    // The second step is not in the history yet, but it is what Ctrl+Z will reach.
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步']);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(flights).toHaveLength(2);                     // nothing sent: the first step stays where it is
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步']);

    await answer(1, serverAt(5, 2));
    expect(flights).toHaveLength(3);
    expect(flights[2].operations).toEqual([moveTo(1)]);  // the inverse of the second step, not of the first
    await answer(2, serverAt(6, 1));
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步']);
    expect(result.current.state.redo.map(entry => entry.label)).toEqual(['第二步']);
    expect(result.current.state.plan?.actors[0].position).toEqual([1, 0]);
  });

  it('replays held presses one at a time, each on the history the last one left', async () => {
    const { result } = await open();
    act(() => result.current.commit({ label: '第一步', operations: [moveTo(1)] }));
    await answer(0, serverAt(4, 1));
    act(() => result.current.commit({ label: '第二步', operations: [moveTo(2)] }));
    act(() => { result.current.undo(); result.current.undo(); });

    await answer(1, serverAt(5, 2));
    expect(flights).toHaveLength(3);
    await answer(2, serverAt(6, 1));
    expect(flights).toHaveLength(4);
    expect(flights[3].operations).toEqual([moveTo(-1.3)]);
    await answer(3, serverAt(7, -1.3));
    expect(result.current.state.undo).toEqual([]);
    expect(result.current.state.redo.map(entry => entry.label)).toEqual(['第二步', '第一步']);
    expect(result.current.canRedo).toBe(true);
  });

  it('forgets a held undo when the save fails or a new edit is made', async () => {
    const { result } = await open();
    act(() => result.current.commit({ label: '第一步', operations: [moveTo(1)] }));
    await answer(0, serverAt(4, 1));

    act(() => result.current.commit({ label: '第二步', operations: [moveTo(2)] }));
    act(() => result.current.undo());
    await fail(1, new ApiError('空间调度服务暂不可用，请稍后重试', 502));
    expect(flights).toHaveLength(2);                     // the edit it meant is gone: the first step is not touched
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步']);

    act(() => result.current.commit({ label: '第二步', operations: [moveTo(2)] }));
    act(() => result.current.undo());
    act(() => result.current.commit({ label: '第三步', operations: [moveTo(3)] }));
    await answer(2, serverAt(5, 2));
    await answer(3, serverAt(6, 3));
    expect(flights).toHaveLength(4);
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步', '第二步', '第三步']);
  });

  it('puts an undo that never reached the server back, and says so in Chinese', async () => {
    const { result } = await open();
    act(() => result.current.commit({ label: '第一步', operations: [moveTo(1)] }));
    await answer(0, serverAt(4, 1));
    expect(result.current.canRedo).toBe(false);

    act(() => result.current.undo());
    expect(result.current.state.undo).toEqual([]);
    expect(result.current.canRedo).toBe(true);           // the undo in flight is what redo will reach
    // A request that never arrived fails with the browser's own English sentence.
    await fail(1, new TypeError('Failed to fetch'));
    expect(result.current.state.notice).toBe('保存失败，请稍后重试。（刚才的修改没有保存，请重新操作）');
    expect(result.current.state.undo.map(entry => entry.label)).toEqual(['第一步']);
    expect(result.current.state.plan?.actors[0].position).toEqual([1, 0]);
    expect(result.current.canUndo).toBe(true);
  });

  it('shows the server’s sentence when there is one, and its own when the plan cannot be read', async () => {
    vi.mocked(fetchSpatialPlan).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const offline = renderHook(() => useDeskSession('task-1', 'scene-1'));
    await waitFor(() => expect(offline.result.current.state.loadError).toBe('空间调度读取失败。'));
    expect(offline.result.current.canUndo).toBe(false);
    offline.unmount();

    const { result } = await open();
    act(() => result.current.commit({ label: '第一步', operations: [moveTo(1)] }));
    await fail(0, new ApiError('空间调度服务暂不可用，请稍后重试', 502));
    expect(result.current.state.notice).toBe('空间调度服务暂不可用，请稍后重试（刚才的修改没有保存，请重新操作）');
  });
});
