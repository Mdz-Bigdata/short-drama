// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BlockingDiagram, BlockingDiagramSeries } from '../lib/blockingDiagram';
import { BlockingDiagramDialog } from './BlockingDiagramDialog';

const URL_BASE = 'http://localhost:8000/api/drama/t1/spatial/scenes/E1S01/blocking-diagrams';

function diagram(index: number, extra: Partial<BlockingDiagram> = {}): BlockingDiagram {
  return {
    index, total: 2, shot_ids: [index], title: `站位图 ${index}/2 · 第 ${index} 镜`, view: 'oblique',
    figures: [
      { name: '陆沉', extra: false, role: 'principal', color: '#E0453A', position: [1.5, 1], yaw_deg: -90, posture: 'stand', posture_label: '站立', height_m: 1.8, start: null },
      { name: '苏晚', extra: false, role: 'principal', color: '#20B5A0', position: [-1, -1], yaw_deg: 51, posture: 'sit', posture_label: '坐着', height_m: 1.65, start: null },
      { name: '群演1', extra: true, role: 'crowd', color: '#B0B0B0', position: [3, -3], yaw_deg: 0, posture: 'lie', posture_label: '倒卧', height_m: 1.7, start: null },
    ],
    pieces: [{ name: '木箱', kind: 'prop', shape: 'box', position: [-1.6, -1.2], size: [0.8, 0.8, 0.6], yaw_deg: 0, elevation_m: 0 }],
    cameras: [{
      id: 'c1', label: 'CAM 1', position: [0.2, 5], true_position: [0.2, 5], height_m: 1.5, far_m: 0, target: [0.2, 0], lens_mm: 40, fov_deg: 48.5,
      subjects: ['陆沉', '苏晚'], focus: '', color: '', shot_ids: [index], candidate: false, move: 'static', move_label: '固定机位', end_position: null,
    }],
    routes: [], bounds: [-4, -5, 5, 7], notes: ['按已保存的调度方案（修订 7）绘制。'], prompt: `提示词 ${index}`,
    ...extra,
  };
}

