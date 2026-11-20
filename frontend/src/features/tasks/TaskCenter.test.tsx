// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  // A returned mock would be called again by vitest as the hook's teardown.
  beforeEach(() => { mocked.mockReset(); });
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

  it('stays open on an Escape that only dismisses the input method or that a control inside handled', async () => {
    mocked.mockResolvedValue(view([]));
    const onClose = vi.fn();
    render(<TaskCenter taskId="t1" onClose={onClose} />);
    await screen.findByText('这个项目还没有生成任务');
    const close = screen.getByRole('button', { name: '关闭' });
    fireEvent.keyDown(close, { key: 'Escape', isComposing: true });
    fireEvent.keyDown(close, { key: 'Escape', keyCode: 229 });
    close.addEventListener('keydown', event => event.preventDefault(), { once: true });
    fireEvent.keyDown(close, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(close, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('says it is reading until the first answer comes', async () => {
    let answer: (value: TaskCenterView) => void = () => {};
    mocked.mockImplementation(() => new Promise(resolve => { answer = resolve; }));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    expect(screen.getByRole('status').textContent).toBe('正在读取任务…');
    await act(async () => { answer(view([])); });
    expect(screen.queryByText('正在读取任务…')).toBeNull();
    expect(screen.getByText('这个项目还没有生成任务')).toBeTruthy();
  });

  it('takes focus when it opens, keeps Tab inside and hands focus back when it closes', async () => {
    mocked.mockResolvedValue(view([job('video:1', 'failed')]));
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(<TaskCenter taskId="t1" onClose={() => {}} />);
    const close = screen.getByRole('button', { name: '关闭' });
    expect(document.activeElement).toBe(close);
    await screen.findByText('标签 video:1');

    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '重试' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab' });
    expect(document.activeElement).toBe(close);

    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('keeps polling while the run is going', async () => {
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout');
    mocked.mockResolvedValue(view([job('video:1', 'running')], true));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    await screen.findByText('标签 video:1');
    await waitFor(() => expect(setTimeoutSpy.mock.calls.some(call => call[1] === 3000)).toBe(true));
    setTimeoutSpy.mockRestore();
  });

  it('goes on polling after one failed read and clears the error when the next one works', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      let reply: () => Promise<TaskCenterView> = async () => view([job('video:1', 'running')], true);
      mocked.mockImplementation(() => reply());
      const { container } = render(<TaskCenter taskId="t1" onClose={() => {}} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(container.querySelector('.task-center__status--running')).toBeTruthy();

      reply = async () => { throw new Error('网络抖动'); };
      await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
      expect(screen.getByRole('alert').textContent).toContain('网络抖动');

      reply = async () => view([job('video:1', 'done')]);
      await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
      expect(screen.queryByRole('alert')).toBeNull();
      expect(container.querySelector('.task-center__status--done')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not retry a failed read when nothing was running', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      // The second read is the effect re-running once `running` turned false.
      mocked.mockResolvedValueOnce(view([job('video:1', 'done')])).mockRejectedValue(new Error('读不到'));
      render(<TaskCenter taskId="t1" onClose={() => {}} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByRole('alert').textContent).toContain('读不到');
      const calls = mocked.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
      expect(mocked.mock.calls.length).toBe(calls);
    } finally {
      vi.useRealTimers();
    }
  });

  it('drops the read error once a manual refresh works', async () => {
    mocked.mockResolvedValueOnce(view([job('video:1', 'done')])).mockRejectedValueOnce(new Error('读不到'));
    render(<TaskCenter taskId="t1" onClose={() => {}} />);
    expect((await screen.findByRole('alert')).textContent).toContain('读不到');

    mocked.mockResolvedValue(view([job('video:1', 'done')]));
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
});
