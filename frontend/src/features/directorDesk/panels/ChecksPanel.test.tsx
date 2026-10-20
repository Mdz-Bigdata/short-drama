// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { SpatialRepairsResponse, StagePlan } from '../../spatial/spatialTypes';
import { ChecksPanel } from './ChecksPanel';

const REPAIRS_URL = 'http://localhost:8000/api/drama/t1/spatial/scenes/E1S01/repairs';
const SPREAD = [{ op: 'move_actor', name: '助手', position: [0.8, -2.3] }];
const REPAIRS: SpatialRepairsResponse = {
  schemaVersion: 'spatial-stage.v1', taskId: 't1', sceneId: 'E1S01', revision: 3,
  repairs: [{ code: 'spatial_subject_occlusion', label: '拉开站位', detail: '把助手往画右挪 0.8 米', shotIds: [2], operations: SPREAD, manual: '', automatic: true }],
  operations: SPREAD, automatic: 1, manual: 0,
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('ChecksPanel', () => {
  const fetchMock = vi.fn();
  const onCommit = vi.fn();
  const onSelectShot = vi.fn();
  const repairCalls = () => fetchMock.mock.calls.filter(call => String(call[0]) === REPAIRS_URL);
  const panel = (props: Partial<Parameters<typeof ChecksPanel>[0]> = {}) => (
    <ChecksPanel taskId="t1" sceneId="E1S01" plan={PLAN} shotId={1} editable saving={false} onCommit={onCommit} onSelectShot={onSelectShot} {...props} />
  );

  beforeEach(() => {
    onCommit.mockReset();
    onSelectShot.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation(() => json(REPAIRS));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists every check with its mark, severity and shots, and counts the failures in the header', async () => {
    render(panel());
    expect(screen.getByText('1 项未通过')).toBeTruthy();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0].className).toContain('is-passed');
    expect(within(items[0]).getByText('通过')).toBeTruthy();
    expect(items[1].className).toContain('is-warning');
    expect(within(items[1]).getByText('提示')).toBeTruthy();
    expect(within(items[1]).getByText(/第2镜的林夏被助手挡住/)).toBeTruthy();

    await userEvent.click(within(items[1]).getByRole('button', { name: '切换到第 2 镜' }));
    expect(onSelectShot).toHaveBeenCalledWith(2);
    // The 修正 button only shows once the repairs are in, after the debounce.
    expect(await screen.findByRole('button', { name: '修正' })).toBeTruthy();
    expect(repairCalls()).toHaveLength(1);
    expect((repairCalls()[0][1] as RequestInit).signal).toBeInstanceOf(AbortSignal);
  });

  it('commits one repair, and all of them, through the desk edit path as a barrier edit', async () => {
    render(panel());
    await userEvent.click(await screen.findByRole('button', { name: '修正' }));
    expect(onCommit).toHaveBeenCalledWith({ label: '修正：拉开站位', operations: SPREAD, barrier: true });

    await userEvent.click(screen.getByRole('button', { name: '一键修正 (1)' }));
    expect(onCommit).toHaveBeenLastCalledWith({ label: '一键修正', operations: SPREAD, barrier: true });
  });

  it('never asks for repairs when every check passes', async () => {
    const clean: StagePlan = { ...PLAN, checks: PLAN.checks.map(check => ({ ...check, passed: true, shot_ids: [] })) };
    render(panel({ plan: clean }));
    expect(screen.getByText('全部通过')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /一键修正/ })).toBeNull();
    await new Promise(resolve => setTimeout(resolve, 400));
    expect(repairCalls()).toHaveLength(0);
  });

  it('shows what the person has to decide when a repair cannot be automatic', async () => {
    fetchMock.mockImplementation(() => json({
      ...REPAIRS,
      repairs: [{ ...REPAIRS.repairs[0], label: '需人工处理', operations: [], manual: '两人都在说话，请先决定谁让位。', automatic: false }],
      operations: [], automatic: 0, manual: 1,
    }));
    render(panel());
    expect((await screen.findByRole('note')).textContent).toBe('需人工处理：两人都在说话，请先决定谁让位。');
    expect(screen.queryByRole('button', { name: '修正' })).toBeNull();
    expect(screen.getByRole('button', { name: '一键修正 (0)' })).toHaveProperty('disabled', true);
  });

  it('asks once per settled revision, and drops an answer meant for another revision', async () => {
    const { rerender } = render(panel());
    // Two revisions inside the debounce window: only the last one reaches the server.
    rerender(panel({ plan: { ...PLAN, revision: 4 } }));
    await waitFor(() => expect(repairCalls()).toHaveLength(1));
    await new Promise(resolve => setTimeout(resolve, 400));
    expect(repairCalls()).toHaveLength(1);
    // The server answered for revision 3; this plan is revision 4, so its operations are not offered.
    expect(screen.queryByRole('button', { name: '修正' })).toBeNull();
    expect(screen.getByRole('status').textContent).toBe('正在整理修正建议…');

    rerender(panel({ plan: { ...PLAN, revision: 5 } }));
    fetchMock.mockImplementation(() => json({ ...REPAIRS, revision: 5 }));
    expect(await screen.findByRole('button', { name: '修正' })).toBeTruthy();
    expect(repairCalls()).toHaveLength(2);
  });

  it('holds the buttons while the desk cannot edit or is still saving', async () => {
    const { rerender } = render(panel({ editable: false }));
    const fix = await screen.findByRole('button', { name: '修正' });
    expect(fix).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: '一键修正 (1)' })).toHaveProperty('disabled', true);

    rerender(panel({ saving: true }));
    expect(screen.getByRole('button', { name: '修正' })).toHaveProperty('disabled', true);
    rerender(panel());
    expect(screen.getByRole('button', { name: '修正' })).toHaveProperty('disabled', false);
  });

  it('says when the repairs could not be read and tries again on request', async () => {
    fetchMock.mockImplementationOnce(() => json({ detail: '本场还没有空间方案' }, 404));
    render(panel());
    expect((await screen.findByRole('alert')).textContent).toContain('本场还没有空间方案');
    await userEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByRole('button', { name: '修正' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
