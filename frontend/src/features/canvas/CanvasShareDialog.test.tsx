// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasShareDialog } from './CanvasShareDialog';
import { CanvasWorkspace } from './CanvasWorkspace';
import { shareExpiryDays, shareUrl } from './canvasShareApi';

vi.mock('../directorDesk/DirectorDesk', () => ({ DirectorDesk: () => null }));
vi.mock('./PanoramaViewer', () => ({ default: () => null }));

const SHARE_PATH = '/api/studio/projects/p1/canvases/main/share';

interface Call { method: string; path: string; body: unknown }

let calls: Call[];
let current: { token: string; url_path: string; expires_at: string | null; created_at: string } | null;
let tokens = 0;

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function nextShare(days: number | null) {
  tokens += 1;
  const token = `tok${String(tokens).padStart(16, '0')}`;
  const created = Date.parse('2026-11-10T00:00:00Z');
  return {
    token, url_path: `/share/canvas/${token}`, created_at: new Date(created).toISOString(),
    expires_at: days === null ? null : new Date(created + days * 86_400_000).toISOString(),
  };
}

function installServer(initial: typeof current = null) {
  calls = [];
  current = initial;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace('http://localhost:8000', '').split('?')[0];
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    calls.push({ method, path, body });
    if (path === SHARE_PATH && method === 'GET') return ok(current);
    if (path === SHARE_PATH && method === 'POST') {
      current = nextShare((body as { expires_days: number | null }).expires_days);
      return ok(current);
    }
    if (path === SHARE_PATH && method === 'DELETE') {
      const stopped = Boolean(current);
      current = null;
      return ok({ stopped });
    }
    // What the canvas workspace asks for when it opens.
    if (path === '/api/studio/tasks/t1/canvas-project') {
      return ok({ project_id: 'p1', task_id: 't1', canvases: [{ id: 'main', project_id: 'p1', title: '主画布', bookmarks: [], version: 1 }] });
    }
    if (path.endsWith('/canvas/run-options')) {
      return ok({ models: { image: '', video: '', audio: '' }, enabled: { image: [], video: [], audio: [] }, video_durations: [5], kinds: {} });
    }
    if (path.endsWith('/canvas/shots')) return ok({ shots: [] });
    if (path.endsWith('/canvas/outputs')) return ok({ version: 1, outputs: {}, latest: {}, history_counts: {}, running: 0 });
    if (path.endsWith('/canvas') && method === 'GET') return ok({ project_id: 'p1', version: 1, nodes: [], edges: [], created_at: '' });
    return ok({});
  });
}

function openDialog(onClose = vi.fn()) {
  render(<CanvasShareDialog projectId="p1" canvasId="main" canvasTitle="主画布" onClose={onClose} />);
  return onClose;
}

