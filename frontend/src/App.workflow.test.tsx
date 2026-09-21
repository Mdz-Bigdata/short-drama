// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskResponse, WorkflowSnapshot } from './types';
import App from './App';

vi.mock('./features/storyboard/StoryboardWorkspace', () => ({ StoryboardWorkspace: () => <div>分镜工作区</div> }));

function task(id = 'task-a'): TaskResponse {
  const workflow: WorkflowSnapshot = {
    stages: Array.from({ length: 8 }, (_, i) => ({ stage: i + 1, label: `Agent ${i + 1}`, state: i < 3 ? 'complete' : 'pending', missing: [], guidance: '按顺序继续' })),
    next_stage: 4, active_stage: null, completed_stages: [1, 2, 3], production_complete: false,
    release_ready: false, mode: 'ready', hint: `${id}：第 4 阶段仍有分镜未完成，请继续第 2 集。`, event_id: 'partial-4',
    actions: [{ kind: 'continue', label: '继续制作第 2 集分镜', message: '继续' }],
  };
  return {
    taskId: id, currentStage: 4, stageName: '分镜师分镜拆解', status: 'idle',
    config: { titleSuggestion: `项目 ${id}`, directorStyle: 'realistic', shotStyle: 'cinematic', llmModel: 'test', imageModel: 'test', videoModel: 'test', ttsModel: 'test', oneClick: false },
    assets: {}, logs: {}, workflow,
    chatHistory: [{ id: `${id}-u`, role: 'user', content: `${id}：之前请保持古装风格` }, { id: `${id}-a`, role: 'assistant', content: `${id}：已保留古装设置` }],
  };
}

