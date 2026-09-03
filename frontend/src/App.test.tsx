// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';


const appStylesheet = [
  readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8'),
  readFileSync(resolve(process.cwd(), 'src/features/workbench/StageFivePreview.css'), 'utf8'),
].join('\n');


describe('App model configuration status', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows 已配置 and loads global defaults when the account has an enabled model', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{ id: 'configuration-1', models: [{ id: 'saved-model-1' }] }],
          summary: { text: 1, image: 0, video: 0, audio: 0 },
          global_status: {
            configured: true,
            enabled_total: 1,
            enabled_model_ids: { text: ['global-writer'], image: [], video: [], audio: [] },
            default_model_ids: { text: 'global-writer', image: null, video: null, audio: null },
          },
        }),
      } as Response;
      if (url.endsWith('/api/drama/list') || url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole('button', { name: /模型: 已配置/ })).toBeTruthy();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/model-configurations',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('keeps 未配置 when saved models exist but none is globally enabled', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{ id: 'configuration-1', models: [{ id: 'disabled-model', enabled: false }] }],
          summary: { text: 0, image: 0, video: 0, audio: 0 },
          global_status: {
            configured: false,
            enabled_total: 0,
            enabled_model_ids: { text: [], image: [], video: [], audio: [] },
            default_model_ids: { text: null, image: null, video: null, audio: null },
          },
        }),
      } as Response;
      if (url.endsWith('/api/drama/list') || url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole('button', { name: /模型: 未配置/ })).toBeTruthy();
  });

  it('replaces the episode snapshot hash when a later plan fetch returns another script version', async () => {
    const user = userEvent.setup();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    const sourceHashA = 'a'.repeat(64);
    const sourceHashB = 'b'.repeat(64);
    const task = {
      taskId: 'versioned-writer-task',
      currentStage: 2,
      stageName: '编剧剧本创作',
      status: 'idle' as const,
      config: {
        titleSuggestion: '跨标签版本项目',
        scriptName: '跨标签版本项目.md',
        scriptContent: 'B 版本正文',
        directorStyle: 'realistic',
        shotStyle: 'cinematic',
        llmModel: 'writer-model',
        imageModel: 'image-model',
        videoModel: 'video-model',
        ttsModel: 'audio-model',
        oneClick: false,
        episodeCount: 1,
      },
      assets: { '2': 'B 版本正文' },
      logs: {},
    };
    const writerDashboard = {
      schemaVersion: 'writer-dashboard.v1',
      taskId: task.taskId,
      sourceHash: sourceHashB,
      title: '跨标签版本项目',
      state: 'READY',
      overview: { synopsis: 'B 版本故事', genre: '悬疑', theme: '版本', worldSetting: '都市' },
      stats: {
        totalEpisodes: 1,
        sceneCount: 1,
        characterCount: 1,
        mainEventCount: 1,
        relationshipCount: 0,
        totalDurationSeconds: 60,
        tone: '悬疑',
      },
      scenes: [{
        sceneId: 'E1S01',
        episodeIndex: 1,
        sceneIndex: 1,
        startSeconds: 0,
        durationSeconds: 60,
        durationLabel: '1分钟',
        content: 'B 版本场景',
        characters: ['林夏'],
        keyEventIndex: 0,
      }],
      timeline: [{
        eventId: 'event-b',
        order: 1,
        phase: '故事开始',
        title: 'B 版本事件',
        desc: 'B 版本事件描述',
        points: [],
        sceneId: 'E1S01',
        startSeconds: 0,
      }],
      roles: [{ name: '林夏', position: '主角' }],
      relationships: [],
      episodes: [{
        index: 1,
        title: 'B 服务端分集',
        sceneCount: 1,
        durationSeconds: 60,
        status: 'idle',
        videoUrl: null,
      }],
      script: 'B 版本正文',
      scriptFileName: '跨标签版本项目.md',
    };
    let episodeFetchCount = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [],
          summary: { text: 1, image: 1, video: 1, audio: 1 },
          global_status: {
            configured: true,
            enabled_total: 4,
            enabled_model_ids: { text: ['writer-model'], image: ['image-model'], video: ['video-model'], audio: ['audio-model'] },
            default_model_ids: { text: 'writer-model', image: 'image-model', video: 'video-model', audio: 'audio-model' },
          },
        }),
      } as Response;
      if (url.endsWith('/api/drama/list')) return {
        ok: true,
        status: 200,
        json: async () => [task],
      } as Response;
      if (url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      if (url.endsWith(`/api/drama/${task.taskId}/writer-dashboard`)) return {
        ok: true,
        status: 200,
        json: async () => writerDashboard,
      } as Response;
      if (url.endsWith(`/api/drama/${task.taskId}/episodes/plan`) && init?.method === 'POST') return {
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response;
      if (url.endsWith(`/api/drama/${task.taskId}/episodes`)) {
        episodeFetchCount += 1;
        if (episodeFetchCount === 1) return {
          ok: true,
          status: 200,
          json: async () => ({
            sourceHash: sourceHashA,
            episodes: [{ index: 1, title: 'A 标签旧分集', status: 'completed', videoUrl: 'https://example.test/a.mp4' }],
          }),
        } as Response;
        if (episodeFetchCount === 2) return {
          ok: true,
          status: 200,
          json: async () => ({
            sourceHash: sourceHashB,
            episodes: [{ index: 1, title: 'B 标签轮询分集', status: 'completed', videoUrl: 'https://example.test/b.mp4' }],
          }),
        } as Response;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            sourceHash: 'not-a-valid-source-hash',
            episodes: [{ index: 1, title: '无版本分集不应合并', status: 'completed', videoUrl: 'https://example.test/unversioned.mp4' }],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<App />);
    await user.click(await screen.findByText('跨标签版本项目'));

    expect(await screen.findByRole('heading', { name: '跨标签版本项目' })).toBeTruthy();
    await waitFor(() => expect(episodeFetchCount).toBe(1));
    expect(screen.queryByText('A 标签旧分集')).toBeNull();
    expect(screen.getByText('B 服务端分集')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '重新分集' }));
    expect(await screen.findByText('B 标签轮询分集')).toBeTruthy();
    expect(screen.queryByText('B 服务端分集')).toBeNull();
    expect(screen.getByRole('link', { name: '播放' }).getAttribute('href')).toBe('https://example.test/b.mp4');

    await user.click(screen.getByRole('button', { name: '重新分集' }));
    await waitFor(() => expect(episodeFetchCount).toBe(3));
    expect(screen.queryByText('无版本分集不应合并')).toBeNull();
    expect(screen.getByText('B 服务端分集')).toBeTruthy();
    expect(screen.queryByRole('link', { name: '播放' })).toBeNull();
  });
});

