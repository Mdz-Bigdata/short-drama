// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BlockoutPanel } from '../directorDesk/panels/BlockoutPanel';
import type { StagePlan } from '../spatial/spatialTypes';

const PLAN = { landmarks: [], cameras: [] } as unknown as StagePlan;

function panel(initialReference?: { url: string }) {
  return render(<BlockoutPanel taskId="t1" sceneId="S1" plan={PLAN} editable onCommit={() => undefined} onLook={() => undefined} initialReference={initialReference} />);
}

describe("the desk's reference hand-off", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('loads the connected picture as if chosen, and analyses nothing until asked', async () => {
    const urls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      urls.push(String(input));
      return { ok: true, status: 200, blob: async () => new Blob(['x'], { type: 'image/png' }) } as Response;
    });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:picture', revokeObjectURL: () => undefined }));
    panel({ url: 'http://localhost:8000/media/ref.png' });
    expect(await screen.findByAltText('所选参考图')).toBeTruthy();
    expect(urls).toEqual(['http://localhost:8000/media/ref.png']);
    await waitFor(() => expect((screen.getByRole('button', { name: '解析参考图' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('says so when the picture cannot be read, and leaves the manual way open', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, status: 404 } as Response);
    panel({ url: 'http://localhost:8000/media/gone.png' });
    expect(await screen.findByText('连接的参考图没能读取，请手动选择。')).toBeTruthy();
    expect(screen.getByRole('button', { name: '选择参考图' })).toBeTruthy();
  });

  it('without a hand-off it does not fetch anything', () => {
    const fetched = vi.spyOn(globalThis, 'fetch');
    panel();
    expect(fetched).not.toHaveBeenCalled();
  });
});