describe('CanvasShareDialog', () => {
  beforeEach(() => {
    tokens = 0;
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('creates a read-only link with the chosen validity and shows its full address', async () => {
    installServer();
    openDialog();
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('拿到链接的人不用登录就能看这张画布和其中的图片视频，不能修改。');
    fireEvent.click(await screen.findByLabelText('30 天'));
    fireEvent.click(screen.getByRole('button', { name: '创建只读链接' }));
    const input = await screen.findByLabelText('只读链接') as HTMLInputElement;
    expect(input.readOnly).toBe(true);
    expect(input.value).toBe(`${window.location.origin}/share/canvas/${current!.token}`);
    expect(calls.find(call => call.method === 'POST')?.body).toEqual({ expires_days: 30 });
    expect(dialog.textContent).toContain('到期');
  });

  it('offers forever as a validity', async () => {
    installServer();
    openDialog();
    fireEvent.click(await screen.findByLabelText('永久'));
    fireEvent.click(screen.getByRole('button', { name: '创建只读链接' }));
    await screen.findByLabelText('只读链接');
    expect(calls.find(call => call.method === 'POST')?.body).toEqual({ expires_days: null });
    expect(screen.getByText('永久有效')).toBeTruthy();
  });

  it('copies the link, and selects it when the clipboard is refused', async () => {
    installServer(nextShare(7));
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    openDialog();
    const input = await screen.findByLabelText('只读链接') as HTMLInputElement;
    fireEvent.click(screen.getByRole('button', { name: /复制链接/ }));
    await screen.findByText('已复制到剪贴板');
    expect(writeText).toHaveBeenCalledWith(input.value);

    writeText.mockRejectedValueOnce(new Error('denied'));
    const select = vi.spyOn(input, 'select');
    fireEvent.click(screen.getByRole('button', { name: /复制链接/ }));
    await screen.findByText(/已选中链接/);
    expect(select).toHaveBeenCalled();
  });

  it('rotates the link only after a confirmation, keeping its validity', async () => {
    installServer(nextShare(7));
    openDialog();
    const input = await screen.findByLabelText('只读链接') as HTMLInputElement;
    const before = input.value;
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: /换一个链接/ }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toContain('旧链接会立即失效');
    expect(calls.some(call => call.method === 'POST')).toBe(false);

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole('button', { name: /换一个链接/ }));
    await waitFor(() => expect(input.value).not.toBe(before));
    expect(calls.filter(call => call.method === 'POST')).toEqual([{ method: 'POST', path: SHARE_PATH, body: { expires_days: 7 } }]);
  });

  it('stops sharing after a confirmation and offers to create a new link', async () => {
    installServer(nextShare(1));
    openDialog();
    await screen.findByLabelText('只读链接');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: /停止分享/ }));
    expect(calls.some(call => call.method === 'DELETE')).toBe(false);
    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole('button', { name: /停止分享/ }));
    expect(await screen.findByRole('button', { name: '创建只读链接' })).toBeTruthy();
    expect(calls.filter(call => call.method === 'DELETE')).toHaveLength(1);
    expect(screen.queryByLabelText('只读链接')).toBeNull();
  });

  it('shows a failure from the server', async () => {
    installServer();
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: '分享服务不可用' }) } as Response);
    openDialog();
    expect((await screen.findByRole('alert')).textContent).toBe('分享服务不可用');
  });

  it('closes on Escape and on the close button', async () => {
    installServer();
    const onClose = openDialog();
    await screen.findByRole('button', { name: '创建只读链接' });
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('opens from the canvas toolbar for the current board', async () => {
    installServer();
    render(<CanvasWorkspace taskId="t1" onClose={vi.fn()} />);
    const toolbar = await screen.findByRole('toolbar', { name: '画布工具' });
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(within(toolbar).getByRole('button', { name: '分享' }));
    const dialog = await screen.findByRole('dialog', { name: '分享画布' });
    expect(within(dialog).getByText('主画布')).toBeTruthy();
    await within(dialog).findByRole('button', { name: '创建只读链接' });
    expect(calls.some(call => call.method === 'GET' && call.path === SHARE_PATH)).toBe(true);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '分享画布' })).toBeNull());
  });
});

describe('share helpers', () => {
  it('builds the address on the frontend origin', () => {
    expect(shareUrl({ url_path: '/share/canvas/abc' }, 'https://novara.example/')).toBe('https://novara.example/share/canvas/abc');
  });

  it('keeps the validity a link was made with', () => {
    expect(shareExpiryDays({ created_at: '2026-11-10T00:00:00Z', expires_at: null })).toBeNull();
    expect(shareExpiryDays({ created_at: '2026-11-10T00:00:00Z', expires_at: '2026-11-11T00:00:00Z' })).toBe(1);
    expect(shareExpiryDays({ created_at: '2026-11-10T00:00:00Z', expires_at: '2026-11-17T00:05:00Z' })).toBe(7);
    expect(shareExpiryDays({ created_at: '2026-11-10T00:00:00Z', expires_at: '2026-12-10T00:00:00Z' })).toBe(30);
  });
});
