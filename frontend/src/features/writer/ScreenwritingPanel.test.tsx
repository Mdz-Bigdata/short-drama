// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ScreenwritingPanel } from './ScreenwritingPanel';
import { planOperations } from './planOperations';
import type { ScreenwritingEpisode, ScreenwritingScene, ScreenwritingState } from './screenwritingApi';

function scene(id: string, overrides: Partial<ScreenwritingScene> = {}): ScreenwritingScene {
  return {
    scene_id: id,
    duration_seconds: 6,
    segment_break: false,
    setting: '地下实验室 夜 内景',
    characters_in_scene: ['林夏'],
    scene_description: `${id} 的画面`,
    utterances: [{ kind: 'dialogue', speaker: '林夏', text: '你到底瞒了什么？', delivery: '压抑-克制 / 慢' }],
    ...overrides,
  };
}

const STATE: ScreenwritingState = {
  schemaVersion: 'screenwriting.v1',
  taskId: 't1',
  available: true,
  engine: 'screenwriting-master',
  sourceKind: 'outline',
  stale: false,
  staleReason: null,
  title: '暗室回声',
  episodeCount: 2,
  overview: { title: '暗室回声', synopsis: '', genre: '悬疑', theme: '', worldSetting: '' },
  inventory: { characters: { 林夏: { description: '黑色短发' } }, scenes: {}, props: {} },
  ledger: [
    { episode: 1, title: '对峙', hook: '录音笔亮起红灯', storyBeats: ['林夏潜入实验室', '周教授拦下她'], nextEpisodeTeaser: '证据被抢走', ledgerStatus: 'written' },
    { episode: 2, title: '反击', hook: '她拨通了那个号码', storyBeats: ['林夏找到备份'], nextEpisodeTeaser: null, ledgerStatus: 'written' },
  ],
  durations: { supported: [4, 5, 6, 7, 8], default: null, episodeTargetSeconds: 90, videoModel: 'seedance2.0' },
  episodes: [
    { episode: 1, title: '对峙', sceneCount: 2, durationSeconds: 12, planRevision: 'sha256-v1:aaa', violationCount: 1, needsReplan: ['E1S02'], writtenAt: '' },
    { episode: 2, title: '反击', sceneCount: 1, durationSeconds: 6, planRevision: 'sha256-v1:bbb', violationCount: 0, needsReplan: [], writtenAt: '' },
  ],
  warnings: [],
  updatedAt: '',
};

const EPISODE: ScreenwritingEpisode = {
  taskId: 't1',
  episode: 1,
  title: '对峙',
  hook: '录音笔亮起红灯',
  nextEpisodeTeaser: '证据被抢走',
  planRevision: 'sha256-v1:aaa',
  stale: false,
  plan: { title: '对峙', scenes: [scene('E1S01'), scene('E1S02', { needs_replan: true })] },
  script: { episode: 1, title: '对峙', scenes: [] },
  screenplayText: '',
  violations: [{ code: 'speech_exceeds_max', message: '口播约 24.0 秒超过最长档 15 秒', label: '分镜 E1S02', severity: 'warning', sceneId: 'E1S02' }],
  needsReplan: ['E1S02'],
  writtenAt: '',
  rewrittenSceneIds: [],
};

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

describe('planOperations', () => {
  it('emits one update per shot whose editable fields actually changed', () => {
    const scenes = [scene('E1S01'), scene('E1S02')];
    const drafts = {
      E1S01: { duration: '6', description: 'E1S01 的画面' },
      E1S02: { duration: '8', description: '改写后的画面' },
    };

    expect(planOperations(scenes, drafts)).toEqual([
      { op: 'update', id: 'E1S02', fields: { duration_seconds: 8, scene_description: '改写后的画面' } },
    ]);
  });

  it('ignores a blank or non-positive duration instead of sending it', () => {
    const scenes = [scene('E1S01')];
    expect(planOperations(scenes, { E1S01: { duration: '', description: 'E1S01 的画面' } })).toEqual([]);
    expect(planOperations(scenes, { E1S01: { duration: '0', description: 'E1S01 的画面' } })).toEqual([]);
  });
});

