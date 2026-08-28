// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WriterAgentPageContainer } from './WriterAgentPageContainer';
import type { WriterDashboardResponse, WriterEpisode } from './types';

const dashboard = {
  schemaVersion: 'writer-dashboard.v1' as const,
  taskId: 'writer-task-1',
  sourceHash: 'a'.repeat(64),
  title: '十二小时',
  state: 'READY' as const,
  overview: {
    synopsis: '林夏在十二小时内追查失踪案。',
    genre: '都市悬疑',
    theme: '真相需要代价',
    worldSetting: '近未来都市',
  },
  stats: {
    totalEpisodes: 2,
    sceneCount: 2,
    characterCount: 2,
    mainEventCount: 2,
    relationshipCount: 1,
    totalDurationSeconds: 110,
    tone: '悬疑',
  },
  scenes: [
    {
      sceneId: 'E1S01',
      episodeIndex: 1,
      sceneIndex: 1,
      startSeconds: 0,
      durationSeconds: 65,
      durationLabel: '1m 5s',
      content: '林夏收到匿名录音。',
      characters: ['林夏'],
      keyEventIndex: 0,
    },
    {
      sceneId: 'E2S01',
      episodeIndex: 2,
      sceneIndex: 2,
      startSeconds: 65,
      durationSeconds: 45,
      durationLabel: '45秒',
      content: '林夏闯入地下实验室。',
      characters: ['林夏', '周教授'],
      keyEventIndex: 1,
    },
  ],
  timeline: [
    {
      eventId: 'event-1',
      order: 1,
      phase: '故事开始',
      title: '匿名录音',
      desc: '倒计时开始。',
      points: ['建立目标'],
      sceneId: 'E1S01',
      startSeconds: 0,
    },
    {
      eventId: 'event-2',
      order: 2,
      phase: '高潮',
      title: '实验室对峙',
      desc: '真相揭晓。',
      points: ['关系反转'],
      sceneId: 'E2S01',
      startSeconds: 65,
    },
  ],
  roles: [{ name: '林夏', position: '女主角' }, { name: '周教授', position: '反派' }],
  relationships: [{ from: '林夏', to: '周教授', relation: '师生对立' }],
  episodes: [
    { index: 1, title: '匿名录音', sceneCount: 1, durationSeconds: 65, status: 'completed' as const, videoUrl: null },
    { index: 2, title: '地下实验室', sceneCount: 1, durationSeconds: 45, status: 'idle' as const, videoUrl: null },
  ],
  script: '第1集 匿名录音\n林夏：你隐瞒了什么？',
};