const SERIES: BlockingDiagramSeries = {
  task_id: 't1', scene_id: 'E1S01', location: '旧仓库 夜', revision: 7, persisted: true, view: 'oblique',
  views: [{ id: 'oblique', label: '45° 俯视', tilt_deg: 45 }, { id: 'top', label: '顶视', tilt_deg: 90 }, { id: 'eye', label: '平视', tilt_deg: 18 }],
  grid: { cell_m: 1, major_every: 5 },
  colors: [{ name: '陆沉', hex: '#E0453A', color_name: '红' }, { name: '苏晚', hex: '#20B5A0', color_name: '青' }],
  extra_color: '#B0B0B0',
  diagrams: [
    diagram(1),
    diagram(2, {
      routes: [{ name: '陆沉', color: '#E0453A', points: [[3.5, 2], [1.5, 1]], meters: 2.2, order: 1 }],
      cameras: [{
        id: 'c3', label: 'CAM 3', position: [0, 4], true_position: [0, 4], height_m: 1.6, far_m: 0, target: [0, 0], lens_mm: 35, fov_deg: 54.4,
        subjects: ['陆沉'], focus: '陆沉', color: '#E0453A', shot_ids: [2], candidate: false, move: 'push', move_label: '推近', end_position: [0, 2],
      }],
    }),
  ],
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('BlockingDiagramDialog', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith(URL_BASE)) return json({ ...SERIES, view: url.includes('view=top') ? 'top' : 'oblique' });
      return json({ detail: 'not found' }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('draws the first beat with a tag for each named character and none for the crowd', async () => {
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    const picture = await screen.findByRole('img', { name: /站位图 1\/2 · 第 1 镜：陆沉、苏晚/ });
    const words = [...picture.querySelectorAll('text')].map(node => node.textContent);
    expect(words).toContain('陆沉');
    expect(words).toContain('苏晚');
    expect(words).toContain('CAM 1');
    expect(words).not.toContain('群演1');
    expect(words.some(word => word?.includes('每格 1 米'))).toBe(true);
    expect(screen.getByText('1 / 2')).toBeTruthy();
    expect(screen.getByRole('button', { name: '上一张' })).toHaveProperty('disabled', true);
  });

  it('pages to the walking beat, which shows the route number and the travelling lens', async () => {
    const user = userEvent.setup();
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    await screen.findByRole('img', { name: /站位图 1\/2/ });
    await user.click(screen.getByRole('button', { name: '下一张' }));
    const picture = screen.getByRole('img', { name: /站位图 2\/2/ });
    expect(picture.closest('[hidden]')).toBeNull();
    expect(picture.querySelector('path[stroke-dasharray]')).not.toBeNull();
    expect([...picture.querySelectorAll('text')].map(node => node.textContent)).toContain('CAM 3');
    expect((screen.getByLabelText('这张站位图的出图提示词') as HTMLTextAreaElement).value).toBe('提示词 2');
    expect(screen.getByRole('button', { name: '下一张' })).toHaveProperty('disabled', true);
  });

  it('asks the server again when the view changes and marks the chosen view', async () => {
    const user = userEvent.setup();
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    await screen.findByRole('img', { name: /站位图 1\/2/ });
    expect(screen.getByRole('radio', { name: '45° 俯视' }).getAttribute('aria-checked')).toBe('true');
    await user.click(screen.getByRole('radio', { name: '顶视' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('view=top'))).toBe(true));
    await waitFor(() => expect(screen.getByRole('radio', { name: '顶视' }).getAttribute('aria-checked')).toBe('true'));
  });

  it('copies the prompt of the diagram on show', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    await screen.findByRole('img', { name: /站位图 1\/2/ });
    await user.click(screen.getByText(/这张图的出图提示词/));
    await user.click(screen.getByRole('button', { name: /复制提示词/ }));
    expect(writeText).toHaveBeenCalledWith('提示词 1');
    expect(await screen.findByText(/已复制这张图的提示词/)).toBeTruthy();
  });

  it('shows the server’s own words when the scene has nothing to draw, and says when edits are still saving', async () => {
    fetchMock.mockImplementation(() => json({ detail: '这一场还没有镜头，画不出站位图；先在导演台里排出至少一镜。' }, 422));
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving onClose={() => {}} />);
    expect((await screen.findByRole('alert')).textContent).toContain('这一场还没有镜头');
    expect(screen.getByText(/还有改动正在保存/)).toBeTruthy();
  });

  it('draws a fight beat with its strike, contact star, effect ring, ruler and act labels, and lists them in the legend', async () => {
    const fight = diagram(1, {
      title: '站位图 1/2 · 第 1 镜 · 开场站位 · 动作预演 + 特效预演',
      figures: [
        { name: '陆沉', extra: false, role: 'principal', color: '#E0453A', position: [-1, 0], yaw_deg: 90, posture: 'fight', posture_label: '格斗架势', height_m: 1.8, start: null, acts: [] },
        { name: '苏晚', extra: false, role: 'principal', color: '#20B5A0', position: [1, 0], yaw_deg: -90, posture: 'stand', posture_label: '站立', height_m: 1.65, start: null, acts: ['受击'] },
      ],
      modes: ['staging', 'action', 'vfx'], mode_label: '动作预演 + 特效预演',
      strikes: [{
        attacker: '陆沉', target: '苏晚', kind: 'fist', short: '拳', label: '拳轨迹', color: '#E0453A', from: [-0.7, 0], to: [0.75, 0], meters: 2,
        shot_id: 1, at_s: 1, source: 'clip', source_label: '按导演台动作片段', force_to: [1.95, 0], reaction: '受击',
      }],
      effects: [{ id: 'VFX-01', kind: 'shock', name: '冲击波', center: [1, 0], radius_m: 3, rings: 3, from: [-1, 0], source: '陆沉', inside: ['苏晚'], color: '#C0392B' }],
      distances: [],
      nodes: [{ shot_id: 1, at_s: 1, end_s: 1.8, name: '陆沉', what: '直拳', source: 'clip' }],
      legend: [
        { mark: '陆沉', meaning: '角色，格斗架势', color: '红', where: '偏左 1 米' },
        { mark: '拳轨迹', meaning: '陆沉打向苏晚，两人相距约 2 米；苏晚受击（按导演台动作片段）', color: '红', where: '偏右 1 米' },
        { mark: 'VFX-01', meaning: '冲击波占位，半径约 3 米，由陆沉发出；苏晚在范围内', color: '红', where: '偏右 1 米' },
      ],
    });
    fetchMock.mockImplementation(() => json({ ...SERIES, diagrams: [fight, SERIES.diagrams[1]] }));
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    const picture = await screen.findByRole('img', { name: /动作预演 \+ 特效预演：陆沉、苏晚/ });
    const words = [...picture.querySelectorAll('text')].map(node => node.textContent);
    for (const word of ['拳 约 2 米', 'VFX-01 冲击波', '受击', '1 米']) expect(words).toContain(word);
    expect(words.some(word => word?.includes('星形是接触点') && word.includes('圆圈是特效占位'))).toBe(true);
    // Three rings for the effect, one dotted strike line.
    expect(picture.querySelectorAll('polygon[stroke="#C0392B"]')).toHaveLength(3);
    expect(picture.querySelector('line[stroke-dasharray="2 12"]')).not.toBeNull();

    await user.click(screen.getByText(/标注表（图上的 3 个标记各是什么）/));
    expect(screen.getByRole('rowheader', { name: '拳轨迹' })).toBeTruthy();
    expect(screen.getByText(/第 1 镜 1–1.8 秒 · 陆沉：直拳/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /复制标注表/ }));
    expect(String(writeText.mock.calls[0][0])).toContain('VFX-01\t冲击波占位');
    expect(await screen.findByText(/已复制这张图的标注表/)).toBeTruthy();
  });

  it('keeps a plain beat plain: a scale bar, no legend when the server sends none', async () => {
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    const picture = await screen.findByRole('img', { name: /站位图 1\/2/ });
    expect([...picture.querySelectorAll('text')].map(node => node.textContent)).toContain('1 米');
    expect(picture.querySelector('line[stroke-dasharray="2 12"]')).toBeNull();
    expect(screen.queryByText(/标注表/)).toBeNull();
  });

  it('puts a ruler with its metres between the leads of a plain beat', async () => {
    fetchMock.mockImplementation(() => json({ ...SERIES, diagrams: [diagram(1, { distances: [{ a: '苏晚', b: '陆沉', meters: 3.2, from: [-1, -1], to: [1.5, 1] }] })] }));
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={() => {}} />);
    const picture = await screen.findByRole('img', { name: /站位图 1\/2/ });
    expect([...picture.querySelectorAll('text')].map(node => node.textContent)).toContain('约 3 米');
  });

  it('closes on Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<BlockingDiagramDialog taskId="t1" sceneId="E1S01" saving={false} onClose={onClose} />);
    await screen.findByRole('img', { name: /站位图 1\/2/ });
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
