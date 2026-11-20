// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasExportDialog } from './CanvasExportDialog';
import { isBundleFile } from './canvasBundleApi';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function open(overrides: Partial<Parameters<typeof CanvasExportDialog>[0]> = {}) {
  const props = { projectId: 'p1', canvasId: 'main', title: '雨夜', prepare: vi.fn(async () => 3), onExportJson: vi.fn(), onClose: vi.fn(), ...overrides };
  render(<CanvasExportDialog {...props} />);
  return props;
}

describe('exporting a canvas', () => {
  it('exports the plain JSON through the existing export and closes', () => {
    const props = open();
    fireEvent.click(screen.getByRole('button', { name: '导出 .json' }));
    expect(props.onExportJson).toHaveBeenCalledTimes(1);
    expect(props.onClose).toHaveBeenCalled();
  });

  it('saves first, then downloads the bundle under the name the server gives it', async () => {
    const fetched = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('zipbytes', {
      status: 200, headers: { 'Content-Disposition': "attachment; filename=\"canvas.zip\"; filename*=UTF-8''%E9%9B%A8%E5%A4%9C.novara-canvas.zip" },
    }));
    const created = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const props = open();
    fireEvent.click(screen.getByRole('button', { name: '打包 .zip' }));
    await screen.findByText(/已下载 雨夜\.novara-canvas\.zip/);
    expect(props.prepare).toHaveBeenCalledTimes(1);
    expect(String(fetched.mock.calls[0][0])).toContain('/api/studio/projects/p1/canvas/bundle?canvas_id=main');
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it('says why when packing is refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: '这块画布还没有内容，没有可导出的' }), { status: 422 }));
    open();
    fireEvent.click(screen.getByRole('button', { name: '打包 .zip' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('这块画布还没有内容，没有可导出的'));
  });

  it('tells a bundle from a plain export by its name or type', () => {
    expect(isBundleFile(new File(['x'], 'a.novara-canvas.zip'))).toBe(true);
    expect(isBundleFile(new File(['x'], 'a', { type: 'application/zip' }))).toBe(true);
    expect(isBundleFile(new File(['{}'], 'a.novara-canvas.json', { type: 'application/json' }))).toBe(false);
  });
});
