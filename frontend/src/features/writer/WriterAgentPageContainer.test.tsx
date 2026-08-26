// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WriterAgentPageContainer } from './WriterAgentPageContainer';

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
