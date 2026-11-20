// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasStoryboardDialog } from './CanvasStoryboardDialog';

const PATH = '/api/studio/projects/p1/canvas/storyboard';

interface Call { method: string; path: string; body: any }

function installServer(scenes: { scene_id: string; shots: number; new: number }[], maxShots = 120) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace('http://localhost:8000', '').split('?')[0];
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    calls.push({ method, path, body });
    if (path !== PATH) return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) } as Response;
    if (method === 'GET') return { ok: true, status: 200, json: async () => ({ scenes, max_shots: maxShots }) } as Response;
    return {
      ok: true, status: 200,
      json: async () => ({ applied: true, shots: 3, skipped: 0, frames_to_draw: 2, cast: 1, scenes: body.scene_ids, version: 8, node_ids: ['n1', 'n2'] }),
    } as Response;
  });
  return calls;
}

function open(overrides: Partial<Parameters<typeof CanvasStoryboardDialog>[0]> = {}) {
  const props = { projectId: 'p1', canvasId: 'main', prepare: vi.fn(async () => 7), onApplied: vi.fn(), onClose: vi.fn(), ...overrides };
  render(<CanvasStoryboardDialog {...props} />);
  return props;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('laying the storyboard out on the canvas', () => {
  it('lists the scenes, picks the ones with shots still to lay out, and applies on the saved version', async () => {
    const calls = installServer([{ scene_id: 'E1S01', shots: 2, new: 2 }, { scene_id: 'E1S02', shots: 1, new: 0 }, { scene_id: 'E1S03', shots: 4, new: 1 }]);
    const props = open();

    expect(await screen.findByText('E1S01')).toBeTruthy();
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes.map(box => [box.checked, box.disabled])).toEqual([[true, false], [false, true], [true, false]]);
    expect(screen.getByText('1 个镜头，都已在画布上')).toBeTruthy();
    expect(screen.getByText('4 个镜头，其中 1 个还没铺')).toBeTruthy();
    expect(screen.getByText('将铺 3 个镜头')).toBeTruthy();

    fireEvent.click(boxes[2]);
    expect(screen.getByText('将铺 2 个镜头')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '铺到画布' }));

    await waitFor(() => expect(props.onApplied).toHaveBeenCalledWith(['n1', 'n2']));
    expect(props.prepare).toHaveBeenCalledTimes(1);
    const post = calls.find(call => call.method === 'POST')!;
    expect(post.body).toEqual({ scene_ids: ['E1S01'], preview: false, expected_version: 7 });
    expect(screen.getByText('已铺 3 个镜头：2 个首帧待生成，新增 1 张定妆图')).toBeTruthy();
    expect(screen.getByRole('button', { name: '完成' })).toBeTruthy();
  });

  it('will not lay out more than the limit, or nothing', async () => {
    installServer([{ scene_id: 'E1S01', shots: 5, new: 5 }, { scene_id: 'E1S02', shots: 4, new: 4 }], 6);
    open();
    await screen.findByText('E1S01');
    const apply = screen.getByRole('button', { name: '铺到画布' }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('一次最多铺 6 个镜头');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    expect(apply.disabled).toBe(false);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(apply.disabled).toBe(true);
  });

  it('says why when the canvas cannot be saved first, and lays nothing out', async () => {
    const calls = installServer([{ scene_id: 'E1S01', shots: 2, new: 2 }]);
    const props = open({ prepare: vi.fn(async () => { throw new Error('画布还没保存成功，先解决保存问题。'); }) });
    await screen.findByText('E1S01');
    fireEvent.click(screen.getByRole('button', { name: '铺到画布' }));
    expect((await screen.findByRole('alert')).textContent).toContain('画布还没保存成功');
    expect(calls.some(call => call.method === 'POST')).toBe(false);
    expect(props.onApplied).not.toHaveBeenCalled();
  });

  it('closes on Escape', async () => {
    installServer([]);
    const props = open();
    await screen.findByText('项目还没有分镜。');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalled();
  });
});
