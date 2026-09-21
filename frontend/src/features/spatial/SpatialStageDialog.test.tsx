// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SpatialStageDialog } from './SpatialStageDialog';
import { planResponse } from './spatialFixtures';

vi.mock('./three/SpatialStageViewport', () => ({
  default: ({ mode }: { mode: string }) => <div data-testid="viewport">3D:{mode}</div>,
}));

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('SpatialStageDialog', () => {
  const fetchMock = vi.fn();
  const requests = () => fetchMock.mock.calls.map(call => ({
    url: String(call[0]),
    method: (call[1] as RequestInit | undefined)?.method || 'GET',
    body: (call[1] as RequestInit | undefined)?.body ? JSON.parse(String((call[1] as RequestInit).body)) : undefined,
  }));

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method || 'GET';
      if (method === 'PATCH') return jsonResponse(planResponse({ boardStale: true }, { revision: 4, source: 'edited' }));
      return jsonResponse(planResponse());
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows the shots, the measured sentences of the selected one, and the checks', async () => {
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'E1S01 · 空间调度' })).toBeTruthy();
    const shots = screen.getByRole('complementary', { name: '本场镜头机位' });
    expect(within(shots).getAllByRole('button')).toHaveLength(2);
    expect(within(shots).getByText('建立 · 全景')).toBeTruthy();
    expect(within(shots).getByLabelText('有提示')).toBeTruthy();          // shot 2 is named by a failed warning
    expect(screen.getByText(/林夏位于画面左侧三分之一的中景/)).toBeTruthy();
    expect(screen.getByText(/第2镜的林夏被助手挡住/)).toBeTruthy();
    expect(screen.getByRole('img', { name: 'E1S01 空间调度俯视图' })).toBeTruthy();

    await userEvent.click(within(shots).getByRole('button', { name: /单人 · 近景/ }));
    expect(screen.getByText(/近景，65mm/)).toBeTruthy();
  });

  it('loads three.js only when a 3D view is opened', async () => {
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });
    expect(screen.queryByTestId('viewport')).toBeNull();

    await userEvent.click(screen.getByRole('tab', { name: /机位视角/ }));
    expect((await screen.findByTestId('viewport')).textContent).toBe('3D:camera');
  });

  it('sends semantic operations pinned to the revision it read', async () => {
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });

    await userEvent.type(screen.getByLabelText('相距（米）'), '1.2');
    await userEvent.click(screen.getByRole('button', { name: '面对面站定' }));

    await waitFor(() => expect(requests().some(item => item.method === 'PATCH')).toBe(true));
    const patch = requests().find(item => item.method === 'PATCH');
    expect(patch?.url).toContain('/api/drama/t1/spatial/scenes/E1S01');
    expect(patch?.body).toEqual({
      baseRevision: 3,
      operations: [{ op: 'face_pair', first: '林夏', second: '周教授', distance: 1.2 }, { op: 'solve_camera' }],
    });
    expect(await screen.findByText(/本场已完成的九宫格仍按旧站位绘制/)).toBeTruthy();
    expect(screen.getByText(/已手动调整 · 第 4 版/)).toBeTruthy();
  });

  it('keeps a moved principal facing their partner and leaves cameras alone when asked to', async () => {
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    const floor = await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });
    await userEvent.click(screen.getByLabelText('移动人物后自动重解机位'));

    const mark = floor.querySelector('.spatial-floor__actor.is-principal') as SVGGElement;
    vi.spyOn(floor, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 720, height: 540, right: 720, bottom: 540, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(mark, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(floor, { clientX: 140, clientY: 260, pointerId: 1 });
    fireEvent.pointerUp(floor, { clientX: 140, clientY: 260, pointerId: 1 });

    await waitFor(() => expect(requests().some(item => item.method === 'PATCH')).toBe(true));
    const operations = requests().find(item => item.method === 'PATCH')?.body.operations;
    expect(operations.map((item: { op: string }) => item.op)).toEqual(['move_actor', 'orient_toward', 'orient_toward']);
    expect(operations[0].name).toBe('林夏');
    expect(operations[0].position).toHaveLength(2);
  });

  it('explains a conflict and lets the user read the plan again', async () => {
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => (
      init?.method === 'PATCH' ? jsonResponse({ detail: '空间方案已在其他页面更新，请刷新后重试' }, 409) : jsonResponse(planResponse())
    ));
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });

    await userEvent.click(screen.getByRole('button', { name: /重解全部机位/ }));

    expect(await screen.findByText(/空间方案已在其他页面更新.*重新读取/)).toBeTruthy();
    const before = requests().filter(item => item.method === 'GET').length;
    await userEvent.click(screen.getByRole('button', { name: /重新读取/ }));
    await waitFor(() => expect(requests().filter(item => item.method === 'GET').length).toBe(before + 1));
  });

  it('asks before sending a finished scene back to stage four', async () => {
    const onRedraw = vi.fn();
    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} onRedrawRequested={onRedraw} />);
    await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });

    await userEvent.click(screen.getByRole('button', { name: /按当前站位重画本场/ }));
    expect(confirm).toHaveBeenCalled();
    expect(requests().some(item => item.url.endsWith('/redraw'))).toBe(false);

    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: /按当前站位重画本场/ }));
    await waitFor(() => expect(requests().some(item => item.url.endsWith('/redraw') && item.method === 'POST')).toBe(true));
    await waitFor(() => expect(onRedraw).toHaveBeenCalled());
  });

  it('says so when the plan is only a preview, and hides redraw until a board exists', async () => {
    fetchMock.mockImplementation(() => jsonResponse(planResponse({ persisted: false, boardStatus: 'pending' }, { coverage: 'template' })));
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);

    expect(await screen.findByText(/当前为按剧本即时规划的预览/)).toBeTruthy();
    expect(screen.getByText('标准覆盖预览')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /按当前站位重画本场/ })).toBeNull();
  });

  it('reports a load failure and closes on Escape', async () => {
    const onClose = vi.fn();
    fetchMock.mockImplementation(() => jsonResponse({ detail: '场景 E1S01 不在剧本大纲里' }, 404));
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={onClose} />);

    expect((await screen.findByRole('alert')).textContent).toContain('不在剧本大纲里');
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});
