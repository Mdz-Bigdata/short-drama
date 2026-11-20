// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskResponse, WorkflowSnapshot } from './types';
import App from './App';

vi.mock('./features/storyboard/StoryboardWorkspace', () => ({
  StoryboardWorkspace: ({ onRegenerate }: { onRegenerate?: () => void }) => (
    <div>分镜工作区<button type="button" onClick={onRegenerate}>重跑分镜阶段</button></div>
  ),
}));
vi.mock('./features/writer/WriterAgentPageContainer', () => ({ WriterAgentPageContainer: () => <div>编剧工作区</div> }));

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

  it('stays on the director board for review once the director stage is finished', async () => {
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
    expect(await screen.findByText('已完成 1/8 步。接下来是第 2/8 步：编剧剧本创作。')).toBeTruthy();
    expect(screen.getByRole('button', { name: /1.总导演/ }).getAttribute('aria-current')).toBe('step');
    expect(screen.getByRole('button', { name: /2.编剧/ }).getAttribute('aria-current')).toBeNull();
  });

  it('keeps polling through a backend restart and shows why the stage stopped', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const running = task();
    running.currentStage = 1;
    running.status = 'running';
    running.chatHistory = [];
    running.workflow = { ...running.workflow!, mode: 'running', active_stage: 1, next_stage: 1,
      completed_stages: [], hint: '正在进行第 1/8 步：总导演策划。', event_id: 'running-1' };
    let snapshot: TaskResponse | null = running;
    mockFetch([running], url => {
      if (!url.endsWith('/task-a/status')) return undefined;
      if (!snapshot) return Promise.reject(new TypeError('Failed to fetch'));
      return response(snapshot);
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    expect(await screen.findByRole('button', { name: /1.总导演/, current: 'step' })).toBeTruthy();

    // The server goes away for a few polls while it reloads.
    snapshot = null;
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600 * 3); });
    expect(screen.queryByText(/流程状态暂时同步失败/)).toBeNull();

    const notice = '第 1/8 步：总导演策划执行到一半时服务重启，本轮被打断，未能完成。';
    snapshot = { ...running, status: 'interrupted',
      chatHistory: [{ id: 'interrupted-1', role: 'assistant', content: notice }],
      workflow: { ...running.workflow!, mode: 'paused', active_stage: null, next_stage: 1,
        hint: '已完成 0/8 步。接下来是第 1/8 步：总导演策划。', event_id: 'paused-1' } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600); });
    expect(await screen.findByText(notice)).toBeTruthy();
    expect(screen.getByRole('button', { name: /1.总导演/ }).getAttribute('aria-current')).toBe('step');
  });

  it('advances one stage per 继续 and holds each finished board for review', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const base = task();
    const stageNames = ['总导演策划', '编剧剧本创作', '角色设计师造型'];
    const at = (done: number, running: number | null): TaskResponse => ({
      ...base,
      currentStage: running ?? Math.max(1, done),
      status: running ? 'running' : 'idle',
      chatHistory: [],
      workflow: { ...base.workflow!, mode: running ? 'running' : 'ready', active_stage: running,
        next_stage: running ?? done + 1, completed_stages: Array.from({ length: done }, (_, i) => i + 1),
        hint: running ? `正在进行第 ${running}/8 步：${stageNames[running - 1]}。`
          : `已完成 ${done}/8 步。接下来是第 ${done + 1}/8 步：${stageNames[done]}。`,
        event_id: running ? `running-${running}` : `ready-${done + 1}` },
    });
    let snapshot = at(1, null);
    const sent: string[] = [];
    mockFetch([snapshot], (url, init) => {
      if (url.endsWith('/task-a/status')) return response(snapshot);
      if (!url.endsWith('/assistant')) return undefined;
      sent.push(JSON.parse(String(init?.body)).message);
      const stage = snapshot.workflow!.next_stage!;
      snapshot = at(stage - 1, stage);
      return response({ reply: snapshot.workflow!.hint, action: 'run_stage', stage, task: snapshot });
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    // Stage 1 is done: its board stays up for review until the user says 继续.
    expect(await screen.findByRole('button', { name: /1.总导演/, current: 'step' })).toBeTruthy();
    const tab = (stage: number) => screen.getByRole('button', { name: new RegExp(`^${stage}\\.`) });

    for (const stage of [2, 3]) {
      await user.type(screen.getByRole('textbox', { name: /发送给/ }), '继续{Enter}');
      await waitFor(() => expect(tab(stage).getAttribute('aria-current')).toBe('step'));
      snapshot = at(stage, null);
      await act(async () => { await vi.advanceTimersByTimeAsync(1_600 * 2); });
      expect(await screen.findByText(snapshot.workflow!.hint)).toBeTruthy();
      expect(tab(stage).getAttribute('aria-current')).toBe('step');
      expect(tab(stage + 1).getAttribute('aria-current')).toBeNull();
    }
    expect(sent).toEqual(['继续', '继续']);
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
      expect(JSON.parse(String(init?.body))).toEqual({ message: '/resume', context: expect.objectContaining({ stage: expect.any(Number) }) });
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

describe('App reports a project failure inside the project', () => {
  const refused = (status: number, detail: string): Response => {
    const body = { ok: false, status, json: async () => ({ detail }), clone: () => body } as unknown as Response;
    return body;
  };

  // drama_service.assistant_message stores the user message before the turn runs, so a turn that
  // is refused afterwards (402, 409, 500) has already left it in the chat history.
  function recordingServer(current: TaskResponse, refusal: () => Response | undefined) {
    const server = { stored: current };
    mockFetch([current], (url, init) => {
      if (url.endsWith('/task-a/status')) return response(server.stored);
      if (!url.endsWith('/assistant')) return undefined;
      const history = server.stored.chatHistory!;
      const message = JSON.parse(String(init?.body)).message as string;
      server.stored = { ...server.stored, chatHistory: [...history, { id: `u${history.length}`, role: 'user', content: message }] };
      const refusedWith = refusal();
      if (refusedWith) return refusedWith;
      server.stored = { ...server.stored, chatHistory: [...server.stored.chatHistory!, { id: `a${history.length}`, role: 'assistant', content: '已改成夜戏。' }] };
      return response({ reply: '已改成夜戏。', action: 'none', stage: null, task: server.stored });
    });
    return server;
  }

  it('explains a refused message beside the composer and keeps the recorded message once', async () => {
    const current = task();
    const server = recordingServer(current, () => refused(409, '当前阶段正在执行，请稍后再发。'));
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: /发送给/ });
    await user.type(input, '把第二场改成夜戏{Enter}');

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('当前阶段正在执行，请稍后再发。');
    expect(document.getElementById('workbench-chat-sidebar')!.contains(alert)).toBe(true);
    expect(screen.queryByText(/正在理解您的指令/)).toBeNull();
    // The server has the message: it stays in the history, and is not offered for a second send.
    expect(screen.getAllByText('把第二场改成夜戏')).toHaveLength(1);
    expect(input.value).toBe('');
    expect(server.stored.chatHistory!.filter(entry => entry.content === '把第二场改成夜戏')).toHaveLength(1);
  });

  it('hands the text back for a resend when the refused message was not recorded', async () => {
    const current = task();
    let refuse = true;
    mockFetch([current], url => {
      if (!url.endsWith('/assistant')) return undefined;
      if (refuse) return refused(404, '任务不存在');
      return response({ reply: '已改成夜戏。', action: 'none', stage: null, task: { ...current, chatHistory: [
        ...current.chatHistory!, { id: 'u2', role: 'user', content: '把第二场改成夜戏' }, { id: 'a2', role: 'assistant', content: '已改成夜戏。' },
      ] } });
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: /发送给/ });
    await user.type(input, '把第二场改成夜戏{Enter}');

    expect((await screen.findByRole('alert')).textContent).toContain('任务不存在');
    expect(screen.queryByText(/正在理解您的指令/)).toBeNull();
    // The message was not delivered: it is back in the composer, not in the history.
    expect(input.value).toBe('把第二场改成夜戏');
    expect(screen.queryByText('把第二场改成夜戏')).toBeNull();

    refuse = false;
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    expect(await screen.findByText('已改成夜戏。')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getAllByText('把第二场改成夜戏')).toHaveLength(1);
    expect(input.value).toBe('');
  });

  it('keeps the failed message on screen when something else was typed while it was sending', async () => {
    const current = task();
    let fail: (reason: Error) => void = () => undefined;
    mockFetch([current], url => url.endsWith('/assistant')
      ? new Promise<Response>((_, reject) => { fail = reject; }) : undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: /发送给/ });
    await user.type(input, '把第二场改成夜戏{Enter}');
    await user.type(input, '再加一场雨');
    await act(async () => { fail(new TypeError('Failed to fetch')); });

    expect((await screen.findByRole('alert')).textContent).toContain('发送消息失败');
    expect(screen.queryByText(/正在理解您的指令/)).toBeNull();
    expect(input.value).toBe('再加一场雨');
    expect(screen.getAllByText('把第二场改成夜戏')).toHaveLength(1);
  });

  it('leaves a half-typed message in the composer when a button sends the instruction', async () => {
    const current = task();
    let refuse = true;
    const server = recordingServer(current, () => refuse ? refused(500, '对话处理失败') : undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: /发送给/ });
    await user.type(input, '半句没写完的话');

    await user.click(screen.getAllByRole('button', { name: '继续制作第 2 集分镜' })[0]);
    expect((await screen.findByRole('alert')).textContent).toContain('对话处理失败');
    expect(input.value).toBe('半句没写完的话');

    refuse = false;
    await user.click(screen.getAllByRole('button', { name: '继续制作第 2 集分镜' })[0]);
    await screen.findByText('已改成夜戏。');
    expect(input.value).toBe('半句没写完的话');
    expect(server.stored.chatHistory!.filter(entry => entry.content === '半句没写完的话')).toHaveLength(0);
  });

  it('can be dismissed, and is not carried back to the lobby when the project closes', async () => {
    const current = task();
    mockFetch([current], url => url.endsWith('/assistant') ? Promise.reject(new TypeError('Failed to fetch')) : undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    await user.type(screen.getByRole('textbox', { name: /发送给/ }), '进度{Enter}');
    expect((await screen.findByRole('alert')).textContent).toContain('发送消息失败');
    await user.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByRole('alert')).toBeNull();

    await user.click(screen.getByRole('button', { name: '发送消息' }));
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: '关闭项目工作台' }));
    await screen.findByText('项目 task-a');
    expect(screen.queryByText(/发送消息失败/)).toBeNull();
    expect(document.querySelector('.error-banner')).toBeNull();
  });

  it('leaves an out-of-points refusal to the top-up notice instead of repeating it', async () => {
    const current = task();
    recordingServer(current, () => refused(402, '积分不足，请先充值。'));
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await screen.findByText(current.workflow!.hint);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: /发送给/ });
    await user.type(input, '把第二场改成夜戏{Enter}');
    await waitFor(() => expect(screen.queryByText(/正在理解您的指令/)).toBeNull());
    expect(screen.getAllByText('积分不足，请先充值。')).toHaveLength(1);
    expect(document.querySelector('.chat-sidebar__error')).toBeNull();
    // Recorded by the server before the refusal: shown once, and not sent again after the top-up.
    expect(screen.getAllByText('把第二场改成夜戏')).toHaveLength(1);
    expect(input.value).toBe('');
  });
});

