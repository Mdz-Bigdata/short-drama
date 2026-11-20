// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskResponse } from './types';
import App from './App';

vi.mock('./features/platform/CapabilityCenter', () => ({ CapabilityCenter: () => <div>平台能力</div> }));

function task(patch: Partial<TaskResponse> = {}): TaskResponse {
  return {
    taskId: 'task-a', currentStage: 2, stageName: '编剧', status: 'idle',
    config: { titleSuggestion: '项目甲', directorStyle: 'realistic', shotStyle: 'cinematic', llmModel: 'test', imageModel: 'test', videoModel: 'test', ttsModel: 'test', oneClick: false },
    assets: {}, logs: {}, chatHistory: [],
    ...patch,
  };
}

const response = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => data }) as Response;

function mockFetch(tasks: () => TaskResponse[], intercept?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const result = intercept?.(url, init);
    if (result) return await result;
    if (url.endsWith('/api/auth/session')) return response({ authenticated: true, user: { user_id: 'admin', username: 'admin', role: 'admin' } });
    if (url.endsWith('/api/model-configurations')) return response({ items: [], globalDefaults: {} });
    if (url.endsWith('/api/drama/list')) {
      return response(tasks().map(({ taskId, currentStage, stageName, status, config }) => ({ taskId, currentStage, stageName, status, config })));
    }
    if (url.endsWith('/api/drama/skills')) return response([]);
    const selected = tasks().find(item => url.endsWith(`/api/drama/${item.taskId}/status`));
    if (selected) return response(selected);
    return response({ items: [], total: 0, episodes: [] });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const ideaBox = () => screen.findByPlaceholderText('由一个想法或故事开始...') as Promise<HTMLTextAreaElement>;
const chatBox = () => screen.findByRole('textbox', { name: /发送给 .+ 的消息/ }) as Promise<HTMLTextAreaElement>;

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('App lobby idea box', () => {
  it('does not leave the idea in the chat box of the project it created', async () => {
    const created = task({ taskId: 'task-new', config: { ...task().config, titleSuggestion: '雨夜追凶' } });
    let tasks: TaskResponse[] = [];
    mockFetch(() => tasks, url => {
      if (url.endsWith('/api/drama/create')) {
        tasks = [created];
        return response(created);
      }
      if (url.endsWith('/api/drama/task-new/assistant')) return response({ reply: '已开始', task: created });
      return undefined;
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(await ideaBox(), '雨夜追凶{Enter}');

    expect((await chatBox()).value).toBe('');
    await user.click(screen.getByRole('button', { name: '关闭项目工作台' }));
    expect((await ideaBox()).value).toBe('');
  });

  it('keeps a half-typed chat message out of the lobby and out of the next project', async () => {
    mockFetch(() => [task(), task({ taskId: 'task-b', config: { ...task().config, titleSuggestion: '项目乙' } })]);
    const user = userEvent.setup();
    render(<App />);

    await user.type(await ideaBox(), '下一部想拍的');
    await user.click(await screen.findByText('项目甲'));
    const chat = await chatBox();
    expect(chat.value).toBe('');
    await user.type(chat, '把第三场改成');
    await user.click(screen.getByRole('button', { name: '关闭项目工作台' }));

    expect((await ideaBox()).value).toBe('下一部想拍的');
    await user.click(await screen.findByText('项目乙'));
    expect((await chatBox()).value).toBe('');
  });
});

describe('App project cards', () => {
  it('waits for the list before saying there are no projects', async () => {
    let release: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>(resolve => { release = resolve; });
    mockFetch(() => [], url => url.endsWith('/api/drama/list') ? pending : undefined);
    render(<App />);

    await screen.findByText('断点续传项目大厅');
    expect(screen.queryByText('还没有项目')).toBeNull();
    release(response([]));
    expect(await screen.findByText('还没有项目')).toBeTruthy();
  });

  it('names each status in Chinese', async () => {
    mockFetch(() => [
      task({ status: 'idle' }),
      task({ taskId: 'task-b', status: 'awaiting_quality_review', config: { ...task().config, titleSuggestion: '项目乙' } }),
    ]);
    const { container } = render(<App />);

    await screen.findByText('项目乙');
    const chips = [...container.querySelectorAll('.project-card__status')].map(node => node.textContent);
    expect(chips).toEqual(['已暂停', '待质检']);
    expect(container.textContent).not.toMatch(/IDLE|QUALITY REVIEW/);
  });

  it('does not call a failed, interrupted or stopped project paused', async () => {
    const named = (taskId: string, status: TaskResponse['status']) => task({ taskId, status, config: { ...task().config, titleSuggestion: taskId } });
    mockFetch(() => [
      named('失败的', 'failed'), named('中断的', 'interrupted'), named('停止的', 'stopped'),
      named('待评审的', 'awaiting_council_review'), named('评审没过的', 'council_quality_failed'), named('暂停的', 'paused'),
    ]);
    const { container } = render(<App />);

    await screen.findByText('暂停的');
    const cards = [...container.querySelectorAll('.project-card')];
    expect(cards.map(card => card.querySelector('.project-card__status')?.textContent)).toEqual(['生成失败', '已中断', '已停止', '待评审', '评审未过', '已暂停']);
    // The line under the title repeats the chip, so the two cannot disagree.
    expect(cards.map(card => card.querySelector('.project-card__meta')?.textContent?.split(' - ')[1])).toEqual(['生成失败', '已中断', '已停止', '待评审', '评审未过', '已暂停']);
    expect(cards.map(card => card.classList.contains('is-failed'))).toEqual([true, true, false, false, true, false]);
  });

  it('says why a pause did not happen', async () => {
    mockFetch(() => [task({ status: 'running' })], url => url.endsWith('/api/drama/task-a/pause') ? response({ detail: '这一步正在写入，暂时不能暂停' }, false) : undefined);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '暂停' }));
    // Announced, and shown once beside the cards: the banner above the idea box may be scrolled away.
    const notice = await screen.findByRole('alert');
    expect(notice.textContent).toBe('这一步正在写入，暂时不能暂停');
    expect(notice.closest('.project-lobby')).not.toBeNull();
    expect(screen.getAllByText(/这一步正在写入，暂时不能暂停/)).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('says so when a resume cannot reach the server', async () => {
    mockFetch(() => [task()], url => {
      if (url.endsWith('/api/drama/task-a/resume')) throw new TypeError('Failed to fetch');
      return undefined;
    });
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '恢复' }));
    expect((await screen.findByRole('alert')).textContent).toBe('恢复项目失败，请稍后重试。');
  });

  it('takes the notice down when the next try works', async () => {
    let refuse = true;
    mockFetch(() => [task({ status: 'running' })], url => {
      if (!url.endsWith('/api/drama/task-a/pause')) return undefined;
      return refuse ? response({ detail: '这一步正在写入，暂时不能暂停' }, false) : response({ ok: true });
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '暂停' }));
    await screen.findByRole('alert');
    refuse = false;
    await user.click(screen.getByRole('button', { name: '暂停' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('removes a deleted project without a second dialog', async () => {
    let tasks = [task()];
    mockFetch(() => tasks, (url, init) => {
      if (url.endsWith('/api/drama/task-a') && init?.method === 'DELETE') {
        tasks = [];
        return response({ deleted: true });
      }
      return undefined;
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '删除任务项目' }));
    await waitFor(() => expect(screen.queryByText('项目甲')).toBeNull());
    expect(alert).not.toHaveBeenCalled();
  });
});

describe('App create-project dialog', () => {
  const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('button', { name: '创建新项目' }));
    const dialog = await screen.findByRole('dialog');
    return { dialog, title: within(dialog).getByPlaceholderText(/例如：/) as HTMLInputElement };
  };
  const createCalls = (fetchMock: ReturnType<typeof mockFetch>) => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/drama/create'));

  it('asks for a title inside the dialog instead of a browser alert', async () => {
    const fetchMock = mockFetch(() => []);
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<App />);

    const { dialog, title } = await openDialog(user);
    await user.click(within(dialog).getByRole('button', { name: '立即创建项目' }));

    expect(within(dialog).getByRole('alert').textContent).toBe('请输入短剧选题名称！');
    expect(alert).not.toHaveBeenCalled();
    expect(createCalls(fetchMock)).toHaveLength(0);

    await user.type(title, '雨');
    expect(within(dialog).queryByRole('alert')).toBeNull();
  });

  it('comes back with the reason and what was typed when the project could not be created', async () => {
    const created = task({ taskId: 'task-new', config: { ...task().config, titleSuggestion: '雨夜追凶' } });
    let tasks: TaskResponse[] = [];
    let refuse = true;
    const fetchMock = mockFetch(() => tasks, url => {
      if (url.endsWith('/api/drama/create')) {
        if (refuse) return response({ detail: '当前套餐的项目数已满' }, false);
        tasks = [created];
        return response(created);
      }
      if (url.endsWith('/api/drama/task-new/assistant')) return response({ reply: '已开始', task: created });
      return undefined;
    });
    const user = userEvent.setup();
    render(<App />);

    const first = await openDialog(user);
    await user.type(first.title, '雨夜追凶');
    await user.click(within(first.dialog).getByRole('button', { name: '立即创建项目' }));

    const dialog = await screen.findByRole('dialog');
    expect((await within(dialog).findByRole('alert')).textContent).toBe('当前套餐的项目数已满');
    expect((within(dialog).getByPlaceholderText(/例如：/) as HTMLInputElement).value).toBe('雨夜追凶');
    // Said once, in the dialog: not a second time behind it.
    expect(screen.getAllByText(/当前套餐的项目数已满/)).toHaveLength(1);

    refuse = false;
    await user.click(within(dialog).getByRole('button', { name: '立即创建项目' }));
    await chatBox();
    expect(createCalls(fetchMock)).toHaveLength(2);
    expect(JSON.parse(String(createCalls(fetchMock)[1][1]?.body)).titleSuggestion).toBe('雨夜追凶');
  });

  it('sends the chosen audience for a serial and hides the choice for a short film', async () => {
    const created = task({ taskId: 'task-new', config: { ...task().config, titleSuggestion: '回家' } });
    let tasks: TaskResponse[] = [];
    const fetchMock = mockFetch(() => tasks, url => {
      if (url.endsWith('/api/drama/create')) {
        tasks = [created];
        return response(created);
      }
      if (url.endsWith('/api/drama/task-new/assistant')) return response({ reply: '已开始', task: created });
      return undefined;
    });
    const user = userEvent.setup();
    render(<App />);

    const { dialog, title } = await openDialog(user);
    await user.selectOptions(within(dialog).getByLabelText('创作类型'), 'film');
    expect(within(dialog).queryByLabelText('目标用户')).toBeNull();
    await user.selectOptions(within(dialog).getByLabelText('创作类型'), 'drama');
    await user.selectOptions(within(dialog).getByLabelText('目标用户'), 'female');
    await user.selectOptions(within(dialog).getByLabelText('年龄段'), 'senior');
    await user.type(title, '回家');
    await user.click(within(dialog).getByRole('button', { name: '立即创建项目' }));
    await chatBox();

    expect(JSON.parse(String(createCalls(fetchMock)[0][1]?.body)).targetAudience).toEqual({ lean: 'female', age: 'senior' });
  });

  it('reopens with the reason when the server cannot be reached', async () => {
    mockFetch(() => [], url => {
      if (url.endsWith('/api/drama/create')) throw new TypeError('Failed to fetch');
      return undefined;
    });
    const user = userEvent.setup();
    render(<App />);

    const first = await openDialog(user);
    await user.type(first.title, '雨夜追凶');
    await user.click(within(first.dialog).getByRole('button', { name: '立即创建项目' }));

    const dialog = await screen.findByRole('dialog');
    expect((await within(dialog).findByRole('alert')).textContent).toBe('无法连接至后端，请先确保后端运行中。');
    expect((within(dialog).getByPlaceholderText(/例如：/) as HTMLInputElement).value).toBe('雨夜追凶');
  });
});