describe('WriterAgentPageContainer', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('loads the versioned writer dashboard contract from the backend', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => dashboard,
    } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        title="本地标题"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    expect(screen.getByText('实验室对峙')).toBeTruthy();
    expect(screen.getByRole('img', { name: /2名角色、1条人物关系/ })).toBeTruthy();
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(
      'http://localhost:8000/api/drama/writer-task-1/writer-dashboard',
      expect.objectContaining({ credentials: 'include' }),
    ));
  });

  it('persists an edited screenplay through the task-scoped script endpoint', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const revisedDashboard = {
      ...dashboard,
      sourceHash: 'b'.repeat(64),
      script: '# 修订版\n\n林夏：真相就在这里。',
    };
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: true, json: async () => dashboard } as Response)
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: '现有下游资产需要归档后才能应用新剧本' }),
      } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => revisedDashboard } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 · 完整剧本' });
    await user.click(within(dialog).getByRole('button', { name: '编辑剧本' }));
    const editor = within(dialog).getByRole('textbox', { name: '剧本内容' });
    await user.clear(editor);
    await user.type(editor, '# 修订版{Enter}{Enter}林夏：真相就在这里。');
    await user.click(within(dialog).getByRole('button', { name: '保存剧本' }));

    await waitFor(() => expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      'http://localhost:8000/api/drama/writer-task-1/script',
      expect.objectContaining({
        method: 'PATCH',
        credentials: 'include',
        body: JSON.stringify({
          content: '# 修订版\n\n林夏：真相就在这里。',
          file_name: '十二小时.md',
          expected_source_hash: dashboard.sourceHash,
          confirm_invalidate: false,
        }),
      }),
    ));
    await waitFor(() => expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      'http://localhost:8000/api/drama/writer-task-1/script',
      expect.objectContaining({
        method: 'PATCH',
        credentials: 'include',
        body: JSON.stringify({
          content: '# 修订版\n\n林夏：真相就在这里。',
          file_name: '十二小时.md',
          expected_source_hash: dashboard.sourceHash,
          confirm_invalidate: true,
        }),
      }),
    ));
    expect(window.confirm).toHaveBeenCalled();
    expect(await within(dialog).findByText('已保存')).toBeTruthy();
  });

  it('restores a persisted txt filename when the editor is reopened', async () => {
    const user = userEvent.setup();
    const txtDashboard = { ...dashboard, scriptFileName: '现场修订.txt' };
    const revised = { ...txtDashboard, sourceHash: 'c'.repeat(64), script: '纯文本修订' };
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: true, json: async () => txtDashboard } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => revised } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 · 完整剧本' });
    expect(within(dialog).getByText('现场修订.txt')).toBeTruthy();
    await user.click(within(dialog).getByRole('button', { name: '编辑剧本' }));
    const editor = within(dialog).getByRole('textbox', { name: '剧本内容' });
    await user.clear(editor);
    await user.type(editor, '纯文本修订');
    await user.click(within(dialog).getByRole('button', { name: '保存剧本' }));

    await waitFor(() => expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      'http://localhost:8000/api/drama/writer-task-1/script',
      expect.objectContaining({
        body: JSON.stringify({
          content: '纯文本修订',
          file_name: '现场修订.txt',
          expected_source_hash: dashboard.sourceHash,
          confirm_invalidate: false,
        }),
      }),
    ));
  });

  it('saves a dirty draft against its original version after the dashboard refreshes', async () => {
    const user = userEvent.setup();
    const remoteDashboard = {
      ...dashboard,
      sourceHash: 'b'.repeat(64),
      script: '其他标签页已经保存的 B 版本',
    };
    const onScriptSaved = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: true, json: async () => dashboard } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => remoteDashboard } as Response)
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: '剧本已在其他页面更新，请刷新后再保存' }),
      } as Response);
    const commonProps = {
      taskId: 'writer-task-1',
      episodes: [],
      episodesBusy: false,
      onPlanEpisodes: vi.fn(),
      onProduceEpisode: vi.fn(),
      onScriptSaved,
    };
    const { rerender } = render(
      <WriterAgentPageContainer {...commonProps} refreshKey="version-a" />,
    );

    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 · 完整剧本' });
    await user.click(within(dialog).getByRole('button', { name: '编辑剧本' }));
    const editor = within(dialog).getByRole('textbox', { name: '剧本内容' }) as HTMLTextAreaElement;
    await user.clear(editor);
    await user.type(editor, 'A 版本上尚未保存的本地草稿');

    rerender(<WriterAgentPageContainer {...commonProps} refreshKey="version-b" />);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(editor.value).toBe('A 版本上尚未保存的本地草稿');
    await user.click(within(dialog).getByRole('button', { name: '保存剧本' }));

    await waitFor(() => expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      'http://localhost:8000/api/drama/writer-task-1/script',
      expect.objectContaining({
        body: JSON.stringify({
          content: 'A 版本上尚未保存的本地草稿',
          file_name: '十二小时.md',
          expected_source_hash: dashboard.sourceHash,
          confirm_invalidate: false,
        }),
      }),
    ));
    expect((await within(dialog).findByRole('alert')).textContent).toContain('剧本已在其他页面更新');
    expect(editor.value).toBe('A 版本上尚未保存的本地草稿');
    expect(within(dialog).getAllByText(/未保存/).length).toBeGreaterThan(0);
    expect(onScriptSaved).not.toHaveBeenCalled();
  });

  it('atomically replaces invalidated episodes before immediate production and keeps them across remounts', async () => {
    const user = userEvent.setup();
    const staleEpisodes = [
      {
        index: 1,
        title: '旧版第一集',
        summary: '私密旧版剧情摘要',
        status: 'completed' as const,
        videoUrl: 'https://example.test/old.mp4',
      },
      { index: 2, title: '旧版第二集', status: 'completed' as const, videoUrl: 'https://example.test/old-2.mp4' },
    ];
    const revisedDashboard = {
      ...dashboard,
      sourceHash: 'd'.repeat(64),
      script: '新版本正文',
      stats: { ...dashboard.stats, totalEpisodes: 1, sceneCount: 1, totalDurationSeconds: 55 },
      scenes: dashboard.scenes.slice(0, 1),
      episodes: [
        { index: 1, title: '新版第一集', sceneCount: 1, durationSeconds: 55, status: 'idle' as const, videoUrl: null },
      ],
    };
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: true, json: async () => dashboard } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => revisedDashboard } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => revisedDashboard } as Response);

    function WriterEpisodeStateHarness() {
      const [visible, setVisible] = useState(true);
      const [episodeState, setEpisodeState] = useState<{
        sourceHash: string;
        items: WriterEpisode[];
      }>({ sourceHash: dashboard.sourceHash, items: staleEpisodes });
      return <>
        <button type="button" onClick={() => setVisible(current => !current)}>切换 Writer Agent</button>
        {visible && <WriterAgentPageContainer
          taskId="writer-task-1"
          episodes={episodeState.items}
          episodesSourceHash={episodeState.sourceHash}
          episodesBusy={false}
          onPlanEpisodes={vi.fn()}
          onProduceEpisode={index => setEpisodeState(current => ({
            ...current,
            items: current.items.map(episode => episode.index === index
              ? { ...episode, status: 'running' }
              : episode),
          }))}
          onScriptSaved={(savedDashboard: WriterDashboardResponse) => setEpisodeState({
            sourceHash: savedDashboard.sourceHash,
            items: savedDashboard.episodes,
          })}
        />}
      </>;
    }

    render(<WriterEpisodeStateHarness />);
    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    expect(screen.getByText('旧版第一集')).toBeTruthy();
    expect(screen.getByText('旧版第二集')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 · 完整剧本' });
    await user.click(within(dialog).getByRole('button', { name: '编辑剧本' }));
    const editor = within(dialog).getByRole('textbox', { name: '剧本内容' });
    await user.clear(editor);
    await user.type(editor, '新版本正文');
    await user.click(within(dialog).getByRole('button', { name: '保存剧本' }));
    expect(await within(dialog).findByText('已保存')).toBeTruthy();
    expect(screen.getByText('新版第一集')).toBeTruthy();
    expect(screen.queryByText('旧版第一集')).toBeNull();
    expect(screen.queryByText('旧版第二集')).toBeNull();
    expect(screen.queryByRole('link', { name: '播放' })).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: '关闭剧本阅读器' }));
    await user.click(screen.getByRole('button', { name: '制作本集' }));
    expect(await screen.findByText('制作中')).toBeTruthy();
    expect(screen.getByText('新版第一集')).toBeTruthy();
    expect(screen.queryByText('旧版第二集')).toBeNull();

    await user.click(screen.getByRole('button', { name: '切换 Writer Agent' }));
    expect(screen.queryByRole('heading', { name: '十二小时' })).toBeNull();
    await user.click(screen.getByRole('button', { name: '切换 Writer Agent' }));
    expect(await screen.findByText('制作中')).toBeTruthy();
    expect(screen.getByText('新版第一集')).toBeTruthy();
    expect(screen.queryByText('旧版第二集')).toBeNull();
    expect(screen.queryByRole('link', { name: '播放' })).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    const localStorageContents = Object.keys(window.localStorage)
      .map(key => window.localStorage.getItem(key) || '')
      .join('\n');
    expect(localStorageContents).not.toContain('旧版第一集');
    expect(localStorageContents).not.toContain('私密旧版剧情摘要');
    expect(localStorageContents).not.toContain('https://example.test/old.mp4');
  });

  it('prefers the explicit display title over a backend-generated synopsis title', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        ...dashboard,
        title: '现代文学系博士穿越魏晋时期，以历史知识、现代思维与学识，从底层流浪乞儿成长为一代宰执。',
      }),
    } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        displayTitle="乱葬坑里有人醒"
        title="后备标题"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '乱葬坑里有人醒' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /现代文学系博士穿越魏晋时期/ })).toBeNull();
  });

  it('uses the backend script title when the explicit display title is only the unnamed placeholder', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => dashboard,
    } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        displayTitle="未命名剧本"
        title="后备标题"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '十二小时' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '未命名剧本' })).toBeNull();
  });

  it('keeps the unnamed placeholder when every available title is a long synopsis', async () => {
    const backendSynopsisTitle = '林夏在十二小时内追查失踪案并发现导师隐瞒证据，最终必须在真相与亲情之间作出选择。';
    const fallbackSynopsisTitle = '现代文学博士意外穿越乱世并凭借知识从底层流浪者成长为改变时代格局的一代宰执。';
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ ...dashboard, title: backendSynopsisTitle }),
    } as Response);

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        displayTitle="未命名剧本"
        title={fallbackSynopsisTitle}
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: '未命名剧本' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: backendSynopsisTitle })).toBeNull();
    expect(screen.queryByRole('heading', { name: fallbackSynopsisTitle })).toBeNull();
  });

  it('falls back to the current embedded assets when a refresh request fails after a successful load', async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        json: async () => dashboard,
      } as Response)
      .mockRejectedValueOnce(new Error('refresh unavailable'));

    const commonProps = {
      taskId: 'writer-task-1',
      title: '本地项目',
      fallbackBreakdown: {
        overview: { synopsis: '刷新后的本地大纲。' },
        scenes: [{ scene_id: 'E1S01', duration: '9s', content: '刷新后的离线场景', characters: ['林夏'] }],
        roles: [{ name: '林夏', position: '主角' }],
      },
      fallbackScript: '刷新后的本地剧本',
      episodes: [],
      episodesBusy: false,
      onPlanEpisodes: vi.fn(),
      onProduceEpisode: vi.fn(),
    };
    const { rerender } = render(<WriterAgentPageContainer {...commonProps} refreshKey="revision-1" />);

    expect(await screen.findByText('实验室对峙')).toBeTruthy();
    rerender(<WriterAgentPageContainer {...commonProps} refreshKey="revision-2" />);

    expect((await screen.findByRole('status')).textContent).toContain('后端编剧看板暂不可用');
    expect(screen.getAllByText('刷新后的离线场景').length).toBeGreaterThan(0);
    expect(screen.queryByText('实验室对峙')).toBeNull();

    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    expect(screen.getByText('刷新后的本地剧本')).toBeTruthy();
  });

  it('clears the previous dashboard immediately when the task id changes', async () => {
    const pendingSecondDashboard = new Promise<Response>(() => undefined);
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        json: async () => dashboard,
      } as Response)
      .mockImplementationOnce(() => pendingSecondDashboard);

    const baseProps = {
      title: '项目标题',
      fallbackBreakdown: {
        scenes: [{ scene_id: 'E1S01', duration: '7s', content: '第二项目本地场景', characters: ['新角色'] }],
        roles: [{ name: '新角色', position: '主角' }],
      },
      fallbackScript: '第二项目本地剧本',
      episodes: [],
      episodesBusy: false,
      onPlanEpisodes: vi.fn(),
      onProduceEpisode: vi.fn(),
    };
    const { rerender } = render(<WriterAgentPageContainer {...baseProps} taskId="writer-task-1" />);

    expect(await screen.findByText('实验室对峙')).toBeTruthy();
    rerender(<WriterAgentPageContainer {...baseProps} taskId="writer-task-2" />);

    expect(screen.queryByText('实验室对峙')).toBeNull();
    expect(screen.getAllByText('第二项目本地场景').length).toBeGreaterThan(0);
  });

  it('keeps the task asset visible when the backend is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network unavailable'));

    render(
      <WriterAgentPageContainer
        taskId="writer-task-1"
        title="离线项目"
        fallbackBreakdown={{
          scenes: [{ scene_id: 'E1S01', duration: '8s', content: '离线场景', characters: ['林夏'] }],
          roles: [{ name: '林夏', position: '主角' }],
        }}
        fallbackScript="离线剧本"
        episodes={[]}
        episodesBusy={false}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(screen.getAllByText('离线场景').length).toBeGreaterThan(0);
    expect((await screen.findByRole('status')).textContent).toContain('后端编剧看板暂不可用');
  });
});
