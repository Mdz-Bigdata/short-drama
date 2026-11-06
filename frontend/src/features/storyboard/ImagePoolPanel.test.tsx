// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '../../api/client';
import { ImagePoolPanel, type PoolImage } from './ImagePoolPanel';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);

const IMAGES: PoolImage[] = [
  { id: 'img_a', url: '/media/board.png', kind: 'board', label: 'E1S01 九宫格', scene_id: 'E1S01' },
  { id: 'img_b', url: '/media/shot.png', kind: 'shot', label: 'E1S01 镜头 1', scene_id: 'E1S01', shot_id: 1 },
];

function route(extra: (path: string) => unknown = () => undefined) {
  mocked.mockImplementation(async (path: unknown) => {
    const value = String(path);
    const answer = extra(value);
    if (answer !== undefined) return answer as never;
    if (value.endsWith('/image-pool')) return { revision: 2, images: IMAGES } as never;
    if (value.endsWith('/shots/visual')) return { shots: [{ shot_id: 1, scene_id: 'E1S01', shot_uid: 101, desc: '开场' }] } as never;
    return {} as never;
  });
}

describe('ImagePoolPanel', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(cleanup);

  it('lists the pool and filters by kind', async () => {
    route();
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    expect(await screen.findByRole('button', { name: /E1S01 九宫格/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('类型'), { target: { value: 'shot' } });
    expect(screen.queryByRole('button', { name: /E1S01 九宫格/ })).toBeNull();
    expect(screen.getByRole('button', { name: /E1S01 镜头 1/ })).toBeTruthy();
  });

  it('splits the selected image with the revision it read', async () => {
    route(path => path.endsWith('/split')
      ? { revision: 3, images: [...IMAGES, { id: 'cell_1', url: '/media/c.png', kind: 'cell', label: '切图 1-1' }], added: ['cell_1'] }
      : undefined);
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    const split = await screen.findByRole('button', { name: '切分选中的图' }) as HTMLButtonElement;
    expect(split.disabled).toBe(true);
    fireEvent.click(await screen.findByRole('button', { name: /E1S01 九宫格/ }));
    fireEvent.change(screen.getByLabelText('行'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '切分选中的图' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/image-pool/split', expect.objectContaining({
      body: JSON.stringify({ image_id: 'img_a', rows: 2, columns: 3, revision: 2 }),
    })));
    expect((await screen.findByRole('status')).textContent).toContain('1');
    expect(screen.getByRole('button', { name: /切图 1-1/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /E1S01 九宫格/ })).toBeNull();
  });

  it('will not cut into a single cell', async () => {
    route();
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /E1S01 九宫格/ }));
    fireEvent.change(screen.getByLabelText('行'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('列'), { target: { value: '1' } });
    expect((screen.getByRole('button', { name: '切分选中的图' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('assigns to the shot it was opened for and hands back the workspace', async () => {
    route(path => path.endsWith('/assign') ? { task_id: 't1' } : undefined);
    const onAssigned = vi.fn();
    render(<ImagePoolPanel taskId="t1" shot={{ shot_id: 4, scene_id: 'E1S02', shot_uid: 204 }} onAssigned={onAssigned} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /E1S01 镜头 1/ }));
    fireEvent.click(screen.getByRole('button', { name: '用于 E1S02 第 4 镜' }));
    await waitFor(() => expect(onAssigned).toHaveBeenCalledWith({ task_id: 't1' }));
    expect(mocked).toHaveBeenCalledWith('/api/drama/t1/image-pool/assign', expect.objectContaining({
      body: JSON.stringify({ image_id: 'img_b', shot_id: 4, scene_id: 'E1S02', shot_uid: 204 }),
    }));
    expect(mocked).not.toHaveBeenCalledWith('/api/drama/t1/shots/visual');
  });

  it('lets the person choose the shot when opened without one', async () => {
    route(path => path.endsWith('/assign') ? {} : undefined);
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /E1S01 镜头 1/ }));
    const use = screen.getByRole('button', { name: '用于这一镜' }) as HTMLButtonElement;
    expect(use.disabled).toBe(true);
    await screen.findByRole('option', { name: /开场/ });
    fireEvent.change(screen.getByLabelText('给哪一镜'), { target: { value: 'E1S01#1' } });
    fireEvent.click(screen.getByRole('button', { name: '用于这一镜' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/image-pool/assign', expect.objectContaining({
      body: JSON.stringify({ image_id: 'img_b', shot_id: 1, scene_id: 'E1S01', shot_uid: 101 }),
    })));
  });

  it('shows a refusal, such as a stale revision', async () => {
    route(path => {
      if (path.endsWith('/split')) throw new ApiError('图片池已被更新，请刷新后再试', 409);
      return undefined;
    });
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /E1S01 九宫格/ }));
    fireEvent.click(screen.getByRole('button', { name: '切分选中的图' }));
    expect((await screen.findByRole('alert')).textContent).toContain('已被更新');
  });

  it('rebuilds the index and says when the pool is empty', async () => {
    route(path => path.endsWith('/image-pool') ? { revision: 0, images: [] } : path.endsWith('/rebuild') ? { revision: 1, images: IMAGES } : undefined);
    render(<ImagePoolPanel taskId="t1" onClose={() => {}} />);
    expect(await screen.findByText('这里还没有图片；第 4 阶段出分镜图后会出现在这里。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重建索引' }));
    expect(await screen.findByRole('button', { name: /E1S01 九宫格/ })).toBeTruthy();
  });
});
