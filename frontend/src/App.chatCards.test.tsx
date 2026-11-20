// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskResponse, WorkflowSnapshot } from './types';
import App from './App';

function task(patch: Partial<TaskResponse> = {}): TaskResponse {
  const workflow: WorkflowSnapshot = {
    stages: Array.from({ length: 8 }, (_, i) => ({ stage: i + 1, label: `Agent ${i + 1}`, state: i < 3 ? 'complete' : 'pending', missing: [], guidance: '' })),
    next_stage: 4, active_stage: null, completed_stages: [1, 2, 3], production_complete: false,
    release_ready: false, mode: 'ready', hint: '接下来是第 4/8 步。', event_id: 'ready-4', actions: [],
  };
  return {
    taskId: 'task-a', currentStage: 3, stageName: '角色', status: 'idle',
    config: { titleSuggestion: '项目甲', directorStyle: 'realistic', shotStyle: 'cinematic', llmModel: 'test', imageModel: 'test', videoModel: 'test', ttsModel: 'test', oneClick: false },
    assets: {}, logs: {}, workflow,
    chatHistory: [
      { id: 'u1', role: 'user', content: '把第1场的内侍往后挪' },
      {
        id: 'a1', role: 'assistant', content: '内侍往后退了两步。',
        ui_actions: [{ type: 'stage_changed', scene_id: 'E1S01', revision: 5, snapshot_id: 'snap1', summary: '助手：内侍后退', failing_checks: [], changed: { actors: ['内侍'], pieces_added: [], pieces_changed: [], pieces_removed: [], cameras: [] } }],
      },
    ],
    ...patch,
  };
}

const response = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => data }) as Response;

function mockFetch(current: () => TaskResponse, intercept?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const result = intercept?.(url, init);
    if (result) return result;
    if (url.endsWith('/api/auth/session')) return response({ authenticated: true, user: { user_id: 'admin', username: 'admin', role: 'admin' } });
    if (url.endsWith('/api/model-configurations')) return response({ items: [], globalDefaults: {} });
    if (url.endsWith('/api/drama/list')) {
      const { taskId, currentStage, stageName, status, config } = current();
      return response([{ taskId, currentStage, stageName, status, config }]);
    }
    if (url.endsWith('/api/drama/skills')) return response([]);
    if (url.endsWith('/api/drama/task-a/status')) return response(current());
    return response({ items: [], total: 0, episodes: [] });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('App sidebar cards', () => {
  it('rebuilds a stored stage change as a card whose undo restores the step without the model', async () => {
    const fetchMock = mockFetch(() => task(), url => (
      url.endsWith('/director-desk/scenes/E1S01/director/restore') ? response({ restored: 'snap1' }) : undefined
    ));
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目甲'));

    const sidebar = await screen.findByText('内侍往后退了两步。');
    const bubble = sidebar.closest('.chat-bubble') as HTMLElement;
    expect(within(bubble).getByText(/舞台已改/)).toBeTruthy();
    await user.click(within(bubble).getByRole('button', { name: '撤销这一步' }));

    await waitFor(() => {
      const sent = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/director/restore'));
      expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ snapshot_id: 'snap1' });
    });
    expect(await screen.findByText('已撤销 E1S01 的这一步舞台改动。')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/assistant'))).toBe(false);
  });

  it('keeps only the latest proposal confirmable', async () => {
    mockFetch(() => task({
      chatHistory: [
        { id: 'u1', role: 'user', content: '优化第1集所有场' },
        { id: 'a1', role: 'assistant', content: '要花钱，确认吗？', proposal: { tool: 'optimize_scenes', message: '「批量优化多场」会调用付费模型' } },
        { id: 'u2', role: 'user', content: '/cancel' },
        { id: 'a2', role: 'assistant', content: '已放弃。' },
        { id: 'u3', role: 'user', content: '再优化第1场' },
        { id: 'a3', role: 'assistant', content: '这次只优化一场，确认吗？', proposal: { tool: 'optimize_scenes', message: '「批量优化多场」会调用付费模型（E1S01）' } },
      ],
    }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText('项目甲'));

    const old = (await screen.findByText('要花钱，确认吗？')).closest('.chat-bubble') as HTMLElement;
    const latest = (await screen.findByText('这次只优化一场，确认吗？')).closest('.chat-bubble') as HTMLElement;
    expect((within(old).getByRole('button', { name: '确认执行' }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(latest).getByRole('button', { name: '确认执行' }) as HTMLButtonElement).disabled).toBe(false);
  });
});