describe('App storyboard rerun', () => {
  const storyboardTask = (assets: TaskResponse['assets']): TaskResponse => ({ ...task(), assets: { '4': [{ shot_id: 1 }], ...assets } });
  const sentMessages = (fetchMock: ReturnType<typeof mockFetch>) => fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith('/task-a/assistant'))
    .map(([, init]) => JSON.parse(String(init?.body)).message as string);

  it('asks before a rerun that would clear finished videos, audio or the film', async () => {
    const current = storyboardTask({ '5_shot_videos': { '1': '/media/shot-1.mp4' } });
    const fetchMock = mockFetch([current]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    const rerun = await screen.findByRole('button', { name: '重跑分镜阶段' });

    await user.click(rerun);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(String(confirm.mock.calls[0][0])).toContain('第 5 阶段及之后');
    expect(sentMessages(fetchMock)).toEqual([]);

    confirm.mockReturnValue(true);
    await user.click(rerun);
    await waitFor(() => expect(sentMessages(fetchMock)).toEqual(['重跑第 4 阶段']));
  });

  it('reruns straight away when nothing later exists yet', async () => {
    const fetchMock = mockFetch([storyboardTask({ '4_grid': '/media/grid.png' })]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await user.click(await screen.findByRole('button', { name: '重跑分镜阶段' }));

    await waitFor(() => expect(sentMessages(fetchMock)).toEqual(['重跑第 4 阶段']));
    expect(confirm).not.toHaveBeenCalled();
  });

  // Per-episode production: the server keeps the other episodes' clips and every finished film.
  const perEpisode = (assets: TaskResponse['assets']) => storyboardTask({
    '4_progress': { episodes: [{ number: 1 }, { number: 2 }] },
    '5': [{ shot_id: 1, scene_id: 'E1S01', video_url: '/media/e1.mp4' }],
    '6': { episode: 1 },
    '7': { episode: 1 },
    episode_cycle: { version: 1, episodes: { '1': { audio: { episode: 1 }, timeline: { clips: [] }, film: { final_video_url: '/media/film-1.mp4' } } } },
    ...assets,
  });
  const pressRerun = async (current: TaskResponse) => {
    const fetchMock = mockFetch([current]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目 task-a'));
    await user.click(await screen.findByRole('button', { name: '重跑分镜阶段' }));
    return { fetchMock, confirm };
  };

  it('does not ask in per-episode production when the episode in hand has nothing later', async () => {
    const { fetchMock, confirm } = await pressRerun(perEpisode({}));

    await waitFor(() => expect(sentMessages(fetchMock)).toEqual(['重跑第 4 阶段']));
    expect(confirm).not.toHaveBeenCalled();
  });

  it('names the episode whose videos go, and says the other episodes stay', async () => {
    const { fetchMock, confirm } = await pressRerun(perEpisode({
      '5': [{ shot_id: 1, scene_id: 'E1S01', video_url: '/media/e1.mp4' }, { shot_id: 1, scene_id: 'E2S01', video_url: '/media/e2.mp4' }],
    }));

    expect(confirm).toHaveBeenCalledTimes(1);
    const asked = String(confirm.mock.calls[0][0]);
    expect(asked).toContain('第 2 集已生成的视频、音频与剪辑会被清除');
    expect(asked).toContain('其他各集的视频和成片都保留');
    expect(asked).not.toContain('第 5 阶段及之后');
    expect(sentMessages(fetchMock)).toEqual([]);
  });

  it('looks at the episode the storyboard step will work on, not the first one without a film', async () => {
    // Steps run for every episode before the next step: episode 1 is boarded and filmed-in-part, episode 2 is the one
    // still to board, so a rerun touches episode 2 (nothing to lose) and leaves episode 1's clips alone.
    const { fetchMock, confirm } = await pressRerun(perEpisode({
      '4_progress': { episodes: [{ number: 1, complete: true }, { number: 2, complete: false }, { number: 3, complete: false }] },
      episode_cycle: { version: 1, episodes: {} },
    }));

    await waitFor(() => expect(sentMessages(fetchMock)).toEqual(['重跑第 4 阶段']));
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks about the promotion copy once every episode has its film', async () => {
    const { fetchMock, confirm } = await pressRerun(perEpisode({
      episode_cycle: { version: 1, episodes: {
        '1': { film: { final_video_url: '/media/film-1.mp4' } },
        '2': { film: { final_video_url: '/media/film-2.mp4' } },
      } },
      '8_publish': { title: '宣发标题' },
    }));

    expect(confirm).toHaveBeenCalledTimes(1);
    const asked = String(confirm.mock.calls[0][0]);
    expect(asked).toContain('各集成片都保留');
    expect(asked).toContain('宣发内容会被清除');
    expect(sentMessages(fetchMock)).toEqual([]);
  });
});
