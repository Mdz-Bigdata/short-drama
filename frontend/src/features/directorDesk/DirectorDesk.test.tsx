// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { planResponse } from '../spatial/spatialFixtures';
import type { StagePlan } from '../spatial/spatialTypes';
import { applyAll } from './deskOperations';
import { DirectorDesk } from './DirectorDesk';
import type { CompareRendererProps } from './three/CompareRenderer';
import type { DeskViewportProps } from './three/DeskViewport';
import type { LensViewportProps } from './three/LensViewport';

const { frameSelection } = vi.hoisted(() => ({ frameSelection: vi.fn() }));

// The viewports are the three.js boundary. The stand-ins expose what the desk hands them and let
// a test play the part of the gizmo: preview while "dragging", one commit on release.
vi.mock('./three/DeskViewport', () => ({
  default: function MockDeskViewport({ plan, tool, readOnly, trails, pathTarget, pathRefusal, onPreview, onCommit, onSelect, onPath, onReady }: DeskViewportProps) {
    useEffect(() => {
      onReady?.({ viewPose: () => ({ position: [4, 3, 6], target: [0.6, 1, -0.4] }), frameSelection });
      return () => onReady?.(null);
    }, [onReady]);
    const drag = [{ op: 'move_actor', name: '林夏', position: [0.5, 1] }];
    return (
      <div data-testid="desk-viewport" data-tool={tool} data-readonly={String(readOnly)} data-path-target={pathTarget ? JSON.stringify(pathTarget) : ''} data-path-refusal={pathRefusal}>
        {plan.actors.map(actor => <span key={actor.id} data-testid={`actor-${actor.name}`}>{actor.position.join(',')}</span>)}
        {trails?.filter(trail => trail.kind === 'actor').map(trail => <span key={trail.owner} data-testid={`track-${trail.owner}`}>{trail.keys.map(key => key.position.join(',')).join(';')}</span>)}
        <button type="button" onClick={() => onSelect({ kind: 'actor', name: '林夏' }, false)}>pick 林夏</button>
        <button type="button" onClick={() => onSelect({ kind: 'camera', id: 'cam-01' }, false)}>pick cam-01</button>
        <button type="button" onClick={() => onSelect({ kind: 'camera', id: 'cam-02' }, false)}>pick cam-02</button>
        <button type="button" onClick={() => onPreview(drag)}>drag</button>
        <button type="button" onClick={() => onCommit(drag)}>release</button>
        <button type="button" onClick={() => onPath?.([[-1.3, 0], [0, 1], [1.2, 1.1]])}>stroke</button>
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

// The comparison canvas is three.js too; the stand-in hands over a renderer that draws nothing.
vi.mock('./three/CompareRenderer', () => ({
  default: function MockCompareRenderer({ onReady }: CompareRendererProps) {
    useEffect(() => {
      onReady?.({ renderThumbnails: () => Promise.resolve({}), cancel: () => {} });
      return () => onReady?.(null);
    }, [onReady]);
    return null;
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
    frameSelection.mockClear();
    // The timeline opens the way it was last left, and folded on a short window: start each test tall and unremembered.
    window.localStorage.clear();
    window.innerHeight = 900;
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
    // The director layout has no lens pane; the camera's frame floats over it in the picture-in-picture instead.
    const pip = screen.getByRole('region', { name: '当前机位画中画' });
    expect(await within(pip).findByTestId('lens-viewport')).toBeTruthy();
    expect(screen.getAllByTestId('lens-viewport')).toHaveLength(1);
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
    fireEvent.keyDown(window, { key: 'j' });
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
    // On a focused button Space presses that button; it does not also start playback.
    const fold = screen.getByRole('button', { name: '快捷键' });
    fold.focus();
    fireEvent.keyDown(fold, { key: ' ' });
    expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '播放' })).toBeTruthy();

    // F aims the director view at what is selected.
    fireEvent.keyDown(window, { key: 'f' });
    expect(frameSelection).toHaveBeenCalledTimes(1);

    // The shortcut card is the first thing Escape closes, then the comparison strip, then the measurement, then the selection.
    fireEvent.keyDown(window, { key: '?' });
    expect(screen.getByRole('dialog', { name: '快捷键' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '快捷键' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
    fireEvent.keyDown(window, { key: '4' });
    expect(await screen.findByRole('region', { name: '机位对比' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('region', { name: '机位对比' })).toBeNull();
    expect(screen.getByRole('contentinfo').textContent).toContain('已选：林夏');
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

    // The swatch opens on the colour the lens is drawing. Closing the picker without choosing sends nothing,
    // dragging inside it sends nothing, and the colour it is closed on is sent once.
    const swatch = within(panel).getByLabelText('背景色') as HTMLInputElement;
    expect(swatch.value).toBe('#fdf0f2');
    swatch.dispatchEvent(new Event('change', { bubbles: true }));
    fireEvent.blur(swatch);
    fireEvent.input(swatch, { target: { value: '#aa0000' } });
    fireEvent.input(swatch, { target: { value: '#102030' } });
    expect(patches()).toHaveLength(1);
    fireEvent.change(swatch, { target: { value: '#102030' } });
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1].operations).toEqual([{ op: 'set_backdrop', color: '#102030' }]);

    await userEvent.upload(within(panel).getByLabelText('上传背景图文件'), new File([new Uint8Array([1, 2, 3])], 'wall.png', { type: 'image/png' }));
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2].operations).toEqual([{ op: 'set_backdrop', kind: 'image', url: 'http://img.test/wall.jpg' }]);
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
    // Something done is news, not a warning; and it can be put away.
    const news = (await screen.findByText('导出说明')).closest('p')!;
    expect(news.getAttribute('role')).toBe('status');
    expect(news.className).not.toContain('is-warning');
    await userEvent.click(within(news).getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByText('导出说明')).toBeNull();

    const before = fetchMock.mock.calls.length;
    await userEvent.upload(screen.getByLabelText('导入导演台工程文件'), new File([JSON.stringify({ version: 1, objects: [] })], 'p.json', { type: 'application/json' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(call => String(call[0]).endsWith('/import')).length).toBe(1));
    const sent = JSON.parse(String((fetchMock.mock.calls.find(call => String(call[0]).endsWith('/import'))![1] as RequestInit).body));
    expect(sent).toEqual({ baseRevision: 3, document: { version: 1, objects: [] } });
    // The import is the server's own edit, so the session reads the scene again afterwards.
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before + 1);
    expect(await screen.findByText(/背景与模型绑定不在工程格式里，保持不变/)).toBeTruthy();
  });

  it('shows a problem as an alert in the warning tone, and lets it be dismissed too', async () => {
    const inner = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => (
      String(input).includes('/export?format=') ? json({ detail: '本场还没有可导出的空间方案' }, 409) : inner(input, init) as Promise<Response>
    ));
    await open();
    await userEvent.click(screen.getByRole('button', { name: '导出 CoStage 工程' }));
    const problem = await screen.findByRole('alert');
    expect(problem.textContent).toContain('本场还没有可导出的空间方案');
    expect(problem.className).toContain('is-warning');
    await userEvent.click(within(problem).getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('deletes every selected prop in one edit, and says what Delete does not remove', async () => {
    const base = planResponse().plan;
    stage = { ...base, landmarks: [...base.landmarks, { ...base.landmarks[0], id: 'mark-02', name: '茶杯', position: [1, -0.9] }] };
    await open();
    const outline = screen.getByRole('complementary', { name: '场景大纲' });
    await userEvent.click(within(outline).getByRole('button', { name: /^录音笔/ }));
    fireEvent.click(within(outline).getByRole('button', { name: /^茶杯/ }), { shiftKey: true });
    expect(screen.getByRole('contentinfo').textContent).toContain('已选 2 项');
    fireEvent.keyDown(window, { key: 'Delete' });
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'remove_landmark', name: '录音笔' }, { op: 'remove_landmark', name: '茶杯' }]);

    // A character is not removed with one key: the desk says so instead of staying silent.
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
    fireEvent.keyDown(window, { key: 'Backspace' });
    expect((await screen.findByRole('alert')).textContent).toContain('Delete 只删除道具和本镜的候选机位');
    expect(patches()).toHaveLength(1);
  });

  it('closes the crowd dialog with Escape and leaves the desk open', async () => {
    const onClose = vi.fn();
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={onClose} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
    await userEvent.click(screen.getByRole('button', { name: '添加群演阵列' }));
    const dialog = screen.getByRole('dialog', { name: '添加群演阵列' });
    expect(document.activeElement).toBe(within(dialog).getByLabelText('名称'));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '添加群演阵列' })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('contentinfo').textContent).toContain('已选：林夏');
    // The button that opened the dialog has the focus again.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '添加群演阵列' }));
  });

  it('keeps the crowd dialog open when Escape only dismisses an input method’s candidates', async () => {
    const onClose = vi.fn();
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={onClose} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('button', { name: '添加群演阵列' }));
    const name = within(screen.getByRole('dialog', { name: '添加群演阵列' })).getByLabelText('名称');
    fireEvent.keyDown(name, { key: 'Escape', isComposing: true });
    fireEvent.keyDown(name, { key: 'Escape', keyCode: 229 });
    expect(screen.getByRole('dialog', { name: '添加群演阵列' })).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(name, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '添加群演阵列' })).toBeNull();
  });

  it('gives Escape to the dialog on top, then to the move settings under it', async () => {
    const onClose = vi.fn();
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={onClose} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('button', { name: '运镜预设' }));
    await userEvent.click(screen.getByRole('button', { name: '添加群演阵列' }));
    const name = within(screen.getByRole('dialog', { name: '添加群演阵列' })).getByLabelText('名称');
    expect(document.activeElement).toBe(name);

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '添加群演阵列' })).toBeNull();
    expect(screen.getByRole('form', { name: '运镜预设' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '添加群演阵列' }));

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('form', { name: '运镜预设' })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('makes the player of a clip at full size a Tab stop, and keeps the desk’s keys off it', async () => {
    const clip = {
      id: 'cap-clip', kind: 'clip', shot_id: 1, camera_id: stage.shots[0].camera_id, url: 'http://img.test/desk_clip.mp4', width: 720, height: 1280,
      duration_s: 4, fps: 24, plan_revision: stage.revision, shows_limbs: true, monochrome: true, labelled: false, created_at: '2026-09-20T02:00:00Z', stale: false, warning: '',
    };
    const inner = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => (
      String(input).includes('/director-desk/') ? json({ captures: [clip], applied: {} }) : inner(input, init) as Promise<Response>
    ));
    // jsdom lays nothing out, so every element reports no offsetParent; the trap reads that as hidden.
    const layout = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetParent');
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => document.body });
    try {
      await open();
      await userEvent.click(screen.getByRole('tab', { name: '截图库' }));
      await userEvent.click((await screen.findAllByRole('button', { name: /^查看 第 1 镜/ }))[0]);
      const viewer = screen.getByRole('dialog', { name: '查看截图' });
      const close = within(viewer).getByRole('button', { name: '关闭查看' });
      expect(document.activeElement).toBe(close);
      // The player comes after the close button: Tab is left to the browser, which goes on into its controls.
      expect(fireEvent.keyDown(close, { key: 'Tab' })).toBe(true);
      // On the player Space pauses the clip and M mutes it: neither is a desk shortcut while it is open.
      const player = within(viewer).getByLabelText('第 1 镜白模视频');
      expect(fireEvent.keyDown(player, { key: ' ' })).toBe(true);
      fireEvent.keyDown(player, { key: 'm' });
      expect(screen.getByTestId('desk-viewport').dataset.tool).toBe('select');
    } finally {
      if (layout) Object.defineProperty(HTMLElement.prototype, 'offsetParent', layout);
    }
  });

  it('keeps Tab inside the crowd dialog while it is open', async () => {
    // jsdom lays nothing out, so every element reports no offsetParent; the trap reads that as hidden.
    const layout = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetParent');
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => document.body });
    try {
      render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={vi.fn()} />);
      await screen.findByTestId('desk-viewport');
      await userEvent.click(screen.getByRole('button', { name: '添加群演阵列' }));
      const dialog = screen.getByRole('dialog', { name: '添加群演阵列' });
      const stops = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled])')];
      const [first, last] = [stops[0], stops[stops.length - 1]];
      last.focus();
      await userEvent.tab();
      expect(document.activeElement).toBe(first);
      await userEvent.tab({ shift: true });
      expect(document.activeElement).toBe(last);
    } finally {
      if (layout) Object.defineProperty(HTMLElement.prototype, 'offsetParent', layout);
    }
  });

  it('remembers whether the timeline was folded, and opens folded on a short window', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: '收起时间线' }));
    expect(screen.getByRole('button', { name: /^时间线 · / }).getAttribute('aria-expanded')).toBe('false');
    cleanup();

    await open();
    expect(screen.queryByRole('button', { name: '收起时间线' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /^时间线 · / }));
    expect(screen.getByRole('button', { name: '收起时间线' })).toBeTruthy();
    cleanup();

    // Opened by hand last time: a short window does not fold it again.
    window.innerHeight = 700;
    await open();
    expect(screen.getByRole('button', { name: '收起时间线' })).toBeTruthy();
    cleanup();

    // Never chosen: the short window gives the height to the stage.
    window.localStorage.clear();
    await open();
    expect(screen.queryByRole('button', { name: '收起时间线' })).toBeNull();
    expect(screen.getByRole('button', { name: /^时间线 · / })).toBeTruthy();
  });

  it('lists the keyboard shortcuts behind the ? button', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: '快捷键' }));
    const card = screen.getByRole('dialog', { name: '快捷键' });
    expect(within(card).getAllByRole('term').map(item => item.textContent)).toEqual([
      'V', 'W', 'E', 'R', 'M', 'J', 'P', '1 / 2 / 3', '4', 'F', '空格', 'Delete', '← / →',
      'Ctrl / ⌘ + Z', 'Ctrl / ⌘ + Shift + Z', 'Ctrl / ⌘ + Y', '?', 'Esc', '空格（成片预演）', 'Esc（成片预演）',
    ]);
    // Icon-only buttons say what they do, and their key, on hover.
    expect(screen.getByRole('button', { name: '关闭 3D 导演台' }).getAttribute('title')).toBe('关闭 3D 导演台（Esc）');
    expect(screen.getByRole('button', { name: '重新读取' }).getAttribute('title')).toBeTruthy();
    expect(screen.getByRole('radio', { name: /并排/ }).getAttribute('title')).toBe('并排视图（2）');
    expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '播放' }).getAttribute('title')).toBe('播放（空格）');
    await userEvent.click(within(card).getByRole('button', { name: '知道了' }));
    expect(screen.queryByRole('dialog', { name: '快捷键' })).toBeNull();
  });

  describe('path tool', () => {
    const ROUTE = [[-1.3, 0], [0, 1], [1.2, 1.1]];
    const pathButton = () => screen.getByRole('radio', { name: /路径/ });

    it('is offered for an actor, not for a crowd, and sends the stroke alone as set_path', async () => {
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
      const viewport = screen.getByTestId('desk-viewport');
      // Nothing selected: the button is out, and the shortcut says why instead of switching.
      expect(pathButton()).toHaveProperty('disabled', true);
      fireEvent.keyDown(window, { key: 'p' });
      expect(viewport.getAttribute('data-tool')).toBe('select');
      expect(screen.getByText(/手绘路径：先选择一个角色/)).toBeTruthy();

      await userEvent.click(within(screen.getByRole('region', { name: '群演' })).getByRole('button', { name: /^围观/ }));
      expect(pathButton()).toHaveProperty('disabled', true);
      expect(pathButton().getAttribute('title')).toContain('群演');
      expect(viewport.getAttribute('data-path-refusal')).toContain('群演');

      await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
      expect(pathButton()).toHaveProperty('disabled', false);
      fireEvent.keyDown(window, { key: 'p' });
      expect(viewport.getAttribute('data-tool')).toBe('path');
      expect(viewport.getAttribute('data-path-target')).toBe(JSON.stringify({ kind: 'actor', name: '林夏' }));

      await userEvent.click(screen.getByRole('button', { name: 'stroke' }));
      await waitFor(() => expect(patches()).toHaveLength(1));
      // The default pace walks the route, so the figure gets legs and the walk its motion.
      expect(patches()[0]).toEqual({
        baseRevision: 3, solve: false,
        operations: [
          { op: 'set_figure', name: '林夏', figure: 'humanoid' },
          { op: 'set_path', shot_id: 1, target: '林夏', points: ROUTE, speed_mps: 1.4, clip: 'human-walk-v1' },
        ],
      });
      // The route is keyed by the server, so the desk takes its answer rather than applying anything itself.
      expect(await screen.findByText(/已保存 · 第 4 版/)).toBeTruthy();
    });

    it('takes the filming camera, aimed at its first subject, but not another shot’s lens', async () => {
      await open();
      const viewport = screen.getByTestId('desk-viewport');
      await userEvent.click(screen.getByRole('button', { name: 'pick cam-02' }));
      expect(pathButton()).toHaveProperty('disabled', true);
      expect(pathButton().getAttribute('title')).toContain('不拍摄本镜');

      await userEvent.click(screen.getByRole('button', { name: 'pick cam-01' }));
      await userEvent.click(pathButton());
      expect(viewport.getAttribute('data-tool')).toBe('path');
      expect(viewport.getAttribute('data-path-target')).toBe(JSON.stringify({ kind: 'camera', id: 'cam-01', lookAt: '林夏' }));
      await userEvent.click(screen.getByRole('button', { name: 'stroke' }));
      await waitFor(() => expect(patches()).toHaveLength(1));
      expect(patches()[0].operations).toEqual([{ op: 'set_path', shot_id: 1, target: 'camera', points: ROUTE, look_at: '林夏', speed_mps: 1.4 }]);
    });

    it('keeps the pace field in the status bar, shown only while the path tool is in hand', async () => {
      await open();
      expect(screen.queryByLabelText('路径速度（米/秒）')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'pick 林夏' }));
      await userEvent.click(pathButton());
      // In the status bar, so that picking the tool does not re-wrap the top bar and move the stage.
      expect(screen.getByRole('contentinfo').contains(screen.getByLabelText('路径速度（米/秒）'))).toBe(true);
      await userEvent.click(screen.getByRole('radio', { name: /选择/ }));
      expect(screen.queryByLabelText('路径速度（米/秒）')).toBeNull();
    });

    it('hands every moving actor track of the shot to the director view', async () => {
      stage = { ...stage, timelines: { 1: { duration_s: 5, fps: 24, camera: [], actors: { 林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 2, position: [0.7, 0], easing: 'linear' }] as never } } } };
      await open();
      expect(screen.getByTestId('track-林夏').textContent).toBe('-1.3,0,0;0.7,0,0');
      await userEvent.selectOptions(screen.getByLabelText('镜头'), '2');
      expect(screen.queryByTestId('track-林夏')).toBeNull();
    });
  });

  it('opens the camera comparison over the stage with 4 and promotes a candidate from it', async () => {
    const base = planResponse().plan;
    stage = {
      ...base,
      cameras: [...base.cameras, { ...base.cameras[0], id: 'alt-01-01', label: '01 建立 · 候选1', lens_mm: 50 }],
      shots: [{ ...base.shots[0], alt_camera_ids: ['alt-01-01'] }, base.shots[1]],
    };
    await open();
    expect(screen.queryByRole('region', { name: '机位对比' })).toBeNull();
    fireEvent.keyDown(window, { key: '4' });
    const strip = await screen.findByRole('region', { name: '机位对比' });
    expect(screen.getByRole('button', { name: '机位对比' }).getAttribute('aria-pressed')).toBe('true');
    // The strip sits over the stage, so both views and the side panel are still there.
    expect(screen.getByTestId('desk-viewport')).toBeTruthy();
    expect(screen.getByTestId('lens-viewport')).toBeTruthy();
    const cards = within(strip).getAllByRole('listitem');
    expect(cards.map(card => card.querySelector('strong')?.textContent)).toEqual(['01 建立', '01 建立 · 候选1']);

    // 选中 hands the lens to the desk: the inspector follows it.
    await userEvent.click(within(cards[1]).getByRole('button', { name: /^选中/ }));
    expect(screen.getByRole('contentinfo').textContent).toContain('已选：01 建立 · 候选1');
    expect(screen.getByRole('tab', { name: '属性' }).getAttribute('aria-selected')).toBe('true');

    await userEvent.click(within(cards[1]).getByRole('button', { name: /使用此机位/ }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'use_camera', shot_id: 1, camera_id: 'alt-01-01' }]);
    // The promoted lens now films, so it moved to the front of the strip.
    await waitFor(() => expect(within(strip).getAllByRole('listitem').map(card => card.querySelector('strong')?.textContent)).toEqual(['01 建立 · 候选1', '01 建立']));

    await userEvent.click(screen.getByRole('button', { name: '关闭机位对比' }));
    expect(screen.queryByRole('region', { name: '机位对比' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '机位对比' }));
    expect(screen.getByRole('region', { name: '机位对比' })).toBeTruthy();
    fireEvent.keyDown(window, { key: '4' });
    expect(screen.queryByRole('region', { name: '机位对比' })).toBeNull();
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

    it('keeps Delete and Space on a focused clip inside the timeline: the clip goes, the selected prop stays', async () => {
      stage = { ...stage, timelines: { 1: { ...stage.timelines![1], clips: { 林夏: [{ id: 'clip-1', clip: 'human-walk-v1', start: 0, end: 1 }] } } } };
      await open();
      await userEvent.click(within(screen.getByRole('complementary', { name: '场景大纲' })).getByRole('button', { name: /^录音笔/ }));
      const block = screen.getByRole('button', { name: /「林夏」动作片段 行走/ });
      block.focus();
      fireEvent.keyDown(block, { key: ' ' });
      expect(block.getAttribute('aria-pressed')).toBe('true');
      expect(within(screen.getByLabelText('时间线')).getByRole('button', { name: '播放' })).toBeTruthy();

      fireEvent.keyDown(block, { key: 'Delete' });
      await waitFor(() => expect(patches()).toHaveLength(1));
      expect(patches()[0].operations).toEqual([{ op: 'set_timeline', shot_id: 1, clips: { 林夏: [] } }]);
      expect(within(screen.getByRole('complementary', { name: '场景大纲' })).getByText('录音笔')).toBeTruthy();

      // The clip took the focus with it. It stays on the timeline, so the key held down or pressed again
      // does not go on to the prop selected on the stage.
      const timeline = screen.getByLabelText('时间线');
      expect(document.activeElement).toBe(timeline);
      fireEvent.keyDown(document.activeElement!, { key: 'Delete', repeat: true });
      fireEvent.keyDown(document.activeElement!, { key: 'Delete' });
      expect((await within(timeline).findByRole('alert')).textContent).toContain('没有删除任何内容');
      expect(within(screen.getByRole('complementary', { name: '场景大纲' })).getByText('录音笔')).toBeTruthy();
      expect(patches()).toHaveLength(1);
    });

    it('takes Delete on the bar of a picked clip as that clip, and a held Delete on the stage as one press', async () => {
      stage = { ...stage, timelines: { 1: { ...stage.timelines![1], clips: { 林夏: [{ id: 'clip-1', clip: 'human-walk-v1', start: 0, end: 1 }] } } } };
      await open();
      const outline = screen.getByRole('complementary', { name: '场景大纲' });
      await userEvent.click(within(outline).getByRole('button', { name: /^录音笔/ }));
      await userEvent.click(screen.getByRole('button', { name: /「林夏」动作片段 行走/ }));
      // The bin on the clip's bar says（Delete）: with focus on it the key means the clip.
      const bin = screen.getByRole('button', { name: '删除动作片段' });
      bin.focus();
      fireEvent.keyDown(bin, { key: 'Delete' });
      await waitFor(() => expect(patches()).toHaveLength(1));
      expect(patches()[0].operations).toEqual([{ op: 'set_timeline', shot_id: 1, clips: { 林夏: [] } }]);
      expect(within(outline).getByText('录音笔')).toBeTruthy();

      // Back on the stage, a key that is still held down removes nothing; pressed, it removes the prop.
      (document.activeElement as HTMLElement).blur();
      fireEvent.keyDown(window, { key: 'Delete', repeat: true });
      expect(within(outline).getByText('录音笔')).toBeTruthy();
      fireEvent.keyDown(window, { key: 'Delete' });
      await waitFor(() => expect(patches()).toHaveLength(2));
      expect(patches()[1].operations).toEqual([{ op: 'remove_landmark', name: '录音笔' }]);
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

  describe('monitors, picture-in-picture and 成片预演', () => {
    it('docks a monitor per shot, switches shot from it, and remembers whether it was open', async () => {
      await open();
      // A 1024-px window starts with the wall folded; the button opens it.
      expect(screen.queryByRole('region', { name: '监视器' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: '监视器' }));
      const wall = screen.getByRole('region', { name: '监视器' });
      const items = within(wall).getAllByRole('button', { name: /^第 \d 镜/ });
      expect(items.map(item => item.querySelector('strong')?.textContent)).toEqual(['第 1 镜｜建立 · 林夏、周教授', '第 2 镜｜单人 · 林夏']);
      expect(items[0].getAttribute('aria-pressed')).toBe('true');

      await userEvent.click(items[1]);
      expect((screen.getByRole('combobox', { name: '镜头' }) as HTMLSelectElement).value).toBe('2');
      expect(screen.getByTestId('lens-camera').textContent).toBe('cam-02:65');
      expect(window.localStorage.getItem('directorDesk.monitorsOpen')).toBe('1');

      await userEvent.click(within(wall).getByRole('button', { name: '收起监视器' }));
      expect(screen.queryByRole('region', { name: '监视器' })).toBeNull();
      expect(window.localStorage.getItem('directorDesk.monitorsOpen')).toBe('0');
    });

    it('lists the current shot’s other lenses under it and looks through one when picked', async () => {
      const base = planResponse().plan;
      stage = {
        ...base,
        cameras: [...base.cameras, { ...base.cameras[0], id: 'alt-01-01', label: '01 建立 · 候选1', lens_mm: 50 }],
        shots: [{ ...base.shots[0], alt_camera_ids: ['alt-01-01'] }, base.shots[1]],
      };
      window.localStorage.setItem('directorDesk.monitorsOpen', '1');
      await open();
      const wall = screen.getByRole('region', { name: '监视器' });
      const lens = within(wall).getByRole('button', { name: /01 建立 · 候选1/ });
      expect(lens.textContent).toContain('候选');
      await userEvent.click(lens);
      expect(screen.getByTestId('lens-camera').textContent).toBe('alt-01-01:50');
      expect(lens.getAttribute('aria-pressed')).toBe('true');
    });

    it('floats the current camera over the director view, expands it, closes it and brings it back', async () => {
      await open();
      await userEvent.click(screen.getByRole('radio', { name: /导演/ }));
      const pip = screen.getByRole('region', { name: '当前机位画中画' });
      expect(await within(pip).findByTestId('lens-camera')).toBeTruthy();
      expect(within(pip).getByTestId('lens-camera').textContent).toBe('cam-01:28');
      expect(within(pip).getByText('第 1 镜 · 01 建立')).toBeTruthy();

      await userEvent.click(within(pip).getByRole('button', { name: '放大到机位视图' }));
      expect(screen.getByRole('radio', { name: /^机位$/ }).getAttribute('aria-checked')).toBe('true');
      expect(screen.queryByRole('region', { name: '当前机位画中画' })).toBeNull();

      await userEvent.click(screen.getByRole('radio', { name: /导演/ }));
      await userEvent.click(within(screen.getByRole('region', { name: '当前机位画中画' })).getByRole('button', { name: '关闭画中画' }));
      expect(screen.queryByRole('region', { name: '当前机位画中画' })).toBeNull();
      expect(window.localStorage.getItem('directorDesk.pipOpen')).toBe('0');

      // From another layout the button brings the director view back with the window on it.
      await userEvent.click(screen.getByRole('radio', { name: /并排/ }));
      await userEvent.click(screen.getByRole('button', { name: '画中画' }));
      expect(screen.getByRole('radio', { name: /导演/ }).getAttribute('aria-checked')).toBe('true');
      expect(screen.getByRole('region', { name: '当前机位画中画' })).toBeTruthy();
    });

    it('plays the scene through its lenses in 成片预演, shot after shot, and edits nothing', async () => {
      // A short first shot, so playing on into the second takes a moment.
      stage = { ...stage, timelines: { 1: { duration_s: 0.2, fps: 24, camera: [], actors: {} }, 2: { duration_s: 3, fps: 24, camera: [], actors: {} } } };
      await open();
      // A lens picked for a look does not hold in the preview: it shows the cut.
      await userEvent.click(screen.getByRole('button', { name: 'pick cam-02' }));
      await userEvent.click(screen.getByRole('radio', { name: /成片预演/ }));
      expect(screen.getByRole('radio', { name: /成片预演/ }).getAttribute('aria-checked')).toBe('true');
      expect(screen.queryByTestId('desk-viewport')).toBeNull();
      expect(screen.queryByRole('complementary', { name: '场景大纲' })).toBeNull();
      expect(screen.queryByRole('radiogroup', { name: '工具' })).toBeNull();
      expect(screen.queryByLabelText('时间线')).toBeNull();
      expect(await screen.findByTestId('lens-camera')).toBeTruthy();
      expect(screen.getByTestId('lens-camera').textContent).toBe('cam-01:28');
      const player = screen.getByRole('region', { name: '成片预演播放' });
      expect(within(player).getByLabelText('成片时间').textContent).toBe('00:00 / 00:03');

      // Delete and the tool keys do nothing here; nothing is sent.
      fireEvent.keyDown(window, { key: 'Delete' });
      fireEvent.keyDown(window, { key: 'w' });
      expect(patches()).toHaveLength(0);

      fireEvent.keyDown(window, { key: ' ' });
      await waitFor(() => expect((screen.getByRole('combobox', { name: '镜头' }) as HTMLSelectElement).value).toBe('2'), { timeout: 3000 });
      expect(screen.getByTestId('lens-camera').textContent).toBe('cam-02:65');
      // The next shot rolls on by itself.
      await userEvent.click(await within(player).findByRole('button', { name: '暂停' }, { timeout: 500 }));

      // The strip jumps to a shot's start; the scrubber finds the shot a time falls in.
      await userEvent.click(within(player).getByRole('button', { name: /跳到第 1 镜/ }));
      expect((screen.getByRole('combobox', { name: '镜头' }) as HTMLSelectElement).value).toBe('1');
      fireEvent.change(within(player).getByRole('slider', { name: '成片进度' }), { target: { value: '1.2' } });
      expect((screen.getByRole('combobox', { name: '镜头' }) as HTMLSelectElement).value).toBe('2');
      expect(within(player).getByLabelText('成片时间').textContent).toBe('00:01 / 00:03');

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.getByRole('radio', { name: /场景调度/ }).getAttribute('aria-checked')).toBe('true');
      expect(await screen.findByTestId('desk-viewport')).toBeTruthy();
      expect(screen.getByLabelText('时间线')).toBeTruthy();
      // Escape left the preview only; the desk is still open.
      expect(screen.getByRole('dialog', { name: 'E1S01 · 办公室' })).toBeTruthy();
    });
  });
});