const response = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
function mockFetch(tasks: TaskResponse[], intercept?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const result = intercept?.(url, init);
    if (result) return await result;
    if (url.endsWith('/api/auth/session')) return response({ authenticated: true, user: { user_id: 'admin', username: 'admin', role: 'admin' } });
    if (url.endsWith('/api/model-configurations')) return response({ items: [], globalDefaults: {} });
    if (url.endsWith('/api/drama/list')) return response(tasks.map(item => ({
      taskId: item.taskId, currentStage: item.currentStage, stageName: item.stageName,
      status: item.status, config: item.config,
    })));
    if (url.endsWith('/api/drama/skills')) return response([]);
    const selected = tasks.find(item => url.endsWith(`/api/drama/${item.taskId}/status`));
    if (selected) return response(selected);
    return response({ items: [], total: 0 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('App follows the server workflow', () => {
  it('receives every durable stage transition even when several stages finish between polls', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const current = task();
    current.status = 'running';
    current.workflow = { ...current.workflow!, mode: 'running', active_stage: 4 };
    let snapshot = current;
    mockFetch([current], url => url.endsWith('/task-a/status') ? response(snapshot) : undefined);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText('task-a：已保留古装设置');
    const events = [4, 5, 6].map(stage => ({
      id: `stage-${stage}`, role: 'assistant' as const, content: `第 ${stage}/8 步产物已生成，按顺序继续。`,
    }));
    snapshot = { ...current, currentStage: 7, chatHistory: [...current.chatHistory!, ...events],
      workflow: { ...current.workflow!, active_stage: 7, next_stage: 7, event_id: 'running-7' } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    for (const event of events) expect(await screen.findByText(event.content)).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    for (const event of events) expect(screen.getAllByText(event.content)).toHaveLength(1);
  });

  it('opens the writer agent as soon as the director stage is finished', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running = task();
    running.currentStage = 1;
    running.status = 'running';
    running.workflow = { ...running.workflow!, mode: 'running', active_stage: 1, next_stage: 1,
      completed_stages: [], hint: '正在进行第 1/8 步：总导演策划。', event_id: 'running-1' };
    let snapshot = running;
    mockFetch([running], url => url.endsWith('/task-a/status') ? response(snapshot) : undefined);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    expect(await screen.findByRole('button', { name: /1.总导演/, current: 'step' })).toBeTruthy();

    // The director stage finished; current_stage stays 1 until stage 2 is claimed.
    snapshot = { ...running, status: 'idle', workflow: { ...running.workflow!, mode: 'ready',
      active_stage: null, next_stage: 2, completed_stages: [1],
      hint: '已完成 1/8 步。接下来是第 2/8 步：编剧剧本创作。', event_id: 'ready-2' } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    expect(await screen.findByRole('button', { name: /2.编剧/, current: 'step' })).toBeTruthy();
  });

  it('never moves the board past an agent whose assets are still missing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const current = task();
    current.currentStage = 3;
    current.status = 'running';
    current.workflow = { ...current.workflow!, mode: 'running', active_stage: 3, next_stage: 3,
      completed_stages: [1, 2], hint: '正在进行第 3/8 步：角色设计师造型。', event_id: 'running-3' };
    let snapshot = current;
    mockFetch([current], url => url.endsWith('/task-a/status') ? response(snapshot) : undefined);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    expect(await screen.findByRole('button', { name: /3.角色/, current: 'step' })).toBeTruthy();

    // 这一轮跑完了，但五视图没出齐，服务端仍然把下一步指回第 3 步。
    snapshot = { ...current, status: 'failed', workflow: { ...current.workflow!, mode: 'blocked',
      active_stage: null, next_stage: 3, completed_stages: [1, 2],
      hint: '已完成 2/8 步。接下来是第 3/8 步：角色设计师造型。', event_id: 'blocked-3' } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    expect(screen.getByRole('button', { name: /3.角色/ }).getAttribute('aria-current')).toBe('step');
    expect(screen.getByRole('button', { name: /4.分镜/ }).getAttribute('aria-current')).toBeNull();
  });

  it('restores dialogue and continues incomplete stage 4 through the assistant, not stage 5', async () => {
    const current = task();
    const fetchMock = mockFetch([current], (url, init) => {
      if (!url.endsWith('/assistant')) return;
      expect(JSON.parse(String(init?.body))).toEqual({ message: '/resume' });
      return response({ reply: '已继续第 4 阶段。', action: 'run_stage', stage: 4, task: {
        ...current,
        workflow: { ...current.workflow, mode: 'running', active_stage: 4, event_id: 'running-4' },
        chatHistory: [...current.chatHistory!, { id: 'u2', role: 'user', content: '/resume' }, { id: 'a2', role: 'assistant', content: '已继续第 4 阶段。' }],
      } });
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    expect(await screen.findByText('task-a：之前请保持古装风格')).toBeTruthy();
    expect(await screen.findByText(current.workflow!.hint)).toBeTruthy();
    expect(screen.queryByRole('region', { name: '八大 Agent 流程引导' })).toBeNull();
    await user.type(screen.getByRole('textbox', { name: /发送给/ }), '/');
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(await screen.findByText('已继续第 4 阶段。')).toBeTruthy();
    expect(screen.getAllByText('/resume')).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/next?'))).toBe(false);
    expect(screen.queryByText(/资产已生成并通过质检/)).toBeNull();
  });

  it('does not let a late response from a closed project replace the current dialogue', async () => {
    const a = task('task-a');
    const b = task('task-b');
    let resolveA!: (value: Response) => void;
    const deferredA = new Promise<Response>(resolve => { resolveA = resolve; });
    const fetchMock = mockFetch([a, b], url => url.endsWith('/task-a/status') ? deferredA : undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/task-a/status'))).toBe(true));
    await user.click(screen.getByRole('button', { name: '关闭项目工作台' }));
    await user.click(await screen.findByText('项目 task-b'));
    expect(await screen.findByText('task-b：之前请保持古装风格')).toBeTruthy();
    await act(async () => { resolveA(response(a)); await deferredA; });
    expect(screen.queryByText('task-a：之前请保持古装风格')).toBeNull();
    expect(screen.getByText(b.workflow!.hint)).toBeTruthy();
  });

  it('applies a slow status response even when a newer poll is still in flight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const current = task();
    const pending: Array<(value: Response) => void> = [];
    mockFetch([{ ...current, status: 'running' }], url => {
      if (url.endsWith('/task-a/status')) return new Promise<Response>(resolve => { pending.push(resolve); });
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    expect(pending).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    expect(pending.length).toBeGreaterThan(1);
    await act(async () => { pending[0](response(current)); });
    expect(await screen.findByText(current.workflow!.hint)).toBeTruthy();
    await act(async () => { pending.slice(1).forEach(resolve => resolve(response(current))); });
    expect(screen.getAllByText(current.workflow!.hint)).toHaveLength(1);
  });

  it('keeps the new chat request locked when an old reply arrives after reopening the same project', async () => {
    const current = task();
    const pending: Array<(value: Response) => void> = [];
    mockFetch([current], url => url.endsWith('/assistant')
      ? new Promise<Response>(resolve => { pending.push(resolve); }) : undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    await user.type(screen.getByRole('textbox', { name: /发送给/ }), '进度');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    expect(pending).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: '关闭项目工作台' }));
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    await user.type(screen.getByRole('textbox', { name: /发送给/ }), '进度');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    expect(pending).toHaveLength(2);
    await user.type(screen.getByRole('textbox', { name: /发送给/ }), '继续');
    await act(async () => { pending[0](response({
      reply: '过期回复不应显示', action: 'none', stage: null,
      task: { ...current, chatHistory: [{ id: 'old-reply', role: 'assistant', content: '过期回复不应显示' }] },
    })); });
    expect(screen.queryByText('过期回复不应显示')).toBeNull();
    expect(screen.getByRole('button', { name: '发送消息' }).hasAttribute('disabled')).toBe(true);
    await act(async () => { pending[1](response({
      reply: '这是当前回复', action: 'none', stage: null,
      task: { ...current, chatHistory: [...current.chatHistory!, { id: 'current-reply', role: 'assistant', content: '这是当前回复' }] },
    })); });
    expect(await screen.findByText('这是当前回复')).toBeTruthy();
    expect(screen.getByRole('button', { name: '发送消息' }).hasAttribute('disabled')).toBe(false);
  });
});
