// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../api/client';
import { pendingCount, type SyncReview } from './canvasProjectSync';
import { CanvasProjectSyncDialog } from './CanvasProjectSyncDialog';

const api = vi.hoisted(() => ({ fetchSyncReview: vi.fn(), applySync: vi.fn() }));
vi.mock('./canvasProjectSync', async importOriginal => ({ ...await importOriginal<typeof import('./canvasProjectSync')>(), ...api }));

const REVIEW: SyncReview = {
  storyboard: true,
  version: 7,
  token: 'tok',
  followed: 6,
  new: {
    shots: 3, this_time: 3, later: 0,
    scenes: [
      { scene_id: 'E1S01', shots: 3, new: 1, on_canvas: true, this_time: true },
      { scene_id: 'E1S03', shots: 2, new: 2, on_canvas: false, this_time: true },
    ],
  },
  items: [
    { id: 'c1:prompt', node_id: 'c1', key: 'shot:E1S01:1:clip', field: 'prompt', state: 'update', label: 'E1S01 镜1 视频', scene: 'E1S01', shot: 1, canvas: '旧的画面', project: '新的画面', checked: true },
    { id: 'c1:duration', node_id: 'c1', key: 'shot:E1S01:1:clip', field: 'duration', state: 'update', label: 'E1S01 镜1 视频', scene: 'E1S01', shot: 1, canvas: 5, project: 6, checked: true },
    { id: 'c2:prompt', node_id: 'c2', key: 'shot:E1S01:2:clip', field: 'prompt', state: 'conflict', label: 'E1S01 镜2 视频', scene: 'E1S01', shot: 2, canvas: '我自己写的', project: '项目改的', checked: false },
    { id: 'b2:picture', node_id: 'b2', key: 'shot:E1S01:2:frame', field: 'picture', state: 'update', label: 'E1S01 镜2 分镜图', scene: 'E1S01', shot: 2, canvas: '/media/a.png', project: '/media/b.png', checked: true },
  ],
  notes: [{ kind: 'gone', node_id: 'g1', label: 'E1S02 镜1 视频', scene: 'E1S02', shot: 1 }],
};

function open(props: Partial<Parameters<typeof CanvasProjectSyncDialog>[0]> = {}) {
  const handlers = { prepare: vi.fn(async () => 7), onApplied: vi.fn(), onJump: vi.fn(), onClose: vi.fn() };
  render(<CanvasProjectSyncDialog projectId="p" canvasId="main" clientId="window-1" {...handlers} {...props} />);
  return handlers;
}

afterEach(() => {
  cleanup();
  api.fetchSyncReview.mockReset();
  api.applySync.mockReset();
});

describe('the sync count', () => {
  it('counts new shots and differences, not notes', () => {
    expect(pendingCount(REVIEW)).toBe(7);
    expect(pendingCount(null)).toBe(0);
  });
});

describe('syncing the canvas with the project', () => {
  it('saves first, then shows what would come in, with only the project-side changes ticked', async () => {
    api.fetchSyncReview.mockResolvedValue(REVIEW);
    const { prepare } = open();
    await screen.findByText('铺上 3 个新镜头');
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/E1S01 · 1 个，接在这一场原来那一排后面/)).toBeTruthy();
    expect(screen.getByText(/E1S03 · 2 个，新起一排/)).toBeTruthy();
    expect((screen.getByLabelText('用项目里的提示词：E1S01 镜1 视频') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('用项目里的提示词：E1S01 镜2 视频') as HTMLInputElement).checked).toBe(false);
    const conflicts = screen.getByRole('region', { name: '两边不一样' });
    expect(within(conflicts).getByText('我自己写的')).toBeTruthy();
    expect(within(conflicts).getByText('项目改的')).toBeTruthy();
    expect(screen.getByRole('region', { name: '项目里改了' }).querySelectorAll('img.cn-sync__thumb')).toHaveLength(2);
    expect(screen.getByText(/项目里已没有这一镜/)).toBeTruthy();
    // 3 new shots + 3 ticked changes.
    expect(screen.getByRole('button', { name: '同步（6 处）' })).toBeTruthy();
  });

  it('sends what the person kept, with the review it answers, and shows what changed', async () => {
    api.fetchSyncReview.mockResolvedValue(REVIEW);
    api.applySync.mockResolvedValue({ applied: true, version: 8, shots: 3, updated: 2, kept: 1, node_ids: ['n1', 'c1'] });
    const { onApplied } = open();
    await screen.findByText('铺上 3 个新镜头');
    fireEvent.click(screen.getByLabelText('用项目里的时长：E1S01 镜1 视频'));
    fireEvent.click(screen.getByLabelText('用项目里的提示词：E1S01 镜2 视频'));
    fireEvent.click(screen.getByRole('button', { name: '同步（6 处）' }));
    await screen.findByText('已同步：铺了 3 个镜头，更新 2 个节点，保留画布上的 1 处');
    const [projectId, canvasId, review, accept, addNew, clientId] = api.applySync.mock.calls[0];
    expect([projectId, canvasId, review.token, addNew, clientId]).toEqual(['p', 'main', 'tok', true, 'window-1']);
    expect([...accept].sort()).toEqual(['b2:picture', 'c1:prompt', 'c2:prompt']);
    expect(onApplied).toHaveBeenCalledWith(['n1', 'c1']);
  });

  it('can leave the new shots out', async () => {
    api.fetchSyncReview.mockResolvedValue(REVIEW);
    api.applySync.mockResolvedValue({ applied: true, version: 8, shots: 0, updated: 3, kept: 1, node_ids: [] });
    open();
    fireEvent.click(await screen.findByLabelText('铺上 3 个新镜头'));
    fireEvent.click(screen.getByRole('button', { name: '同步（3 处）' }));
    await waitFor(() => expect(api.applySync).toHaveBeenCalled());
    expect(api.applySync.mock.calls[0][4]).toBe(false);
  });

  it('says when the canvas already matches and offers nothing to apply', async () => {
    api.fetchSyncReview.mockResolvedValue({ ...REVIEW, new: { shots: 0, this_time: 0, later: 0, scenes: [] }, items: [], notes: [] });
    open();
    await screen.findByText('画布和项目分镜一致。');
    expect(screen.queryByRole('button', { name: /^同步/ })).toBeNull();
    expect(screen.getByRole('button', { name: '完成' })).toBeTruthy();
  });

  it('jumps to a node from a difference or a note', async () => {
    api.fetchSyncReview.mockResolvedValue(REVIEW);
    const { onJump } = open();
    fireEvent.click(await screen.findByRole('button', { name: '在画布上找到：E1S02 镜1 视频' }));
    expect(onJump).toHaveBeenCalledWith('g1');
  });

  it('offers to look again when things moved after the review', async () => {
    api.fetchSyncReview.mockResolvedValue(REVIEW);
    api.applySync.mockRejectedValue(new ApiError('查看之后，项目或画布又有了变化', 409));
    open();
    fireEvent.click(await screen.findByRole('button', { name: '同步（6 处）' }));
    await screen.findByText('查看之后，项目或画布又有了变化');
    fireEvent.click(screen.getByRole('button', { name: '重新对照' }));
    await waitFor(() => expect(api.fetchSyncReview).toHaveBeenCalledTimes(2));
  });

  it('does not review a canvas that cannot be saved', async () => {
    open({ prepare: vi.fn(async () => { throw new Error('画布还没保存成功，先解决保存问题。'); }) });
    await screen.findByText('画布还没保存成功，先解决保存问题。');
    expect(api.fetchSyncReview).not.toHaveBeenCalled();
  });
});