describe('App account menu', () => {
  it('opens from the keyboard and hands focus back to the avatar on Escape', async () => {
    mockFetch(() => [task()]);
    const user = userEvent.setup();
    render(<App />);

    const avatar = await screen.findByRole('button', { name: '账号菜单' });
    avatar.focus();
    await user.keyboard('{Enter}');
    expect(avatar.getAttribute('aria-expanded')).toBe('true');
    await user.tab();
    expect(document.activeElement?.textContent).toBe('用户中心');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull();
    expect(document.activeElement).toBe(avatar);
  });
});

describe('App sign-out', () => {
  // user-event moves the pointer without a relatedTarget, which React reads as leaving the
  // window and the hover menu closes under the click; a plain click event goes straight to it.
  async function signOut(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: '账号菜单' }));
    fireEvent.click(await screen.findByRole('button', { name: '退出登录' }));
  }

  it('says so when signing out fails and stays signed in', async () => {
    mockFetch(() => [task()], url => url.endsWith('/api/auth/logout') ? response({ detail: 'x' }, false) : undefined);
    const user = userEvent.setup();
    render(<App />);

    await signOut(user);
    expect(await screen.findByText(/退出登录失败，请重试。/)).toBeTruthy();
    expect(screen.getByText('项目甲')).toBeTruthy();
  });

  it('does not show the last account its projects to whoever signs in next', async () => {
    let signedOut = false;
    let release: (value: Response) => void = () => undefined;
    const nextList = new Promise<Response>(resolve => { release = resolve; });
    mockFetch(() => [task()], url => {
      if (url.endsWith('/api/auth/logout')) {
        signedOut = true;
        return response({ ok: true });
      }
      if (url.endsWith('/api/auth/login_password')) return response({ user: { user_id: 'other', username: 'other', role: 'user' } });
      if (signedOut && url.endsWith('/api/drama/list')) return nextList;
      return undefined;
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(await ideaBox(), '上一个人没写完的想法');
    await signOut(user);
    await user.type(await screen.findByPlaceholderText('请输入绑定的手机号或邮箱'), 'other@example.test');
    await user.type(screen.getByPlaceholderText('请输入您的密码'), 'fixture-pass');
    await user.click(screen.getByRole('button', { name: '立即登录' }));

    await screen.findByText('断点续传项目大厅');
    expect(screen.queryByText('项目甲')).toBeNull();
    expect((await ideaBox()).value).toBe('');
    expect(screen.queryByText('还没有项目')).toBeNull();
    expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull();
    release(response([]));
    expect(await screen.findByText('还没有项目')).toBeTruthy();
  });
});
