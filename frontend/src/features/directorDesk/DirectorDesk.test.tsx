// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { planResponse } from '../spatial/spatialFixtures';
import type { StagePlan } from '../spatial/spatialTypes';
import { applyAll } from './deskOperations';
import { DirectorDesk } from './DirectorDesk';
import type { DeskViewportProps } from './three/DeskViewport';
import type { LensViewportProps } from './three/LensViewport';

// The viewports are the three.js boundary. The stand-ins expose what the desk hands them and let
// a test play the part of the gizmo: preview while "dragging", one commit on release.
vi.mock('./three/DeskViewport', () => ({
  default: function MockDeskViewport({ plan, tool, readOnly, onPreview, onCommit, onSelect, onReady }: DeskViewportProps) {
    useEffect(() => {
      onReady?.({ viewPose: () => ({ position: [4, 3, 6], target: [0.6, 1, -0.4] }) });
      return () => onReady?.(null);
    }, [onReady]);
    const drag = [{ op: 'move_actor', name: '林夏', position: [0.5, 1] }];
    return (
      <div data-testid="desk-viewport" data-tool={tool} data-readonly={String(readOnly)}>
        {plan.actors.map(actor => <span key={actor.id} data-testid={`actor-${actor.name}`}>{actor.position.join(',')}</span>)}
        <button type="button" onClick={() => onSelect({ kind: 'actor', name: '林夏' }, false)}>pick 林夏</button>
        <button type="button" onClick={() => onPreview(drag)}>drag</button>
        <button type="button" onClick={() => onCommit(drag)}>release</button>
      </div>
    );
  },
}));