describe('App session expiry from a feature panel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('returns to the login gate when a shared apiRequest call reports 401', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    // Only the feature-panel call expires; the shell's own endpoints stay healthy,
    // which is exactly what a mid-session cookie expiry looks like.
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.includes('/api/elements')) return {
        ok: false,
        status: 401,
        json: async () => ({ detail: '会话已过期，请重新登录' }),
      } as Response;
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({ items: [], globalDefaults: {} }),
      } as Response;
      return { ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response;
    });

    render(<App />);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '立即登录' })).toBeNull();
    });

    const { apiRequest } = await import('./api/client');
    await apiRequest('/api/elements?kind=scene').catch(() => {});

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '立即登录' })).toBeTruthy();
    });
  });
});

describe('App stage asset preview layout', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('gives Stage 5 a large viewport and lets its only ready medium fill the preview', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    const taskSummary = {
      taskId: 'compact-stage-five',
      currentStage: 5,
      stageName: '视觉总监多镜头多帧生成',
      status: 'idle' as const,
      config: {
        titleSuggestion: '紧凑视觉预览',
        directorStyle: 'realistic',
        shotStyle: 'cinematic',
        llmModel: 'writer-model',
        imageModel: 'image-model',
        videoModel: 'video-model',
        ttsModel: 'audio-model',
        oneClick: false,
        episodeCount: 1,
      },
    };
    const fullTask = {
      ...taskSummary,
      assets: {
        '5': [{
          shot_id: 1,
          size: 'MS',
          motion: 'Locked',
          desc: '双人对峙镜头',
          video_url: 'https://example.test/shot-1.mp4',
        }],
      },
      logs: { '5': 'Stage 5 质检通过' },
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({ items: [], globalDefaults: {} }),
      } as Response;
      if (url.endsWith('/api/drama/list')) return {
        ok: true,
        status: 200,
        json: async () => [taskSummary],
      } as Response;
      if (url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      if (url.endsWith(`/api/drama/${taskSummary.taskId}/status`)) return {
        ok: true,
        status: 200,
        json: async () => fullTask,
      } as Response;
      if (url.endsWith(`/api/drama/${taskSummary.taskId}/episodes`)) return {
        ok: true,
        status: 200,
        json: async () => ({ sourceHash: '', episodes: [] }),
      } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });
    const stylesheet = document.createElement('style');
    stylesheet.textContent = appStylesheet;
    document.head.append(stylesheet);

    try {
      render(<App />);
      await userEvent.click(await screen.findByText('紧凑视觉预览'));

      const preview = await screen.findByRole('region', { name: 'Stage 5 阶段资产预览' });
      const shotList = within(preview).getByRole('region', { name: 'Stage 5 镜头资产列表' });
      const shot = within(shotList).getByRole('article', { name: '镜头 1 视觉资产' });
      const videoPane = within(shot).getByRole('region', { name: '镜头 1 图生视频动态画面' });
      const video = videoPane.querySelector('video');
      const mediaGrid = videoPane.closest('.stage-five-media-grid');

      expect(video).not.toBeNull();
      expect(getComputedStyle(preview).flexGrow).toBe('0');
      expect(getComputedStyle(preview.parentElement as Element).flexGrow).toBe('0');
      expect(parseFloat(getComputedStyle(preview).minHeight)).toBeGreaterThanOrEqual(608);
      expect(parseFloat(getComputedStyle(shotList).height)).toBeGreaterThanOrEqual(512);
      expect(mediaGrid).not.toBeNull();
      expect(getComputedStyle(mediaGrid as Element).gridTemplateColumns).toBe('minmax(0, 1fr)');
      expect(within(shot).getByText('首帧图片仍在生成，已优先放大可用视频。')).toBeTruthy();
      expect(screen.getByText('Stage 5 质检通过')).toBeTruthy();
    } finally {
      stylesheet.remove();
    }
  });
});
