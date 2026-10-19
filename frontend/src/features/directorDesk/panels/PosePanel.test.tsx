// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StageOperation, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest } from '../deskTypes';
import { presetById } from '../lib/poses';
import { PosePanel } from './PosePanel';

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

function withActor(changes: Record<string, unknown>, plan: StagePlan = PLAN): StagePlan {
  return { ...plan, actors: plan.actors.map(actor => (actor.name === '林夏' ? { ...actor, ...changes } : actor)) };
}

describe('PosePanel', () => {
  const fetchMock = vi.fn();
  const onCommit = vi.fn<(request: EditRequest) => void>();
  const onPreview = vi.fn<(operations: StageOperation[] | null) => void>();
  const onShotOnly = vi.fn();
  let library: Array<{ id: string; name: string; pose: Record<string, unknown>; created_at: string }>;
  const committed = () => onCommit.mock.calls.map(call => call[0].operations[0]);
  const panel = (plan: StagePlan, props: Partial<Parameters<typeof PosePanel>[0]> = {}) => (
    <PosePanel
      plan={plan} shot={plan.shots[0]} selection={[{ kind: 'actor', name: '林夏' }]} editable shotOnly={false} footLock
      onShotOnly={onShotOnly} onFootLock={() => {}} onCommit={onCommit} onPreview={onPreview} {...props}
    />
  );

  beforeEach(() => {
    library = [{ id: 'p1', name: '持剑', pose: { preset: '', joints: { 'rightElbow.bend': 70, 'rightHand.index.curl': 95 }, clip: '', clip_phase: 0 }, created_at: '2026-09-01T00:00:00Z' }];
    onCommit.mockReset();
    onPreview.mockReset();
    onShotOnly.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { name: string; pose: Record<string, unknown> };
        library = [...library.filter(item => item.name !== body.name), { id: `p-${body.name}`, name: body.name, pose: body.pose, created_at: '2026-09-20T00:00:00Z' }];
      }
      if (init?.method === 'DELETE') library = library.filter(item => item.id !== url.split('/').pop());
      return json({ poses: library });
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('asks for an actor, and keeps a stand-in limbless until its figure is changed', async () => {
    const { rerender } = render(panel(PLAN, { selection: [] }));
    expect(screen.getByText(/选择一个角色后/)).toBeTruthy();
    rerender(panel(PLAN));
    expect(screen.getByRole('radio', { name: '白模柱体' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByRole('group', { name: '预设姿势' })).toBeNull();
    expect(screen.queryByRole('note')).toBeNull();

    await userEvent.click(screen.getByRole('radio', { name: '关节人偶' }));
    await userEvent.selectOptions(screen.getByLabelText('体型'), 'child');
    expect(committed()).toEqual([
      { op: 'set_figure', name: '林夏', figure: 'mannequin' },
      { op: 'set_figure', name: '林夏', body_type: 'child' },
    ]);
  });

  it('applies one of twenty-five presets as a single set_pose and warns that limbs reach the prompt', async () => {
    render(panel(withActor({ figure: 'mannequin' })));
    const presets = within(screen.getByRole('group', { name: '预设姿势' })).getAllByRole('button');
    expect(presets).toHaveLength(25);
    expect(screen.getByRole('note').textContent).toContain('白模带四肢');

    await userEvent.click(screen.getByRole('button', { name: '单膝跪' }));
    expect(committed()).toEqual([{ op: 'set_pose', name: '林夏', preset: 'kneel-one', joints: presetById('kneel-one')!.joints, clip: '', clip_phase: 0 }]);
    expect(onCommit.mock.calls[0][0].label).toBe('林夏：单膝跪');
  });

  it('previews a joint while the slider moves and saves once, clamped, when it is let go', () => {
    render(panel(withActor({ figure: 'mannequin', body_type: 'child', pose: { preset: 'walk', joints: { 'leftKnee.bend': 12 } } })));
    const groups = screen.getAllByRole('group').filter(node => node.tagName === 'DETAILS');
    expect(groups.map(node => node.querySelector('summary')?.textContent)).toEqual(['头颈', '躯干', '左臂', '右臂', '左手', '右手', '左腿', '右腿']);

    const slider = screen.getByLabelText('左膝 弯曲') as HTMLInputElement;
    expect([slider.min, slider.max, slider.step, slider.value]).toEqual(['0', '120', '1', '12']);
    fireEvent.change(slider, { target: { value: '60' } });
    fireEvent.change(slider, { target: { value: '75' } });
    expect(onCommit).not.toHaveBeenCalled();
    expect(onPreview).toHaveBeenCalledTimes(2);
    expect(onPreview.mock.calls[1][0]?.[0]).toMatchObject({ op: 'set_pose', name: '林夏', preset: 'walk', joints: { 'leftKnee.bend': 75 } });
    fireEvent.pointerUp(slider);
    fireEvent.blur(slider);
    expect(committed()).toEqual([{ op: 'set_pose', name: '林夏', preset: 'walk', joints: { 'leftKnee.bend': 75 }, clip: '', clip_phase: 0 }]);

    // Typed past the range: clamped to what a child's knee allows.
    const typed = screen.getByLabelText('左膝 弯曲 数值');
    fireEvent.blur(typed, { target: { value: '400' } });
    expect(committed()[1]).toMatchObject({ joints: { 'leftKnee.bend': 120 } });
  });

  it('mirrors, resets and shapes a hand', async () => {
    render(panel(withActor({ figure: 'mannequin', pose: { preset: 'wave', joints: { 'rightShoulder.spread': 80, 'rightElbow.bend': 100, 'head.yaw': 10 } } })));
    await userEvent.click(screen.getByRole('button', { name: /左右镜像/ }));
    await userEvent.click(screen.getByRole('button', { name: /复位/ }));
    await userEvent.click(within(screen.getByRole('group', { name: '右手手型' })).getByRole('button', { name: '握拳' }));

    expect(committed()[0]).toEqual({ op: 'set_pose', name: '林夏', preset: '', joints: { 'leftShoulder.spread': -80, 'leftElbow.bend': 100, 'head.yaw': -10 }, clip: '', clip_phase: 0 });
    expect(committed()[1]).toEqual({ op: 'set_pose', name: '林夏', preset: 'stand', joints: {}, clip: '', clip_phase: 0 });
    const fist = committed()[2].joints as Record<string, number>;
    expect(fist['rightHand.index.curl']).toBe(95);
    expect(fist['rightHand.thumb.curl']).toBe(60);
    expect(fist['rightElbow.bend']).toBe(100);
    expect(Object.keys(fist).filter(key => key.startsWith('leftHand.'))).toEqual([]);
  });

  it('writes to this shot only when asked, and always when the shot already poses the actor', async () => {
    const mannequin = withActor({ figure: 'mannequin' });
    const { rerender } = render(panel(mannequin));
    await userEvent.click(screen.getByLabelText('只改这一镜'));
    expect(onShotOnly).toHaveBeenCalledWith(true);

    rerender(panel(mannequin, { shotOnly: true }));
    await userEvent.click(screen.getByRole('button', { name: '坐姿' }));
    expect(committed()[0]).toMatchObject({ op: 'set_pose', name: '林夏', shot_id: 1, preset: 'sit' });

    const overridden: StagePlan = { ...mannequin, shots: [{ ...mannequin.shots[0], overrides: [{ name: '林夏', pose: { preset: 'bow', joints: { 'body.pitch': -46 } } }] }, mannequin.shots[1]] };
    rerender(panel(overridden, { shot: overridden.shots[0] }));
    expect((screen.getByLabelText('只改这一镜') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('只改这一镜') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole('button', { name: '鞠躬' }).getAttribute('aria-pressed')).toBe('true');
    await userEvent.click(screen.getByRole('button', { name: /清除本镜姿势/ }));
    expect(committed()[1]).toEqual({ op: 'set_pose', name: '林夏', shot_id: 1, preset: '', joints: {}, clip: '', clip_phase: 0 });
  });

  it('gives a skinned figure ten clips and a scrubbed phase', async () => {
    render(panel(withActor({ figure: 'humanoid' })));
    const select = screen.getByLabelText('动作片段') as HTMLSelectElement;
    expect([...select.options].map(option => option.textContent)).toEqual([
      '站立 · 站立待机', '站立 · 交谈手势', '移动 · 行走', '移动 · 慢跑', '蹲姿 · 蹲姿待机', '移动 · 蹲着前进', '坐姿 · 坐下', '坐姿 · 坐姿待机', '坐姿 · 坐姿交谈', '坐姿 · 站起',
    ]);
    expect(screen.queryByRole('group', { name: '预设姿势' })).toBeNull();

    await userEvent.selectOptions(select, 'human-sit-idle-v1');
    // The clip's posture rides as the preset: it is what the backend reads the projected height from.
    expect(committed()[0]).toEqual({ op: 'set_pose', name: '林夏', preset: 'sit', joints: {}, clip: 'human-sit-idle-v1', clip_phase: 0 });

    const phase = screen.getByRole('slider', { name: /^进度/ }) as HTMLInputElement;
    fireEvent.change(phase, { target: { value: '0.4' } });
    expect(onPreview.mock.calls[0][0]?.[0]).toMatchObject({ clip: 'human-idle-v1', clip_phase: 0.4 });
    fireEvent.pointerUp(phase);
    expect(committed()[1]).toMatchObject({ op: 'set_pose', clip: 'human-idle-v1', clip_phase: 0.4, preset: 'stand' });
  });

  it('keeps saved poses with the person: no task id in the requests, apply, replace and delete', async () => {
    render(panel(withActor({ figure: 'mannequin', pose: { preset: 'think', joints: { 'rightElbow.bend': 130 } } })));
    expect(await screen.findByText('持剑')).toBeTruthy();
    expect(String(fetchMock.mock.calls[0][0])).toBe('http://localhost:8000/api/director-desk/poses');

    await userEvent.click(screen.getByRole('button', { name: '应用 持剑' }));
    expect(committed()[0]).toEqual({ op: 'set_pose', name: '林夏', preset: '', joints: { 'rightElbow.bend': 70, 'rightHand.index.curl': 95 }, clip: '', clip_phase: 0 });

    await userEvent.click(screen.getByRole('button', { name: /保存为自定义姿势/ }));
    expect(await screen.findByText('先给姿势起个名字。')).toBeTruthy();
    await userEvent.type(screen.getByLabelText('姿势名称'), '托腮');
    await userEvent.click(screen.getByRole('button', { name: /保存为自定义姿势/ }));
    expect(await screen.findByText('已保存「托腮」。')).toBeTruthy();
    const save = fetchMock.mock.calls.find(call => (call[1] as RequestInit | undefined)?.method === 'POST')!;
    expect(String(save[0])).toBe('http://localhost:8000/api/director-desk/poses');
    expect(JSON.parse(String((save[1] as RequestInit).body))).toEqual({ name: '托腮', pose: { preset: 'think', joints: { 'rightElbow.bend': 130 }, clip: '', clip_phase: 0 } });
    expect(screen.getByRole('button', { name: '应用 托腮' })).toBeTruthy();
    expect((screen.getByLabelText('姿势名称') as HTMLInputElement).maxLength).toBe(40);

    await userEvent.click(screen.getByRole('button', { name: '删除 持剑' }));
    await waitFor(() => expect(screen.queryByText('持剑')).toBeNull());
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/api/director-desk/poses/p1') && (call[1] as RequestInit).method === 'DELETE')).toBe(true);
  });

  it('is read-only while the stage is locked', () => {
    render(panel(withActor({ figure: 'mannequin' }), { editable: false }));
    expect(screen.getByRole('button', { name: '坐姿' })).toHaveProperty('disabled', true);
    expect(screen.getByLabelText('左膝 弯曲')).toHaveProperty('disabled', true);
    expect(screen.getByRole('radio', { name: '蒙皮人形' })).toHaveProperty('disabled', true);
  });
});