vi.mock('./three/LensViewport', () => ({
  default: function MockLensViewport({ plan, camera, overlay }: LensViewportProps) {
    return (
      <div data-testid="lens-viewport">
        <span data-testid="lens-camera">{camera?.id}:{camera?.lens_mm}</span>
        <span data-testid="lens-sees">{plan.actors[0].position.join(',')}</span>
        {overlay}
      </div>
    );
  },
}));

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('DirectorDesk', () => {
  const fetchMock = vi.fn();
  // A small honest server: it applies what it is sent, the same way the desk previews it.
  let stage: StagePlan;
  const patches = () => fetchMock.mock.calls
    .filter(call => (call[1] as RequestInit | undefined)?.method === 'PATCH')
    .map(call => JSON.parse(String((call[1] as RequestInit).body)) as { baseRevision: number; solve?: boolean; operations: Array<Record<string, unknown>> });
  const open = async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
  };

  beforeEach(() => {
    stage = planResponse().plan;
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/director-desk/')) return json({ captures: [], applied: {} });
      if (init?.method === 'PATCH') {
        const { operations } = JSON.parse(String(init.body)) as { operations: Array<{ op: string }> };
        stage = { ...applyAll(stage, operations), revision: stage.revision + 1 };
      }
      return json(planResponse({}, stage));
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('opens on the scene with both views live and the outliner filled in', async () => {
    await open();
    expect(screen.getByRole('heading', { name: 'E1S01 · 办公室' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: /并排/ }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('lens-camera').textContent).toBe('cam-01:28');
    const outline = screen.getByRole('complementary', { name: '场景大纲' });
    expect(within(within(outline).getByRole('region', { name: '角色' })).getAllByRole('listitem')).toHaveLength(3);
    expect(within(outline).getByText('还没有群演阵列')).toBeTruthy();
    expect(within(outline).getByText('录音笔')).toBeTruthy();
    expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '播放' })).toBeTruthy();

    await userEvent.click(screen.getByRole('radio', { name: /^机位$/ }));
    expect(screen.queryByTestId('desk-viewport')).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: /导演/ }));
    expect(screen.queryByTestId('lens-viewport')).toBeNull();
  });

  it('shows a drag in the lens view while it happens and sends one operation on release, without re-solving', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'drag' }));
    expect(screen.getByTestId('lens-sees').textContent).toBe('0.5,1');
    expect(patches()).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: 'release' }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toEqual({ baseRevision: 3, solve: false, operations: [{ op: 'move_actor', name: '林夏', position: [0.5, 1] }] });
    expect(await screen.findByText(/已保存 · 第 4 版/)).toBeTruthy();
  });

  it('undoes and redoes through the same PATCH, with the keyboard too', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'release' }));
    await screen.findByText(/第 4 版/);

    await userEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1]).toEqual({ baseRevision: 4, solve: false, operations: [{ op: 'move_actor', name: '林夏', position: [-1.3, 0] }] });

    await screen.findByText(/第 5 版/);
    fireEvent.keyDown(window, { key: 'z', ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2].operations).toEqual([{ op: 'move_actor', name: '林夏', position: [0.5, 1] }]);
  });

  it('poses from the pose tool: the panel comes with it, figure and pose are one PATCH each, and undo restores them', async () => {
    await open();
    fireEvent.keyDown(window, { key: 'p' });
    expect(screen.getByTestId('desk-viewport').getAttribute('data-tool')).toBe('pose');
    expect(screen.getByRole('tab', { name: '姿势' }).getAttribute('aria-selected')).toBe('true');
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));

    await userEvent.click(screen.getByRole('radio', { name: '关节人偶' }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toEqual({ baseRevision: 3, solve: false, operations: [{ op: 'set_figure', name: '林夏', figure: 'mannequin' }] });

    await userEvent.click(await screen.findByRole('button', { name: '坐姿' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations[0]).toMatchObject({ op: 'set_pose', name: '林夏', preset: 'sit' });
    expect(patches()[1].operations[0]).not.toHaveProperty('shot_id');
    await waitFor(() => expect(screen.getByRole('button', { name: '坐姿' }).getAttribute('aria-pressed')).toBe('true'));

    await screen.findByText(/第 5 版/);
    await userEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2].operations).toEqual([{ op: 'set_pose', name: '林夏', preset: '', joints: {}, clip: '', clip_phase: 0 }]);
  });

  it('adds a prop where the director is looking, then edits and deletes it from the inspector', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: /圆柱/ }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{
      op: 'add_landmark', name: '圆柱 1', kind: 'prop', shape: 'cylinder', position: [0.5, -0.5], size: [0.6, 0.6, 1], yaw_deg: 0, color: '',
    }]);

    // The new piece is selected and already on stage, before the server has said a word.
    const inspector = screen.getByRole('region', { name: '属性' });
    expect(within(inspector).getByRole('heading', { name: /圆柱 1/ })).toBeTruthy();
    await userEvent.selectOptions(within(inspector).getByLabelText('形状'), 'wedge');
    const height = within(inspector).getByLabelText('高（米）');
    await userEvent.clear(height);
    await userEvent.type(height, '2.5{Enter}');
    await userEvent.click(within(inspector).getByRole('button', { name: /删除道具/ }));

    await waitFor(() => expect(patches().flatMap(patch => patch.operations).map(item => item.op)).toEqual(['add_landmark', 'transform_landmark', 'transform_landmark', 'remove_landmark']));
    const sent = patches().flatMap(patch => patch.operations);
    expect(sent[1]).toEqual({ op: 'transform_landmark', name: '圆柱 1', shape: 'wedge' });
    expect(sent[2]).toEqual({ op: 'transform_landmark', name: '圆柱 1', size: [0.6, 0.6, 2.5] });
    expect(sent[3]).toEqual({ op: 'remove_landmark', name: '圆柱 1' });
    // Nothing was waiting on a round trip: each request carried the revision the last one returned.
    expect(patches().map(patch => patch.baseRevision)).toEqual([...patches().keys()].map(index => 3 + index));
  });

  it('builds a crowd from the dialog', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: '添加群演阵列' }));
    const dialog = screen.getByRole('dialog', { name: '添加群演阵列' });
    const set = async (label: string, value: string) => {
      const input = within(dialog).getByLabelText(label);
      await userEvent.clear(input);
      await userEvent.type(input, value);
    };
    await set('行数', '2');
    await set('列数', '5');
    await set('间距（米）', '1.5');
    await set('随机种子', '42');
    await userEvent.selectOptions(within(dialog).getByLabelText('体型'), 'heavy');
    expect(within(dialog).getByText(/共 10 人/)).toBeTruthy();
    await userEvent.click(within(dialog).getByRole('button', { name: '添加' }));

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{
      op: 'add_crowd', label: '群演 1', rows: 2, columns: 5, spacing: 1.5, body_type: 'heavy', seed: 42, center: [0.5, -0.5], yaw_deg: 0,
    }]);
  });

  it('transforms and removes a crowd as one piece', async () => {
    const base = planResponse().plan;
    stage = {
      ...base,
      crowds: [{ id: 'crowd-01', label: '围观', rows: 1, columns: 2, spacing: 1, center: [4, 4], yaw_deg: 0, body_type: 'standard', seed: 7 }],
      actors: [
        ...base.actors,
        { ...base.actors[2], id: 'crowd-01-001', name: '围观-01', position: [3.5, 4], role: 'crowd', crowd_id: 'crowd-01' },
        { ...base.actors[2], id: 'crowd-01-002', name: '围观-02', position: [4.5, 4], role: 'crowd', crowd_id: 'crowd-01' },
      ],
    };
    await open();
    await userEvent.click(within(screen.getByRole('region', { name: '群演' })).getByRole('button', { name: /^围观/ }));
    const inspector = screen.getByRole('region', { name: '属性' });
    expect(within(inspector).getByText('2 人')).toBeTruthy();
    const yaw = within(inspector).getByLabelText('朝向（°）');
    await userEvent.clear(yaw);
    await userEvent.type(yaw, '90{Enter}');
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'transform_crowd', crowd_id: 'crowd-01', yaw_deg: 90 }]);
    // Both members turned about the centre at once.
    expect(screen.getByTestId('actor-围观-01').textContent).toBe('4,4.5');

    await userEvent.click(within(inspector).getByRole('button', { name: /删除群演/ }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations).toEqual([{ op: 'remove_crowd', crowd_id: 'crowd-01' }]);
  });

  it('adds cameras from the orbit view and from an angle preset, promotes and removes candidates', async () => {
    await open();
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    const panel = within(screen.getByRole('complementary', { name: '属性与机位' })).getByRole('region', { name: '机位' });

    await userEvent.click(within(panel).getByRole('button', { name: /从当前视角添加机位/ }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'add_camera', shot_id: 1, position: [4, 3, 6], target: [0.6, 1, -0.4], lens_mm: 35 }]);

    await userEvent.click(within(panel).getByRole('button', { name: '过肩' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    const preset = patches()[1].operations[0];
    expect(preset).toMatchObject({ op: 'add_camera', shot_id: 1, label: '第1镜 · 过肩', lens_mm: 50, target: [-1.3, 1.5, 0] });
    expect((preset.position as number[])[0]).toBeGreaterThan(1.3);

    cleanup();
    const base = planResponse().plan;
    stage = {
      ...base,
      cameras: [...base.cameras, { ...base.cameras[0], id: 'alt-01-01', label: '01 建立 · 候选1', lens_mm: 50 }],
      shots: [{ ...base.shots[0], alt_camera_ids: ['alt-01-01'] }, base.shots[1]],
    };
    await open();
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    await userEvent.click(screen.getByRole('button', { name: '查看 01 建立 · 候选1' }));
    expect(screen.getByTestId('lens-camera').textContent).toBe('alt-01-01:50');
    // frame_shot re-frames the lens that films, so it waits until the candidate is promoted.
    expect(screen.getByRole('button', { name: '近景' })).toHaveProperty('disabled', true);

    const before = patches().length;
    await userEvent.click(screen.getByRole('button', { name: '将 01 建立 · 候选1 设为主机位' }));
    await waitFor(() => expect(patches()).toHaveLength(before + 1));
    expect(patches()[before].operations).toEqual([{ op: 'use_camera', shot_id: 1, camera_id: 'alt-01-01' }]);
    // The lens that was filming took the candidate's slot, so it is the one that can go now.
    await userEvent.click(await screen.findByRole('button', { name: '删除 01 建立' }));
    await waitFor(() => expect(patches()).toHaveLength(before + 2));
    expect(patches()[before + 1].operations).toEqual([{ op: 'remove_camera', camera_id: 'cam-01' }]);
  });

  it('changes the lens by preset and by slider, and frames by shot size', async () => {
    await open();
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    await userEvent.click(within(screen.getByRole('group', { name: '焦距预设' })).getByRole('button', { name: '85' }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'move_camera', camera_id: 'cam-01', lens_mm: 85 }]);

    const slider = screen.getByLabelText('焦距（毫米）');
    fireEvent.change(slider, { target: { value: '120' } });
    expect(screen.getByTestId('lens-camera').textContent).toBe('cam-01:120');   // live, before anything is sent
    expect(patches()).toHaveLength(1);
    fireEvent.pointerUp(slider);
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations).toEqual([{ op: 'move_camera', camera_id: 'cam-01', lens_mm: 120 }]);

    await userEvent.click(within(screen.getByRole('group', { name: '景别' })).getByRole('button', { name: '近景' }));
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2].operations).toEqual([{ op: 'frame_shot', shot_id: 1, size: '近景' }]);
  });

  it('switches composition guides and lists the selected shot’s checks', async () => {
    await open();
    const guides = screen.getByRole('img', { name: '构图辅助线' });
    expect(guides.querySelectorAll('[data-guide="thirds"]')).toHaveLength(4);
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    await userEvent.click(screen.getByLabelText('三分线'));
    await userEvent.click(screen.getByLabelText('中心十字'));
    await userEvent.selectOptions(screen.getByLabelText('画幅'), '2.39:1');
    expect(guides.querySelectorAll('[data-guide="thirds"]')).toHaveLength(0);
    expect(guides.querySelectorAll('[data-guide="cross"]')).toHaveLength(2);
    expect(guides.querySelectorAll('[data-guide="mask"]')).toHaveLength(2);

    await userEvent.selectOptions(screen.getByLabelText('画幅'), 'custom');
    const custom = screen.getByLabelText('自定义画幅');
    await userEvent.clear(custom);
    await userEvent.type(custom, '9:16');
    expect(guides.querySelectorAll('[data-guide="mask"]')).toHaveLength(0);

    await userEvent.selectOptions(screen.getByLabelText('镜头'), '2');
    expect(within(screen.getByRole('list', { name: '本镜校验' })).getByText(/第2镜的林夏被助手挡住/)).toBeTruthy();
    expect(screen.getByTestId('lens-camera').textContent).toBe('cam-02:65');
  });

  it('re-reads on a revision conflict and says the edit was not saved', async () => {
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => (
      init?.method === 'PATCH' ? json({ detail: '空间方案已在其他页面更新，请刷新后重试' }, 409) : json(planResponse({}, { revision: 8 }))
    ));
    await open();
    const reads = () => fetchMock.mock.calls.filter(call => !(call[1] as RequestInit | undefined)?.method).length;
    const before = reads();
    await userEvent.click(screen.getByRole('button', { name: 'release' }));
    expect(await screen.findByText(/空间方案已在其他页面更新.*没有保存/)).toBeTruthy();
    await waitFor(() => expect(reads()).toBe(before + 1));
    expect(screen.getByTestId('actor-林夏').textContent).toBe('-1.3,0');
  });

  it('turns read-only with a banner while generation holds the stage', async () => {
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => (
      init?.method === 'PATCH' ? json({ detail: '任务正在执行阶段，暂不能修改空间调度' }, 409) : json(planResponse())
    ));
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'release' }));
    expect((await screen.findByRole('alert')).textContent).toContain('只读：任务正在执行阶段，暂不能修改空间调度');
    expect(screen.getByTestId('desk-viewport').getAttribute('data-readonly')).toBe('true');
    expect(within(screen.getByRole('group', { name: '添加道具' })).getByRole('button', { name: /立方体/ })).toHaveProperty('disabled', true);

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('puts a 422 in the inspector, in the server’s words', async () => {
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => (
      init?.method === 'PATCH' ? json({ detail: 'operations[0] move_actor：position 超出场地范围（±500 米）' }, 422) : json(planResponse())
    ));
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
    const x = within(screen.getByRole('region', { name: '属性' })).getByLabelText('X（米）');
    await userEvent.clear(x);
    await userEvent.type(x, '499{Enter}');
    expect((await within(screen.getByRole('region', { name: '属性' })).findByRole('alert')).textContent).toContain('position 超出场地范围');
    expect(screen.getByTestId('actor-林夏').textContent).toBe('-1.3,0');
  });

  it('reports a load failure, drives tools, views and the playhead from the keyboard, and backs out with Escape', async () => {
    const onClose = vi.fn();
    fetchMock.mockImplementationOnce(() => json({ detail: '场景 E1S01 不在剧本大纲里' }, 404));
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={onClose} />);
    expect((await screen.findByRole('alert')).textContent).toContain('不在剧本大纲里');
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: /重新读取/ }));
    const viewport = await screen.findByTestId('desk-viewport');

    fireEvent.keyDown(window, { key: 'w' });
    expect(viewport.getAttribute('data-tool')).toBe('move');
    fireEvent.keyDown(window, { key: 'v' });
    expect(viewport.getAttribute('data-tool')).toBe('select');
    fireEvent.keyDown(window, { key: '3' });
    expect(screen.queryByTestId('desk-viewport')).toBeNull();
    expect(screen.getByRole('radio', { name: /^机位$/ }).getAttribute('aria-checked')).toBe('true');
    fireEvent.keyDown(window, { key: '2' });
    await screen.findByTestId('desk-viewport');
    fireEvent.keyDown(window, { key: ' ' });
    expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '暂停' })).toBeTruthy();
    fireEvent.keyDown(window, { key: ' ' });
    expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '播放' })).toBeTruthy();

    // The shortcut card is the first thing Escape closes, then the measurement, then the selection.
    fireEvent.keyDown(window, { key: '?' });
    expect(screen.getByRole('dialog', { name: '快捷键' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '快捷键' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('contentinfo').textContent).toContain('未选择');
    // With nothing left to back out of, Escape dismisses the dialog itself.
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('sets the scene backdrop from an upload and keeps it out of what is delivered', async () => {
    const picture = {
      id: 'bg-1', kind: 'backdrop', shot_id: 0, camera_id: '', url: 'http://img.test/wall.jpg', width: 0, height: 0,
      duration_s: 0, fps: 0, plan_revision: 0, shows_limbs: false, monochrome: false, labelled: false, created_at: '2026-09-20T02:00:00Z', stale: false, warning: '',
    };
    let stored: unknown[] = [];
    const inner = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/director-desk/') && init?.method === 'POST') {
        stored = [picture];
        return json(picture);
      }
      if (String(input).includes('/director-desk/')) return json({ captures: stored, applied: {} });
      return inner(input, init) as Promise<Response>;
    });

    await open();
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    const panel = screen.getByRole('region', { name: '场景背景' });
    // With no picture in the scene yet, only a flat colour can be chosen.
    expect(within(panel).getByRole('radio', { name: '参考图' })).toHaveProperty('disabled', true);
    await userEvent.click(within(panel).getByRole('radio', { name: '纯色' }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'set_backdrop', kind: 'color' }]);

    await userEvent.upload(within(panel).getByLabelText('上传背景图文件'), new File([new Uint8Array([1, 2, 3])], 'wall.png', { type: 'image/png' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations).toEqual([{ op: 'set_backdrop', kind: 'image', url: 'http://img.test/wall.jpg' }]);
    expect(within(panel).getByRole('slider', { name: '背景不透明度' })).toBeTruthy();
    expect(screen.queryByRole('slider', { name: '全景接缝方向' })).toBeNull();

    // A backdrop is a framing reference: it is not one of the scene's sixty captures, and it stays
    // out of a delivered still unless it is asked for.
    await userEvent.click(screen.getByRole('tab', { name: '截图库' }));
    expect(screen.getByRole('heading', { name: /截图库/ }).textContent).toContain('0');
    await userEvent.click(screen.getByRole('tab', { name: '机位' }));
    const include = within(screen.getByRole('region', { name: '场景背景' })).getByLabelText('导出时包含背景');
    expect(include).toHaveProperty('checked', false);
    await userEvent.click(include);
    expect(include).toHaveProperty('checked', true);
  });

  it('switches a whole crowd’s figure from the pose panel in one operation', async () => {
    const base = planResponse().plan;
    stage = {
      ...base,
      crowds: [{ id: 'crowd-01', label: '围观', rows: 1, columns: 2, spacing: 1, center: [4, 4], yaw_deg: 0, body_type: 'standard', seed: 7 }],
      actors: [
        ...base.actors,
        { ...base.actors[2], id: 'crowd-01-001', name: '围观-01', position: [3.5, 4], role: 'crowd', crowd_id: 'crowd-01' },
        { ...base.actors[2], id: 'crowd-01-002', name: '围观-02', position: [4.5, 4], role: 'crowd', crowd_id: 'crowd-01' },
      ],
    };
    await open();
    await userEvent.click(within(screen.getByRole('region', { name: '群演' })).getByRole('button', { name: /^围观/ }));
    await userEvent.click(screen.getByRole('tab', { name: '姿势' }));
    const panel = screen.getByRole('region', { name: '姿势' });
    expect(within(panel).getByRole('heading', { name: /围观/ }).textContent).toContain('2 人');

    await userEvent.click(within(panel).getByRole('radio', { name: '关节人偶' }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'set_figure', crowd_id: 'crowd-01', figure: 'mannequin' }]);
    await userEvent.selectOptions(within(panel).getByLabelText('整组体型'), 'heavy');
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations).toEqual([{ op: 'set_figure', crowd_id: 'crowd-01', body_type: 'heavy' }]);

    // Both changes are taken back member by member, with the array's own record restored first.
    await screen.findByText(/第 5 版/);
    await userEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2].operations).toEqual([
      { op: 'set_figure', crowd_id: 'crowd-01', body_type: 'standard' },
      { op: 'set_figure', name: '围观-01', body_type: 'standard' },
      { op: 'set_figure', name: '围观-02', body_type: 'standard' },
    ]);
  });

  it('exports and imports a desk project from inside the desk', async () => {
    const created = vi.fn(() => 'blob:desk');
    vi.stubGlobal('URL', { ...URL, createObjectURL: created, revokeObjectURL: vi.fn() });
    const inner = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/export?format=')) return json({ fileName: 'E1S01-director-desk.json', document: { version: 1, objects: [] }, note: '导出说明' });
      return inner(input, init) as Promise<Response>;
    });
    await open();

    await userEvent.click(screen.getByRole('button', { name: '导出 3D 导演台工程' }));
    await waitFor(() => expect(created).toHaveBeenCalled());
    expect(await screen.findByText('导出说明')).toBeTruthy();

    const before = fetchMock.mock.calls.length;
    await userEvent.upload(screen.getByLabelText('导入导演台工程文件'), new File([JSON.stringify({ version: 1, objects: [] })], 'p.json', { type: 'application/json' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(call => String(call[0]).endsWith('/import')).length).toBe(1));
    const sent = JSON.parse(String((fetchMock.mock.calls.find(call => String(call[0]).endsWith('/import'))![1] as RequestInit).body));
    expect(sent).toEqual({ baseRevision: 3, document: { version: 1, objects: [] } });
    // The import is the server's own edit, so the session reads the scene again afterwards.
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before + 1);
    expect(await screen.findByText(/背景与模型绑定不在工程格式里，保持不变/)).toBeTruthy();
  });

  it('lists the keyboard shortcuts behind the ? button', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: '快捷键' }));
    const card = screen.getByRole('dialog', { name: '快捷键' });
    expect(within(card).getAllByRole('term').map(item => item.textContent)).toEqual([
      'V', 'W', 'E', 'R', 'M', 'P', '1 / 2 / 3', '空格', 'Delete', 'Ctrl / ⌘ + Z', 'Ctrl / ⌘ + Shift + Z', 'Esc',
    ]);
    await userEvent.click(within(card).getByRole('button', { name: '知道了' }));
    expect(screen.queryByRole('dialog', { name: '快捷键' })).toBeNull();
  });

  describe('timeline', () => {
    const WALK = [{ time: 0, position: [-1.3, 0], yaw_deg: 90, easing: 'linear' }, { time: 2, position: [0.7, 0], yaw_deg: 90, easing: 'linear' }];
    const scrubTo = (seconds: number) => {
      const ruler = screen.getByRole('slider', { name: '播放头' });
      vi.spyOn(ruler, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 500, top: 0, height: 20, right: 500, bottom: 20, x: 0, y: 0, toJSON: () => ({}) });
      fireEvent.pointerDown(ruler, { clientX: seconds * 100, pointerId: 1 });
    };

    beforeEach(() => {
      stage = { ...stage, timelines: { 1: { duration_s: 5, fps: 24, camera: [], actors: { 林夏: WALK as never } } } };
    });

    it('draws both views at the playhead without touching the plan or the undo stack', async () => {
      await open();
      expect(screen.getByTestId('actor-林夏').textContent).toBe('-1.3,0');
      scrubTo(1);
      expect(screen.getByLabelText('时间码').textContent).toBe('00:01:00');
      expect(screen.getByTestId('actor-林夏').textContent).toBe('-0.3,0');
      expect(screen.getByTestId('lens-sees').textContent).toBe('-0.3,0');
      expect(patches()).toHaveLength(0);
      expect(screen.getByRole('button', { name: '撤销' })).toHaveProperty('disabled', true);
    });

    it('writes a drag into the key the playhead sits on, and says so', async () => {
      await open();
      await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
      expect(screen.getByRole('note').textContent).toContain('都写入这一帧');
      await userEvent.click(screen.getByRole('button', { name: 'drag' }));
      expect(screen.getByTestId('actor-林夏').textContent).toBe('0.5,1');
      await userEvent.click(screen.getByRole('button', { name: 'release' }));
      await waitFor(() => expect(patches()).toHaveLength(1));
      expect(patches()[0]).toMatchObject({ solve: false, operations: [{ op: 'set_timeline', shot_id: 1, actors: { 林夏: [{ ...WALK[0], position: [0.5, 1] }, WALK[1]] } }] });

      // Undo puts the key back, not the mark.
      await waitFor(() => expect(screen.getByRole('button', { name: '撤销' })).toHaveProperty('disabled', false));
      await userEvent.click(screen.getByRole('button', { name: '撤销' }));
      await waitFor(() => expect(patches()).toHaveLength(2));
      expect(patches()[1].operations).toEqual([{ op: 'set_timeline', shot_id: 1, actors: { 林夏: WALK } }]);
    });

    it('writes a drag to the base plan anywhere else, and says that too', async () => {
      await open();
      await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
      scrubTo(1);
      expect(screen.getByRole('note').textContent).toContain('现在的修改写入基础站位');
      await userEvent.click(screen.getByRole('button', { name: 'release' }));
      await waitFor(() => expect(patches()).toHaveLength(1));
      expect(patches()[0].operations).toEqual([{ op: 'move_actor', name: '林夏', position: [0.5, 1] }]);
      // The keys still decide what is on screen at this instant.
      expect(screen.getByTestId('actor-林夏').textContent).toBe('-0.3,0');
    });

    it('keys the selected actor from the timeline through the same PATCH queue', async () => {
      await open();
      await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
      scrubTo(1);
      await userEvent.click(screen.getByRole('button', { name: /在播放头处打关键帧 · 林夏/ }));
      await waitFor(() => expect(patches()).toHaveLength(1));
      const keys = (patches()[0].operations[0].actors as Record<string, Array<{ time: number; position: number[] }>>)['林夏'];
      expect(keys.map(key => [key.time, key.position])).toEqual([[0, [-1.3, 0]], [1, [-0.3, 0]], [2, [0.7, 0]]]);
      expect(patches()[0].solve).toBe(false);
    });
  });
});

