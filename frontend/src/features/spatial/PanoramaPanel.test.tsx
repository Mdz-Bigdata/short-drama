// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '../../api/client';
import { PanoramaPanel } from './PanoramaPanel';
import { dragLook, lookTarget } from './panoramaView';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));
vi.mock('./three/PanoramaViewer', () => ({
  default: ({ url }: { url: string }) => <div data-testid="viewer">{url}</div>,
}));

const mocked = vi.mocked(apiRequest);
const PANO = { id: 'p1', url: 'http://localhost/media/desk_p1.jpg', description: '客厅', source: 'text', width: 3024, height: 1512 };
const LIST = '/api/drama/t1/panoramas/scenes/E1S01';
const SPATIAL = '/api/drama/t1/spatial/scenes/E1S01';

function route(panoramas: unknown[], extra: (path: string, options?: RequestInit) => unknown = () => undefined) {
  mocked.mockImplementation(async (path: unknown, options?: RequestInit) => {
    const value = String(path);
    const answer = extra(value, options);
    if (answer !== undefined) return answer as never;
    if (value === LIST) return { panoramas } as never;
    if (value === SPATIAL && !options?.method) return { plan: { revision: 7 } } as never;
    return {} as never;
  });
}

describe('PanoramaPanel', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('shows the newest panorama in the viewer', async () => {
    route([PANO]);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    expect((await screen.findByTestId('viewer')).textContent).toBe(PANO.url);
  });

  it('says when a scene has none and offers no backdrop action', async () => {
    route([]);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    expect(await screen.findByText('这一场还没有全景。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '用作导演台背景' })).toBeNull();
  });

  it('asks before paying and posts the description', async () => {
    route([], (path, options) => (path === LIST && options?.method === 'POST' ? { panoramas: [PANO] } : undefined));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByText('这一场还没有全景。');
    fireEvent.change(screen.getByLabelText('这个地点什么样'), { target: { value: ' 雨夜客厅 ' } });
    fireEvent.click(screen.getByRole('button', { name: '生成全景' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(mocked.mock.calls.some(call => (call[1] as RequestInit | undefined)?.method === 'POST')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '生成全景' }));
    expect(await screen.findByTestId('viewer')).toBeTruthy();
    const post = mocked.mock.calls.find(call => (call[1] as RequestInit | undefined)?.method === 'POST');
    const body = (post?.[1] as RequestInit).body as FormData;
    expect(body.get('description')).toBe('雨夜客厅');
    expect(body.get('reference')).toBeNull();
  });

  it('sends a chosen reference picture', async () => {
    route([], (path, options) => (path === LIST && options?.method === 'POST' ? { panoramas: [PANO] } : undefined));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByText('这一场还没有全景。');
    const picture = new File(['x'], 'ref.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('选择参考图'), { target: { files: [picture] } });
    expect(screen.getByText('ref.png')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '生成全景' }));
    await screen.findByTestId('viewer');
    const post = mocked.mock.calls.find(call => (call[1] as RequestInit | undefined)?.method === 'POST');
    expect(((post?.[1] as RequestInit).body as FormData).get('reference')).toBeTruthy();
  });

  it('sets the backdrop through the real set_backdrop operation at the current revision', async () => {
    route([PANO]);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '用作导演台背景' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith(SPATIAL, expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({
        baseRevision: 7,
        operations: [{ op: 'set_backdrop', kind: 'panorama', url: PANO.url, yaw_deg: 0 }],
        solve: false,
      }),
    })));
    expect((await screen.findByRole('status')).textContent).toContain('全景背景');
  });

  it('reports a refused generation and a desk conflict', async () => {
    route([PANO], (path, options) => {
      if (path === LIST && options?.method === 'POST') throw new ApiError('图像模型未能生成全景，请稍后重试', 502);
      if (path === SPATIAL && options?.method === 'PATCH') throw new ApiError('站位已被更新', 409);
      return undefined;
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '用作导演台背景' }));
    expect((await screen.findByRole('alert')).textContent).toContain('站位已被更新');
    fireEvent.click(screen.getByRole('button', { name: '生成全景' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('未能生成全景'));
  });

  it('switches between a scene\'s panoramas and closes', async () => {
    route([PANO, { ...PANO, id: 'p2', url: 'http://localhost/media/desk_p2.jpg' }]);
    const onClose = vi.fn();
    render(<PanoramaPanel taskId="t1" sceneId="E1S01" onClose={onClose} />);
    expect((await screen.findByTestId('viewer')).textContent).toContain('desk_p2');
    fireEvent.click(screen.getByRole('button', { name: '全景 1' }));
    expect((await screen.findByTestId('viewer')).textContent).toContain('desk_p1');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

describe('looking around a panorama', () => {
  it('turns with the drag and stops short of the poles', () => {
    expect(dragLook({ yaw: 0, pitch: 0 }, 100, 0).yaw).toBeCloseTo(-20);
    expect(dragLook({ yaw: 0, pitch: 0 }, 0, 100000).pitch).toBe(85);
    expect(dragLook({ yaw: 0, pitch: 0 }, 0, -100000).pitch).toBe(-85);
  });

  it('starts looking straight ahead and looks up when pitched', () => {
    const [x, y, z] = lookTarget({ yaw: 0, pitch: 0 });
    expect([x, y, z].map(value => Math.round(value))).toEqual([0, 0, -1]);
    expect(lookTarget({ yaw: 0, pitch: 45 })[1]).toBeGreaterThan(0.5);
  });
});