describe('ScreenwritingPanel', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/screenwriting/episodes/1/prompt')) return jsonResponse({ taskId: 't1', episode: 1, stage: 'plan', prompt: '当前正在生成第 1 集' });
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse(EPISODE);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows the episode ledger with hooks, beats and duration constraints', async () => {
    render(<ScreenwritingPanel taskId="t1" />);

    expect(await screen.findByText('对峙')).toBeTruthy();
    expect(screen.getByText('录音笔亮起红灯')).toBeTruthy();
    expect(screen.getByText('林夏潜入实验室')).toBeTruthy();
    expect(screen.getByText('4–8 秒')).toBeTruthy();
    expect(screen.getByText('90 秒')).toBeTruthy();
    expect(screen.getByText('按导演大纲创作')).toBeTruthy();
    expect(screen.getByText('1 个分镜待重拆')).toBeTruthy();
  });

  it('opens one episode and lists its shots with violations', async () => {
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));

    expect(await screen.findByText('E1S01')).toBeTruthy();
    expect(screen.getByLabelText('E1S01 时长（秒）')).toHaveProperty('value', '6');
    expect(screen.getByText('口播约 24.0 秒超过最长档 15 秒')).toBeTruthy();
    expect(screen.getAllByText('你到底瞒了什么？')).toHaveLength(2);
    // Episode 2 was not requested; only the opened episode is loaded.
    expect(fetchMock.mock.calls.filter(call => String(call[0]).includes('/episodes/2'))).toHaveLength(0);
  });

  async function editFirstShotDuration(value: string) {
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));
    const duration = await screen.findByLabelText('E1S01 时长（秒）');
    await userEvent.clear(duration);
    await userEvent.type(duration, value);
    await userEvent.click(screen.getByRole('button', { name: /保存改动/ }));
  }

  it('sends only the edited shot and reports which shots were re-authored', async () => {
    const patched: RequestInit[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        patched.push(init);
        const body = JSON.parse(String(init.body)) as { baseRevision: string; operations: unknown[]; confirmInvalidate: boolean };
        expect(body.baseRevision).toBe('sha256-v1:aaa');
        expect(body.operations).toEqual([{ op: 'update', id: 'E1S01', fields: { duration_seconds: 8 } }]);
        expect(body.confirmInvalidate).toBe(false);
        return jsonResponse({ ...EPISODE, planRevision: 'sha256-v1:ccc', rewrittenSceneIds: ['E1S01'] });
      }
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse(EPISODE);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });

    await editFirstShotDuration('8');

    await waitFor(() => expect(screen.getByText(/重写了 E1S01/)).toBeTruthy());
    expect(patched).toHaveLength(1);
  });

  it('asks before an edit archives the assets built from the old plan', async () => {
    const confirmations: string[] = [];
    let attempts = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        attempts += 1;
        const body = JSON.parse(String(init.body)) as { confirmInvalidate: boolean };
        if (!body.confirmInvalidate) {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: () => Promise.resolve({ detail: '应用新剧本会归档当前角色、分镜或成片；确认后可安全创建新版本' }),
          } as Response);
        }
        return jsonResponse({ ...EPISODE, rewrittenSceneIds: ['E1S01'] });
      }
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse(EPISODE);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('confirm', (message: string) => { confirmations.push(message); return true; });

    await editFirstShotDuration('8');

    await waitFor(() => expect(screen.getByText(/重写了 E1S01/)).toBeTruthy());
    expect(attempts).toBe(2);
    expect(confirmations[0]).toMatch(/归档/);
  });

  it('keeps the local edit when the user declines the archive confirmation', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({ detail: '应用新剧本会归档当前角色、分镜或成片；确认后可安全创建新版本' }),
        } as Response);
      }
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse(EPISODE);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('confirm', () => false);

    await editFirstShotDuration('8');

    await waitFor(() => expect(screen.getByText('已取消保存，本地改动仍保留。')).toBeTruthy());
    expect(screen.getByLabelText('E1S01 时长（秒）')).toHaveProperty('value', '8');
  });

  it('previews a prompt without triggering a write', async () => {
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));
    await userEvent.click(await screen.findByRole('button', { name: /查看内容层提示词/ }));

    expect(await screen.findByText('当前正在生成第 1 集')).toBeTruthy();
    expect(fetchMock.mock.calls.every(call => (call[1] as RequestInit | undefined)?.method !== 'PATCH')).toBe(true);
  });

  it('offers the prose prompt only when the episode prose is authored from an outline', async () => {
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));
    await userEvent.click(await screen.findByRole('button', { name: /查看正文提示词/ }));

    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/prompt?stage=prose'))).toBe(true));
  });

  it('hides the prose prompt for an uploaded source, whose episodes read as their own text', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse(EPISODE);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      return jsonResponse({ ...STATE, sourceKind: 'novel' });
    });
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));

    expect(await screen.findByRole('button', { name: /查看内容层提示词/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /查看正文提示词/ })).toBeNull();
  });

  it('shows the review summary and each episode\'s review badge', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      return jsonResponse({
        ...STATE,
        episodes: [
          { ...STATE.episodes[0], review: { episode: 1, status: 'confirmed', confirmedBy: 'writer-user' } },
          { ...STATE.episodes[1], review: { episode: 2, status: 'draft', draft: { reasons: ['口播约 24 秒超过最长档 15 秒'], origin: 'model', attempts: 3 } } },
        ],
        reviewSummary: { total: 2, confirmed: [1], pending: [], changed: [], drafts: [2], missing: [], allConfirmed: false, message: '第 2 集仍是带违约的草稿' },
      });
    });
    render(<ScreenwritingPanel taskId="t1" />);

    expect(await screen.findByText(/审核：已确认 1\/2 集/)).toBeTruthy();
    expect(screen.getByText(/审核门不拦截/)).toBeTruthy();
    expect(screen.getByText('已确认')).toBeTruthy();
    expect(screen.getByText('违约草稿')).toBeTruthy();
  });

  it('confirms an episode, refuses while edits are unsaved, and reopens it', async () => {
    const posted: { url: string; body: unknown }[] = [];
    let status: 'pending' | 'confirmed' = 'pending';
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/episodes/1/review')) {
        posted.push({ url, body: JSON.parse(String(init?.body)) });
        status = status === 'pending' ? 'confirmed' : 'pending';
        return jsonResponse({ ...EPISODE, review: { episode: 1, status } });
      }
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse({ ...EPISODE, review: { episode: 1, status } });
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));

    const confirmButton = await screen.findByRole('button', { name: /确认本集/ });
    await userEvent.clear(screen.getByLabelText('E1S01 时长（秒）'));
    await userEvent.type(screen.getByLabelText('E1S01 时长（秒）'), '8');
    expect(confirmButton.hasAttribute('disabled')).toBe(true);
    await userEvent.clear(screen.getByLabelText('E1S01 时长（秒）'));
    await userEvent.type(screen.getByLabelText('E1S01 时长（秒）'), '6');
    await waitFor(() => expect(confirmButton.hasAttribute('disabled')).toBe(false));

    await userEvent.click(confirmButton);
    await waitFor(() => expect(screen.getByText('第 1 集已确认。')).toBeTruthy());
    expect(posted[0].body).toEqual({ action: 'confirm' });

    await userEvent.click(screen.getByRole('button', { name: /重新打开/ }));
    await waitFor(() => expect(screen.getByText('第 1 集已重新打开审核。')).toBeTruthy());
    expect(posted[1].body).toEqual({ action: 'reopen' });
  });

  it('lists a draft\'s reasons and repairs it, reporting when the model did no better', async () => {
    let attempt = 0;
    const draft = { episode: 1, status: 'draft', draft: { reasons: ['口播约 24 秒超过最长档 15 秒'], origin: 'model', attempts: 3 } };
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/episodes/1/repair')) {
        attempt += 1;
        if (attempt === 1) return jsonResponse({ ...EPISODE, review: draft, repair: { episode: 1, repaired: false, improved: false, remaining: ['口播约 24 秒超过最长档 15 秒'] } });
        return jsonResponse({ ...EPISODE, review: { episode: 1, status: 'pending' }, repair: { episode: 1, repaired: true, improved: true, remaining: [] } });
      }
      if (url.includes('/screenwriting/episodes/1')) return jsonResponse({ ...EPISODE, review: draft });
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ task_id: 't1', entries: [], unsplit: [], source_length: 0, layout_revision: '', candidate: null });
      if (url.endsWith('/screenwriting')) return jsonResponse(STATE);
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(<ScreenwritingPanel taskId="t1" />);
    await userEvent.click(await screen.findByRole('button', { name: /第 1 集/ }));

    expect(await screen.findByText(/修好前不能确认/)).toBeTruthy();
    expect(screen.getByText('口播约 24 秒超过最长档 15 秒')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /确认本集/ })).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /AI 修复违约/ }));
    await waitFor(() => expect(screen.getByText(/没有减少违约，保留原草稿/)).toBeTruthy());

    await userEvent.click(screen.getByRole('button', { name: /AI 修复违约/ }));
    await waitFor(() => expect(screen.getByText(/已修复，违约已清除/)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /AI 修复违约/ })).toBeNull();
    expect(screen.getByRole('button', { name: /确认本集/ })).toBeTruthy();
  });

  it('explains itself for a project written by the legacy text engine', async () => {
    fetchMock.mockImplementation(() => jsonResponse({ ...STATE, available: false, ledger: [], episodes: [] }));
    render(<ScreenwritingPanel taskId="t1" />);

    expect(await screen.findByText(/没有结构化分集规划/)).toBeTruthy();
  });
});
