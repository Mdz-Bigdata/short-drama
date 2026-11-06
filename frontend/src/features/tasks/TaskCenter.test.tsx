// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '../../api/client';
import { TaskCenter, type TaskCenterJob, type TaskCenterView } from './TaskCenter';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);

function job(key: string, status: TaskCenterJob['status'], overrides: Partial<TaskCenterJob> = {}): TaskCenterJob {
  return {
    key, label: `标签 ${key}`, family: 'seedance', medium: 'video', bucket: 'seedance/video', depends_on: [], status, meta: {},
    can_cancel: status === 'queued', can_retry: status === 'failed', cancel_requested: false, log: [], ...overrides,
  };
}

function view(jobs: TaskCenterJob[], running = false): TaskCenterView {
  return {
    running, counts: { failed: 1, queued: 1 }, buckets: { 'seedance/video': { limit: 4, running: 0 } },
    progress: { settled: 1, total: jobs.length, percent: 50, running: 0, label: '' }, jobs,
  };
}

describe('TaskCenter', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(cleanup);

  it('lists jobs with status, ceilings and progress, and filters by status', async () => {
    mocked.mockResolvedValue(view([job('video:1', 'failed'), job('video:2', 'queued')]));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    expect(await screen.findByText('标签 video:1')).toBeTruthy();
    expect(mocked).toHaveBeenCalledWith('/api/drama/t1/tasks');
    expect(screen.getByText('seedance/video 0/4')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50');

    fireEvent.click(screen.getByRole('button', { name: /^排队中/ }));
    expect(screen.queryByText('标签 video:1')).toBeNull();
    expect(screen.getByText('标签 video:2')).toBeTruthy();
  });

  it('shows the error and log of a job when it is opened', async () => {
    mocked.mockResolvedValue(view([job('video:1', 'failed', {
      error: 'RuntimeError: no', failure: { message: '供应商原话' },
      log: [{ at: '2026-01-01T00:00:00+00:00', text: '进入队列' }],
    })]));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /标签 video:1/ }));
    expect(screen.getByText('供应商原话')).toBeTruthy();
    expect(screen.getByText('进入队列')).toBeTruthy();
  });

  it('offers cancel only on queued items and retry only on failed ones', async () => {
    mocked.mockResolvedValue(view([job('video:1', 'failed'), job('video:2', 'queued'), job('video:3', 'running')]));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    await screen.findByText('标签 video:3');
    expect(screen.getAllByRole('button', { name: '重试' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '取消' })).toHaveLength(1);
  });

  it('cancels and retries through the routes, encoding the key', async () => {
    mocked.mockResolvedValue(view([job('video:1', 'failed'), job('video:2', 'queued')]));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '取消' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/queue/video%3A2/cancel', expect.objectContaining({ method: 'POST' })));
    await screen.findByRole('status');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/tasks/video%3A1/retry', expect.objectContaining({ method: 'POST' })));
  });

  it('shows why a retry was refused by admission', async () => {
    mocked.mockImplementation(async (path: unknown) => {
      if (String(path).endsWith('/retry')) throw new ApiError('批量视频准入受阻，未重试：缺少首帧', 409);
      return view([job('video:1', 'failed')]);
    });
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '重试' }));
    expect((await screen.findByRole('alert')).textContent).toContain('缺少首帧');
  });

  it('says when the project has no jobs, and closes', async () => {
    mocked.mockResolvedValue(view([]));
    const onClose = vi.fn();
    render(<TaskCenter taskId="t1" onClose={onClose} />);
    expect(await screen.findByText('这个项目还没有生成任务')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('keeps polling while the run is going', async () => {
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout');
    mocked.mockResolvedValue(view([job('video:1', 'running')], true));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    await screen.findByText('标签 video:1');
    await waitFor(() => expect(setTimeoutSpy.mock.calls.some(call => call[1] === 3000)).toBe(true));
    setTimeoutSpy.mockRestore();
  });
});
