// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { StageDirectorState } from '../directorApi';
import { DirectorPanel } from './DirectorPanel';

const BASE = 'http://localhost:8000/api/drama/t1/director-desk/scenes/E1S01';
const MEASURED = { score: 80, errors: 0, warnings: 1, failing: [], notes: [] };

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

function candidate(plan: StagePlan, id: string, source: 'model' | 'rules', score: number, title: string) {
  return { id, title, source, rationale: `${title}的理由`, score, measured: { ...MEASURED, score }, errors: [], plan };
}

describe('DirectorPanel', () => {
  const fetchMock = vi.fn();
  const plan = PLAN;
  let view: StageDirectorState;
  const onCommit = vi.fn();
  const onPlanChanged = vi.fn();
  const onSelect = vi.fn();

  const answers = (routes: Record<string, (body: unknown) => unknown>) => {
    fetchMock.mockImplementation((url: string, options: RequestInit = {}) => {
      const key = `${options.method ?? 'GET'} ${String(url).replace(BASE, '')}`;
      if (key === 'GET /director') return json(view);
      if (String(url).endsWith('/api/director-desk/kits')) {
        return json({ kits: [
          { id: 'desk', name: '书桌', group: '桌台柜架', kind: 'furniture', size: [1.3, 0.65, 0.75], aliases: [] },
          { id: 'sedan', name: '轿车', group: '车船', kind: 'furniture', size: [1.8, 4.5, 1.45], aliases: [] },
        ] });
      }
      const route = routes[key];
      if (!route) return json({ detail: `unexpected ${key}` }, 500);
      const body = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
      const result = route(body);
      return result instanceof Promise ? result : json(result);
    });
  };

  const show = (over: Partial<Parameters<typeof DirectorPanel>[0]> = {}) => render(
    <DirectorPanel
      taskId="t1" sceneId="E1S01" plan={plan} shotId={2} selection={[]} editable saving={false}
      dropPoint={() => [1, 2]} onCommit={onCommit} onPlanChanged={onPlanChanged} onSelect={onSelect} {...over}
    />,
  );

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    view = {
      chat: [], snapshots: [], candidates: [], measured: MEASURED, planner: 'rules', planner_note: '', pipeline_planner: 'model',
    };
    [fetchMock, onCommit, onPlanChanged, onSelect].forEach(mock => mock.mockReset());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('plans, marks the recommendation and only touches the stage when one is adopted', async () => {
    const adopted: unknown[] = [];
    answers({
      'POST /director/plan': () => ({
        candidates: [candidate(plan, 'model-1', 'model', 88, '隔案对峙'), candidate(plan, 'rules', 'rules', 92, '规则基线')],
        recommended: 'model-1', used_model: true, note: '', current: MEASURED,
      }),
      'POST /director/adopt': body => { adopted.push(body); return { plan }; },
    });
    show();
    await screen.findByText('80');
    await userEvent.type(screen.getByLabelText('规划的额外要求'), '压迫感');
    await userEvent.click(screen.getByRole('button', { name: /开始规划/ }));

    const list = await screen.findByRole('list', { name: '调度方案' });
    const cards = within(list).getAllByRole('listitem');
    expect(within(cards[0]).getByText('推荐')).toBeTruthy();
    expect(within(cards[0]).getByText('隔案对峙的理由')).toBeTruthy();
    expect(within(cards[1]).queryByText('推荐')).toBeNull();
    expect(within(cards[1]).getByText('不用模型')).toBeTruthy();
    expect(onPlanChanged).not.toHaveBeenCalled();
    const request = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/director/plan'));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ base_revision: plan.revision, count: 3, goal: '压迫感' });

    await userEvent.click(within(cards[0]).getByRole('button', { name: '采用这版' }));
    await waitFor(() => expect(onPlanChanged).toHaveBeenCalledTimes(1));
    expect(adopted).toEqual([{ base_revision: plan.revision, candidate_id: 'model-1' }]);
    expect(screen.queryByRole('list', { name: '调度方案' })).toBeNull();
  });

  it('says so when the model gave nothing and only the rule plan is on offer', async () => {
    answers({
      'POST /director/plan': () => ({
        candidates: [candidate(plan, 'rules', 'rules', 90, '规则基线')], recommended: 'rules', used_model: false,
        note: '模型没有给出可用的方案', current: MEASURED,
      }),
    });
    show();
    await screen.findByText('80');
    await userEvent.click(screen.getByRole('button', { name: /开始规划/ }));
    expect(await screen.findByText('模型没有给出可用的方案')).toBeTruthy();
  });

  it('sends the message with the chosen scope, then shows what changed and can take it back', async () => {
    const chats: unknown[] = [];
    const reverted: unknown[] = [];
    answers({
      'POST /director/chat': body => {
        chats.push(body);
        view = {
          ...view,
          snapshots: [{ id: 's1', label: '往左', at: '', revision: plan.revision }],
          chat: [
            { role: 'user', text: '林夏往左' },
            {
              role: 'assistant', text: '挪好了', snapshot_id: 's1', compare: '评分 80 → 85（+5.0）',
              changed: { actors: ['林夏'], pieces_added: ['长案'], pieces_changed: [], pieces_removed: ['旧凳'], cameras: ['cam-01'] },
              errors: ['第 2 个操作 flying：未知操作'],
            },
          ],
        };
        return { message: view.chat[1], changed: true, measured: MEASURED, failing: [] };
      },
      'POST /director/revert': body => {
        reverted.push(body);
        view = { ...view, snapshots: [] };
        return { plan };
      },
    });
    show({ selection: [{ kind: 'actor', name: '林夏' }] });
    await screen.findByText('80');
    await userEvent.type(screen.getByLabelText('对 AI 导演说'), '林夏往左');
    await userEvent.click(screen.getByRole('checkbox', { name: /只改选中/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: /只改第 2 镜/ }));
    await userEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('挪好了')).toBeTruthy();
    expect(chats).toEqual([{ base_revision: plan.revision, message: '林夏往左', names: ['林夏'], shot_id: 2 }]);
    expect(onPlanChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByText('评分 80 → 85（+5.0）')).toBeTruthy();
    expect(screen.getByText('移除了：旧凳')).toBeTruthy();
    expect(screen.getByText('1 个操作没有生效')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: '长案' }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'landmark', name: '长案' });
    await userEvent.click(screen.getByRole('button', { name: '机位 cam-01' }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'camera', id: 'cam-01' });

    await userEvent.click(screen.getByRole('button', { name: '撤销这一步' }));
    await waitFor(() => expect(reverted).toEqual([{ base_revision: plan.revision, snapshot_id: 's1' }]));
    expect(onPlanChanged).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByRole('button', { name: '撤销这一步' })).toBeNull());
  });

  it('does not reload the stage for an answer that changed nothing and shows a failure in words', async () => {
    let attempt = 0;
    answers({
      'POST /director/chat': () => {
        attempt += 1;
        if (attempt === 1) return json({ detail: '模型没有返回结果，舞台没有改动' }, 422);
        view = { ...view, chat: [{ role: 'assistant', text: '林夏在左边' }] };
        return { message: view.chat[0], changed: false, measured: MEASURED, failing: [] };
      },
    });
    show();
    await screen.findByText('80');
    await userEvent.type(screen.getByLabelText('对 AI 导演说'), '谁在左边');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    expect((await screen.findByRole('alert')).textContent).toContain('模型没有返回结果');
    expect((screen.getByLabelText('对 AI 导演说') as HTMLTextAreaElement).value).toBe('谁在左边');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    expect(await screen.findByText('林夏在左边')).toBeTruthy();
    expect(onPlanChanged).not.toHaveBeenCalled();
  });

  it('optimises without a message and holds everything while a save is in flight', async () => {
    const asked: unknown[] = [];
    answers({
      'POST /director/optimize': body => {
        asked.push(body);
        return { message: { role: 'assistant', text: '好了' }, changed: true, measured: MEASURED, failing: [] };
      },
    });
    const { rerender } = show({ saving: true });
    await screen.findByText('80');
    expect((screen.getByRole('button', { name: /自动优化/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: /开始规划/ }) as HTMLButtonElement).disabled).toBe(true);
    rerender(
      <DirectorPanel
        taskId="t1" sceneId="E1S01" plan={plan} shotId={2} selection={[]} editable saving={false}
        dropPoint={() => [1, 2]} onCommit={onCommit} onPlanChanged={onPlanChanged} onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /自动优化/ }));
    await waitFor(() => expect(asked).toHaveLength(1));
    expect(onPlanChanged).toHaveBeenCalled();
  });

  it('places a library model and a written one as ordinary undoable edits', async () => {
    answers({
      'POST /models/propose': () => ({
        name: '牛车', kind: 'furniture', kit: '', size: [1.6, 3, 2], summary: '木轮顶棚', dropped: 1, model: 'm',
        parts: [{ shape: 'box', center: [0, 0.5, 0], size: [1, 1, 1], tone: 'dark' }],
      }),
    });
    show();
    await screen.findByText('80');
    await userEvent.click(screen.getByText('建模'));
    await userEvent.click(await screen.findByRole('tab', { name: '车船' }));
    await userEvent.click(screen.getByRole('button', { name: '轿车' }));
    expect(onCommit).toHaveBeenLastCalledWith(expect.objectContaining({
      barrier: true, operations: [{ op: 'add_landmark', name: '轿车', kit: 'sedan', kind: 'furniture', position: [1, 2], yaw_deg: 0 }],
    }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'landmark', name: '轿车' });

    await userEvent.type(screen.getByLabelText('要搭的东西'), '唐代牛车');
    await userEvent.click(screen.getByRole('button', { name: '搭建' }));
    expect(await screen.findByText('有 1 块字段不完整，已略去。')).toBeTruthy();
    expect(onCommit).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '放到舞台上' }));
    expect(onCommit).toHaveBeenLastCalledWith(expect.objectContaining({
      operations: [expect.objectContaining({ op: 'add_landmark', name: '牛车', size: [1.6, 3, 2], fitted_parts: expect.any(Array) })],
    }));
  });

  it('builds a set from words and offers the selected piece as a file', async () => {
    const piece = plan.landmarks[0];
    answers({
      'POST /blockout/describe': () => ({
        summary: '客栈', extent_m: null, reference_camera: null, dropped: 0, model: 'm',
        pieces: [{ name: '柜台', kind: 'furniture', shape: 'box', center: [0, -3], size: [2, 0.6, 1], yaw_deg: 0, elevation_m: 0, color: '', kit: 'counter', parts: [] }],
      }),
    });
    show({ selection: [{ kind: 'landmark', name: piece.name }] });
    await screen.findByText('80');
    await userEvent.click(screen.getByText('建模'));
    await userEvent.type(screen.getByLabelText('场景描述'), '客栈大堂');
    await userEvent.click(screen.getByRole('button', { name: '搭场景' }));
    await userEvent.click(await screen.findByRole('button', { name: '铺到舞台上' }));
    expect(onCommit).toHaveBeenCalledWith(expect.objectContaining({ operations: [expect.objectContaining({ op: 'apply_blockout', replace: true })] }));
    const link = screen.getByRole('link', { name: new RegExp(`导出「${piece.name}」为 GLB`) }) as HTMLAnchorElement;
    expect(link.href).toContain(`/models/${piece.id}.glb`);
  });

  it('turns the pipeline planner off and back', async () => {
    const modes: unknown[] = [];
    fetchMock.mockImplementation((url: string, options: RequestInit = {}) => {
      if (String(url).endsWith('/planner')) {
        modes.push(JSON.parse(String(options.body)));
        return json({ pipeline_planner: 'rules' });
      }
      return String(url).endsWith('/kits') ? json({ kits: [] }) : json(view);
    });
    show();
    await screen.findByText('80');
    const toggle = screen.getByRole('checkbox', { name: /生成分镜时也让模型/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    await userEvent.click(toggle);
    await waitFor(() => expect(modes).toEqual([{ mode: 'rules' }]));
    await waitFor(() => expect(toggle.checked).toBe(false));
  });
});
