// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { changedSinceStartup } from './diagnosticsReport';
import { SystemDiagnostics } from './SystemDiagnostics';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const check = (id: string, label: string, status: 'ok' | 'warning' | 'error', detail = '正常') => ({ id, label, status, detail, elapsed_ms: 1 });

const report = (checks: ReturnType<typeof check>[]) => ({
  status: checks.some(item => item.status === 'error') ? 'error' : checks.some(item => item.status === 'warning') ? 'warning' : 'ok',
  counts: {
    ok: checks.filter(item => item.status === 'ok').length,
    warning: checks.filter(item => item.status === 'warning').length,
    error: checks.filter(item => item.status === 'error').length,
  },
  checked_at: '2026-11-16T02:00:00+00:00',
  checks,
});

describe('changedSinceStartup', () => {
  it('names the checks whose status is different now', () => {
    const before = report([check('disk', '磁盘空间', 'ok'), check('ffmpeg', 'FFmpeg', 'ok')]);
    const now = report([check('disk', '磁盘空间', 'warning'), check('ffmpeg', 'FFmpeg', 'ok'), check('skills', '技能库', 'error')]);
    expect(changedSinceStartup(now as never, before as never).map(item => item.id)).toEqual(['disk']);
    expect(changedSinceStartup(now as never, null)).toEqual([]);
  });
});

describe('SystemDiagnostics', () => {
  it('asks for nothing until a button is pressed, then lists every check', async () => {
    const startup = report([check('disk', '磁盘空间', 'ok'), check('ffmpeg', 'FFmpeg', 'ok')]);
    const now = report([check('disk', '磁盘空间', 'warning', '剩余 3.0 GB，共 500 GB：快满了'), check('ffmpeg', 'FFmpeg', 'ok', '已找到：/usr/bin/ffmpeg')]);
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      { ok: true, status: 200, json: async () => ({ ...now, startup }) } as Response,
    );
    render(<SystemDiagnostics />);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '运行自检' }));
    expect(await screen.findByText('剩余 3.0 GB，共 500 GB：快满了')).toBeTruthy();
    expect(screen.getByText('已找到：/usr/bin/ffmpeg')).toBeTruthy();
    const verdict = screen.getByRole('status').textContent || '';
    expect(verdict).toContain('0 项有问题，1 项需留意');
    expect(verdict).toContain('启动时：2 项全部正常');
    expect(verdict).toContain('启动后有变化：磁盘空间');
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/platform/diagnostics');
  });

  it('saves the bundle under the name the server gave it', async () => {
    const created = vi.fn(() => 'blob:diagnostics');
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true, status: 200, blob: async () => new Blob(['zip']),
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="diagnostics-20261116-020000.zip"' }),
    } as Response);
    render(<SystemDiagnostics />);
    fireEvent.click(screen.getByRole('button', { name: '导出诊断包' }));
    await waitFor(() => expect(clicked).toEqual(['diagnostics-20261116-020000.zip']));
    expect(revoked).toHaveBeenCalledWith('blob:diagnostics');
  });

  it('says so when the check or the export is refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      { ok: false, status: 403, json: async () => ({ detail: '没有权限' }), headers: new Headers() } as Response,
    );
    render(<SystemDiagnostics />);
    fireEvent.click(screen.getByRole('button', { name: '运行自检' }));
    expect((await screen.findByRole('alert')).textContent).toBe('没有权限');
    fireEvent.click(screen.getByRole('button', { name: '导出诊断包' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('诊断包导出失败 (403)'));
  });
});
