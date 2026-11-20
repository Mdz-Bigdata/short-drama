// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskResponse, WorkflowSnapshot } from './types';
import App from './App';

vi.mock('./features/workbench/TimelinePanel', () => ({
  TimelinePanel: ({ onRendered }: { onRendered?: (url: string) => void }) => (
    <button type="button" onClick={() => onRendered?.('/media/film.mp4')}>按时间线重新合成</button>
  ),
}));

function task(patch: Partial<TaskResponse> = {}): TaskResponse {
  const workflow: WorkflowSnapshot = {
    stages: Array.from({ length: 8 }, (_, i) => ({ stage: i + 1, label: `Agent ${i + 1}`, state: i < 5 ? 'complete' : 'pending', missing: [], guidance: '' })),
    next_stage: 6, active_stage: null, completed_stages: [1, 2, 3, 4, 5], production_complete: false,
    release_ready: false, mode: 'ready', hint: '接下来是第 6/8 步。', event_id: 'ready-6',
    actions: [{ kind: 'continue', label: '继续：音频总监', message: '继续' }],
  };
  return {
    taskId: 'task-a', currentStage: 6, stageName: '音频总监', status: 'idle',
    config: { titleSuggestion: '项目甲', directorStyle: 'realistic', shotStyle: 'cinematic', llmModel: 'test', imageModel: 'test', videoModel: 'test', ttsModel: 'test', oneClick: false },
    assets: {}, logs: {}, workflow, chatHistory: [],
    ...patch,
  };
}

const response = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => data }) as Response;

function mockFetch(current: () => TaskResponse, intercept?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const result = intercept?.(url, init);
    if (result) return await result;
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

async function openProject() {
  const user = userEvent.setup();
  const view = render(<App />);
  await user.click(await screen.findByText('项目甲'));
  return { user, view };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('App stage with no output yet', () => {
  it('offers the workflow buttons the text points at and sends the chosen one', async () => {
    const fetchMock = mockFetch(() => task());
    const { user, view } = await openProject();

    await screen.findByText('这一步还没有产物');
    const empty = view.container.querySelector('.stage-empty') as HTMLElement;
    expect(within(empty).getByText(/点下面的按钮继续/)).toBeTruthy();
    await user.click(within(empty).getByRole('button', { name: '继续：音频总监' }));

    await waitFor(() => {
      const sent = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/drama/task-a/assistant'));
      // 每条消息都带上界面上下文(当前在哪一步)，助手据此理解「这一场」「她」指谁。
      expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ message: '继续', context: expect.objectContaining({ stage: expect.any(Number) }) });
    });
  });

  it('points at the chat box alone when the server lists no action', async () => {
    mockFetch(() => task({ workflow: undefined }));
    const { view } = await openProject();

    await screen.findByText('这一步还没有产物');
    const empty = view.container.querySelector('.stage-empty') as HTMLElement;
    expect(within(empty).getByText(/发送「继续」推进流程/)).toBeTruthy();
    expect(within(empty).queryByRole('button')).toBeNull();
  });

  it('shows the live progress card while that stage is running', async () => {
    mockFetch(() => task({
      status: 'running',
      stageProgress: { stage: 6, stage_label: '音频总监', percent: 40, label: '配音', status: 'running', calls: [{ name: '合成第 3 句对白', status: 'running' }] },
    }));
    const { view } = await openProject();

    await screen.findByText('这一步正在生成');
    const empty = view.container.querySelector('.stage-empty') as HTMLElement;
    expect(within(empty).getByText(/Stage 6 · 音频总监/)).toBeTruthy();
    const call = within(empty).getByText('合成第 3 句对白');
    // The running step used to be white on the white card.
    expect((call.parentElement as HTMLElement).style.color).toBe('var(--ink)');
    expect(within(empty).queryByText('这一步还没有产物')).toBeNull();
  });
});

const timelineResponse = {
  task_id: 'task-a',
  timeline: {
    title: { text: '', seconds: 0 }, revision: 3,
    clips: [{ shot_id: 1, shot_uid: 1, scene_id: 'S1', video_url: '/media/c1.mp4', candidates: [], duration: 4, in: 0, out: null, muted: false,
      subtitle: '朕的江山。', voice_path: null, transition_in: null, review: { decision: 'pending', note: '', decided_at: null }, audio_source: 'native', native_available: true }],
    bgm: { source: 'none', path: null, url: null, library_id: null, name: null, volume: 0.16, duck: true, start: 0 },
  },
  summary: { clips: 1, included: 1, seconds: 4, revision: 3, audio_sources: { native: 1, tts: 0, none: 0 } },
  bgm_library: [],
  acceptance: [],
  post: { settings: { transitions: true, dialogue: true, subtitles: true, title_card: true }, tension: [], scene_markers: [], estimated_bytes: 2_000_000, film_versions: [], shots: [] },
};

describe('App final cut after a timeline render', () => {
  it('reloads the project and swaps the player to the new film', async () => {
    let current = task({
      currentStage: 7, stageName: '合成', videoUrl: '/media/film.mp4',
      assets: { '7': { final_video_url: '/media/film.mp4', rendered_at: '2026-01-01T00:00:00+00:00', timeline_revision: 3 } },
    });
    const fetchMock = mockFetch(() => current, url => {
      if (url.endsWith('/api/drama/task-a/timeline')) return response(timelineResponse);
      if (url.endsWith('/api/drama/task-a/timeline/render')) return response({ final_video_url: '/media/film.mp4' });
      return undefined;
    });
    const { user, view } = await openProject();

    // 第 6、7 步是一个页签「剪辑合成师」：成片在它的播放器里，重新合成在它的底栏。
    expect(await screen.findByRole('region', { name: '剪辑合成师' })).toBeTruthy();
    const render = await screen.findByRole('button', { name: '重新合成' });
    const before = view.container.querySelector('video') as HTMLVideoElement;
    expect(before.getAttribute('src')).toBe('/media/film.mp4');
    const statusCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/drama/task-a/status')).length;
    const loaded = statusCalls();

    // A transition-only edit renders to the same path; only the render time moves.
    current = { ...current, assets: { '7': { ...current.assets['7'], rendered_at: '2026-01-01T00:05:00+00:00' } } };
    await user.click(render);

    await waitFor(() => expect(statusCalls()).toBeGreaterThan(loaded));
    await waitFor(() => expect(view.container.querySelector('video')).not.toBe(before));
    expect(view.container.querySelector('video')?.getAttribute('src')).toBe('/media/film.mp4');
  });
});
