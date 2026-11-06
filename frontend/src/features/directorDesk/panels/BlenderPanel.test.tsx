// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BlenderStatus, PrevizRender, PrevizView } from '../blenderApi';
import { BlenderPanel } from './BlenderPanel';

const BASE = 'http://localhost:8000/api/drama/t1/spatial/scenes/E1S01/blender';
const STATUS: BlenderStatus = {
  blender_found: true, blender_path: '/Applications/Blender.app', blender_version: '5.2.2 LTS',
  live_connected: true, live_port: 9877, addon_download: '/api/blender/addon.zip',
};
const RENDER: PrevizRender = {
  plan_revision: 3, video_url: '/media/previz/t1/E1S01/r3/previz.mp4', blend_url: '/media/previz/t1/E1S01/r3/previz.blend',
  stills: [{ shot_id: 1, url: '/media/a.png' }, { shot_id: 2, url: '/media/b.png' }],
  segments: [
    { shot_id: 1, camera: 'cam-01', start: 1, end: 48, seconds: 2 },
    { shot_id: 2, camera: 'cam-02', start: 49, end: 96, seconds: 2 },
  ],
  fps: 24, frames: 96, resolution: [540, 960], blender_version: '5.2.2 LTS', rendered_at: '2026-10-20T00:00:00Z',
  proxies: [{ id: 'actor-01', name: '陆昭', kind: 'actor', color: '#c8a24a' }, { id: 'actor-02', name: '群演', kind: 'extra', color: '#9a9a9a' }],
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('BlenderPanel', () => {
  const fetchMock = vi.fn();
  const onPlanChanged = vi.fn();
  const onSelectShot = vi.fn();
  let view: PrevizView;
  const calls = (suffix: string, method = 'POST') => fetchMock.mock.calls.filter(
    call => String(call[0]) === `${BASE}${suffix}` && (call[1]?.method ?? 'GET') === method,
  );

  beforeEach(() => {
    view = { scene_id: 'E1S01', options: {}, latest: null, stale: false, plan_revision: 3 };
    onPlanChanged.mockReset();
    onSelectShot.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url.endsWith('/api/blender/status')) return json(STATUS);
      if (url === BASE && method === 'GET') return json(view);
      if (url === `${BASE}/render`) {
        view = { ...view, latest: RENDER };
        return json({ ...RENDER, live: true, reused: false });
      }
      if (url === `${BASE}/options`) {
        const body = JSON.parse(String(init?.body));
        view = { ...view, options: { ...view.options, ...body } };
        return json(view);
      }
      if (url === `${BASE}/pull`) {
        const body = JSON.parse(String(init?.body));
        return json({ operations: [{ op: 'move_actor', name: '陆昭', position: [1.2, 0], yaw_deg: 120 }], applied: body.apply, revision: body.apply ? 4 : undefined });
      }
      if (url === `${BASE}/attach`) return json({ attached: [{ shot_id: 1, capture_id: 'c1', url: '/m/1.mp4' }, { shot_id: 2, capture_id: 'c2', url: '/m/2.mp4' }], failed: [] });
      if (url.endsWith('/api/drama/t1/assistant')) {
        return json({ reply: '已把陆昭往左挪两步并重新渲染。', tool_calls: [{ tool: 'describe_stage', result: { ok: true } }, { tool: 'edit_stage', result: { ok: true } }, { tool: 'render_blender_previz', result: { ok: true } }] });
      }
      throw new Error(`unexpected ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const panel = () => render(
    <BlenderPanel taskId="t1" sceneId="E1S01" shotIds={[1, 2]} planRevision={3} editable onPlanChanged={onPlanChanged} onSelectShot={onSelectShot} />,
  );

  it('renders the scene, then lists every shot with its frames and the colour legend of the principals', async () => {
    const user = userEvent.setup();
    panel();
    expect(await screen.findByText(/本机 Blender 5\.2\.2 LTS · 打开的 Blender 已连接/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /用 Blender 渲染预演/ }));
    expect(JSON.parse(String(calls('/render')[0][1]?.body))).toEqual({ long_edge: 960 });
    expect(await screen.findByText(/已渲染 2 镜、4\.0 秒；打开的 Blender 已同步/)).toBeTruthy();
    expect(screen.getByText('第 2 镜 · 2s · 帧 49–96')).toBeTruthy();
    expect(screen.getByText('陆昭')).toBeTruthy();
    expect(screen.queryByText('群演')).toBeNull();
    await user.click(screen.getByRole('button', { name: '选中第 2 镜' }));
    expect(onSelectShot).toHaveBeenCalledWith(2);
  });

  it('turns handheld on for one shot', async () => {
    view = { ...view, latest: RENDER };
    const user = userEvent.setup();
    panel();
    const hand = await screen.findByRole('button', { name: '第 2 镜真实手持' });
    await user.click(hand);
    expect(JSON.parse(String(calls('/options', 'PUT')[0][1]?.body))).toEqual({ handheld_shots: [2] });
    await waitFor(() => expect(screen.getByRole('button', { name: '第 2 镜真实手持' }).getAttribute('aria-pressed')).toBe('true'));
  });

  it('shows what was dragged in Blender and writes it back only after confirmation', async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole('button', { name: /读取 Blender 里的改动/ }));
    const changes = await screen.findByRole('group', { name: 'Blender 里的改动' });
    expect(within(changes).getByText(/「陆昭」移到 \[1\.2,0\]，朝向 120°/)).toBeTruthy();
    expect(onPlanChanged).not.toHaveBeenCalled();
    await user.click(within(changes).getByRole('button', { name: '写回方案' }));
    await waitFor(() => expect(onPlanChanged).toHaveBeenCalled());
    expect(JSON.parse(String(calls('/pull').at(-1)?.[1]?.body))).toEqual({ apply: true });
    expect(await screen.findByText(/已按 Blender 里的位置更新方案（版本 4）/)).toBeTruthy();
  });

  it('talks to the project agent about this scene and re-reads the plan after it edited the stage', async () => {
    const user = userEvent.setup();
    panel();
    await user.type(await screen.findByRole('textbox', { name: '对预演说的话' }), '第 2 镜让陆昭往左走两步，然后渲染给我看');
    await user.click(screen.getByRole('button', { name: '发送' }));
    expect(await screen.findByText('已把陆昭往左挪两步并重新渲染。')).toBeTruthy();
    expect(screen.getByText('调用：describe_stage → edit_stage → render_blender_previz')).toBeTruthy();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(call => String(call[0]).endsWith('/assistant'))?.[1]?.body));
    expect(sent.message).toMatch(/^\/agent 【当前场景 E1S01，Blender 预演台】第 2 镜让陆昭往左走两步/);
    expect(onPlanChanged).toHaveBeenCalled();
  });

  it('refuses to hand a stale previz to the storyboard', async () => {
    view = { ...view, latest: RENDER, stale: true };
    panel();
    expect(await screen.findByText(/站位或机位在这次渲染之后改过了/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /交给分镜当运动参考/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('hands a fresh previz to the storyboard as motion references', async () => {
    view = { ...view, latest: RENDER };
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole('button', { name: /交给分镜当运动参考/ }));
    expect(await screen.findByText(/已把 2 镜的预演登记为运动参考视频/)).toBeTruthy();
  });

  it('explains how to install Blender when it is missing', async () => {
    fetchMock.mockImplementation((input: RequestInfo) => {
      const url = String(input);
      if (url.endsWith('/api/blender/status')) return json({ ...STATUS, blender_found: false, live_connected: false });
      return json(view);
    });
    panel();
    expect(await screen.findByText(/本机没有找到 Blender/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /用 Blender 渲染预演/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('下载桥接插件')).toBeTruthy();
  });
});
