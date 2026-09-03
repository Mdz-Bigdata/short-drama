// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  StoryboardWorkspace,
  type SceneBoardStatus,
  type StoryboardProgress,
  type StoryboardShot,
} from './StoryboardWorkspace';

const shots: StoryboardShot[] = [
  { shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/shot-1.png', size: 'MS', motion: 'Dolly In' },
  { shot_id: 2, scene_id: 'E1S01', image_url: 'https://img.test/shot-2.png', size: 'CU', motion: 'Static' },
  { shot_id: 3, scene_id: 'E1S01', image_url: null },
];

function renderWorkspace() {
  return render(
    <StoryboardWorkspace
      title="乱葬坑里有人醒"
      shots={shots}
      taskId="task-1"
      gridUrl="http://localhost:8000/media/storyboards/grid_test.png"
      onRefresh={vi.fn()}
      onRegenerate={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
}

describe('StoryboardWorkspace downloads', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      blob: async () => new Blob(['png-bytes'], { type: 'image/png' }),
    })));
    URL.createObjectURL = vi.fn(() => 'blob:storyboard');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('downloads the full storyboard grid through the backend proxy', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(screen.getByRole('button', { name: /下载全部分镜图/ }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/drama/task-1/storyboard/download?target=grid',
        { credentials: 'include' },
      );
    });
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it('downloads the selected scene’s own board, not the task-wide grid', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(screen.getByRole('button', { name: /下载本图/ }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/drama/task-1/storyboard/download?target=scene&scene=E1S01',
        { credentials: 'include' },
      );
    });
  });

  it('downloads a single frame when its image is clicked', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(screen.getByRole('button', { name: '下载分镜 2' }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/drama/task-1/storyboard/download?target=shot&shot=1',
        { credentials: 'include' },
      );
    });
  });

  it('keeps a pending frame selectable without requesting a download', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(screen.getByRole('button', { name: '选择分镜 3' }));

    expect(fetch).not.toHaveBeenCalled();
  });

  it('surfaces a status message when the download fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 502 })));
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(screen.getByRole('button', { name: /下载全部分镜图/ }));

    expect(await screen.findByRole('status')).toBeTruthy();
    expect(screen.getByText('分镜图下载失败，请确认后端服务可用后重试。')).toBeTruthy();
  });
});

const multiEpisodeShots: StoryboardShot[] = [
  ...Array.from({ length: 9 }, (_, index) => ({
    shot_id: index + 1,
    scene_id: 'E1S01',
    image_url: `https://img.test/e1s01-${index + 1}.png`,
  })),
  { shot_id: 10, scene_id: 'E1S02', image_url: 'https://img.test/e1s02-1.png' },
  { shot_id: 11, scene_id: 'E2S01', image_url: 'https://img.test/e2s01-1.png' },
];

describe('StoryboardWorkspace episode hierarchy', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('groups scenes under collapsible episode entries', async () => {
    const user = userEvent.setup();
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={multiEpisodeShots}
        taskId="task-1"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    expect(within(nav).getByRole('button', { name: /第 1 集/ })).toBeTruthy();
    expect(within(nav).getByRole('button', { name: /第 2 集/ })).toBeTruthy();
    expect(within(nav).getByText('E1S01')).toBeTruthy();
    expect(within(nav).getByText('E1S02')).toBeTruthy();
    expect(within(nav).getByText('E2S01')).toBeTruthy();

    await user.click(within(nav).getByRole('button', { name: /第 1 集/ }));
    expect(within(nav).queryByText('E1S01')).toBeNull();
    expect(within(nav).queryByText('E1S02')).toBeNull();
    expect(within(nav).getByText('E2S01')).toBeTruthy();

    await user.click(within(nav).getByRole('button', { name: /第 1 集/ }));
    expect(within(nav).getByText('E1S01')).toBeTruthy();
  });

  it('switches the header to the episode of the selected scene', async () => {
    const user = userEvent.setup();
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={multiEpisodeShots}
        taskId="task-1"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByText('第 1 集 · 乱葬坑里有人醒')).toBeTruthy();
    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    await user.click(within(nav).getByText('E2S01'));
    expect(screen.getByText('第 2 集 · 乱葬坑里有人醒')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'E2S01 时序分镜' })).toBeTruthy();
  });

  it('pads a short scene to nine grid slots with vacant placeholders', async () => {
    const user = userEvent.setup();
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={multiEpisodeShots}
        taskId="task-1"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    await user.click(within(nav).getByText('E1S02'));

    expect(screen.getByRole('button', { name: '下载分镜 1' })).toBeTruthy();
    expect(screen.getAllByText(/画格 \d · 空位/)).toHaveLength(8);
  });
});

describe('StoryboardWorkspace per-scene download targeting', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      blob: async () => new Blob(['png-bytes'], { type: 'image/png' }),
    })));
    URL.createObjectURL = vi.fn(() => 'blob:storyboard');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('requests the scene actually selected in a multi-scene board', async () => {
    const user = userEvent.setup();
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={multiEpisodeShots}
        taskId="task-1"
        gridUrl="http://localhost:8000/media/storyboards/grid_test.png"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    await user.click(within(nav).getByText('E2S01'));
    await user.click(screen.getByRole('button', { name: /下载本图/ }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/drama/task-1/storyboard/download?target=scene&scene=E2S01',
        { credentials: 'include' },
      );
    });
    // The task-wide grid endpoint must not be what a per-scene action fetches.
    expect(fetch).not.toHaveBeenCalledWith(
      'http://localhost:8000/api/drama/task-1/storyboard/download?target=grid',
      { credentials: 'include' },
    );
  });

  it('keeps the whole-board action pointed at the task-wide grid', async () => {
    const user = userEvent.setup();
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={multiEpisodeShots}
        taskId="task-1"
        gridUrl="http://localhost:8000/media/storyboards/grid_test.png"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /下载全部分镜图/ }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/drama/task-1/storyboard/download?target=grid',
        { credentials: 'include' },
      );
    });
  });
});

// —— 期望清单 / 集锁定 / 继续门禁（契约 assets["4_scene_boards"] + assets["4_progress"]） ——

const breakdownEightScenes = Array.from({ length: 8 }, (_, index) => ({
  scene_id: `E1S${String(index + 1).padStart(2, '0')}`,
  content: `第一集场景 ${index + 1}`,
}));

const e1s01Shots: StoryboardShot[] = Array.from({ length: 9 }, (_, index) => ({
  shot_id: index + 1,
  scene_id: 'E1S01',
  image_url: `https://img.test/e1s01-${index + 1}.png`,
}));

function pendingBoards(sceneIds: string[], overrides: Record<string, SceneBoardStatus> = {}) {
  const boards: Record<string, SceneBoardStatus> = {};
  sceneIds.forEach(sceneId => {
    boards[sceneId] = overrides[sceneId] ?? { status: 'pending', shots_total: 9, shots_done: 0, episode: 1 };
  });
  return boards;
}

// R1 对抗审查：30 集 / 105 场景的剧本大纲（第 1 集 8 场，2-11 集各 4 场，12-30 集各 3 场）。
function bigBreakdown() {
  const scenes: { scene_id: string; content: string }[] = [];
  for (let episode = 1; episode <= 30; episode++) {
    const perEpisode = episode === 1 ? 8 : episode <= 11 ? 4 : 3;
    for (let index = 1; index <= perEpisode; index++) {
      scenes.push({
        scene_id: `E${episode}S${String(index).padStart(2, '0')}`,
        content: `第${episode}集场景${index}`,
      });
    }
  }
  return scenes;
}

function boardsFor(sceneIds: string[], overrides: Record<string, SceneBoardStatus> = {}) {
  const boards: Record<string, SceneBoardStatus> = {};
  sceneIds.forEach(sceneId => {
    const episode = Number(/E(\d{1,3})/.exec(sceneId)?.[1] ?? 1);
    boards[sceneId] = overrides[sceneId] ?? { status: 'pending', shots_total: 9, shots_done: 0, episode };
  });
  return boards;
}

describe('StoryboardWorkspace 30-episode / 105-scene breakdown (R1)', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders all 105 scene cards; episode 1 has exactly E1S01–E1S08 in order and a breakdown-based total', () => {
    const breakdown = bigBreakdown();
    expect(breakdown).toHaveLength(105);
    const sceneIds = breakdown.map(scene => scene.scene_id);
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={boardsFor(sceneIds, {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        })}
        progress={{
          current_episode: 1,
          // 契约只写了第 1 集：total=8 来自剧本大纲的场景数，而不是已生成数(1)。
          episodes: [{ number: 1, total: 8, done: 1, complete: false }],
        }}
        breakdownScenes={breakdown}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    expect(within(nav).getByText('共 30 集')).toBeTruthy();
    // 30 个集头全部渲染。
    expect(within(nav).getAllByRole('button', { name: /第 \d+ 集/ })).toHaveLength(30);
    // 105 张场景卡全量渲染（未生成的也以「待创作」出现）。
    expect(nav.querySelectorAll('.storyboard-scene-card')).toHaveLength(105);

    // 第 1 集分组：恰好 8 张卡，编号 E1S01–E1S08 齐全且有序。
    const episodeOneGroup = within(nav)
      .getByRole('button', { name: /第 1 集/ })
      .closest('.storyboard-episode-group') as HTMLElement;
    const episodeOneIds = [...episodeOneGroup.querySelectorAll('.storyboard-scene-card')]
      .map(card => card.querySelector('strong')?.textContent);
    expect(episodeOneIds).toEqual([
      'E1S01', 'E1S02', 'E1S03', 'E1S04', 'E1S05', 'E1S06', 'E1S07', 'E1S08',
    ]);

    // 集头 done/total：第 1 集用契约数字 1/8（total 来自 breakdown 写入的契约，非已生成数）。
    expect(within(episodeOneGroup).getByText('1/8 个分镜场景')).toBeTruthy();
    // 契约没写第 2-30 集时，total 从剧本大纲骨架推导（第 2-11 集各 4 场、第 12-30 集各 3 场），
    // 同样不是已生成数（0 场也显示 0/4、0/3）。
    expect(within(nav).getAllByText('0/4 个分镜场景')).toHaveLength(10);
    expect(within(nav).getAllByText('0/3 个分镜场景')).toHaveLength(19);
  });
});

describe('StoryboardWorkspace expectation checklist', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders every breakdown scene, keeping unstarted ones visible as 待创作', () => {
    const sceneIds = breakdownEightScenes.map(scene => scene.scene_id);
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={pendingBoards(sceneIds, {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
          E1S02: { status: 'generating', shots_total: 9, shots_done: 3, episode: 1 },
        })}
        progress={{ current_episode: 1, episodes: [{ number: 1, total: 8, done: 1, complete: false }] }}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    sceneIds.forEach(sceneId => {
      expect(within(nav).getByText(sceneId)).toBeTruthy();
    });
    // 集头计数使用契约数字：done/total 来自 4_progress，而不是已生成 shots 的反推。
    expect(within(nav).getByText('1/8 个分镜场景')).toBeTruthy();
    expect(within(nav).getAllByText('已完成')).toHaveLength(1);
    expect(within(nav).getAllByText('生成中')).toHaveLength(1);
    expect(within(nav).getAllByText('待创作')).toHaveLength(6);
  });
});

describe('StoryboardWorkspace episode locking', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('locks episode 2 scene cards while episode 1 is incomplete', async () => {
    const user = userEvent.setup();
    const breakdown = [
      { scene_id: 'E1S01', content: '第一集开场' },
      { scene_id: 'E1S02', content: '第一集反转' },
      { scene_id: 'E2S01', content: '第二集开场' },
    ];
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={pendingBoards(['E1S01', 'E1S02', 'E2S01'], {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        })}
        progress={{
          current_episode: 1,
          episodes: [
            { number: 1, total: 2, done: 1, complete: false },
            { number: 2, total: 1, done: 0, complete: false },
          ],
        }}
        breakdownScenes={breakdown}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    const lockedCard = within(nav).getByText('E2S01').closest('button');
    expect(lockedCard?.className).toContain('is-locked');
    expect(lockedCard?.getAttribute('aria-disabled')).toBe('true');
    expect(within(nav).getByText('待上一集完成')).toBeTruthy();

    // 点击锁定卡不切换：主区仍停留在第 1 集的场景。
    await user.click(within(nav).getByText('E2S01'));
    expect(screen.getByText('第 1 集 · 乱葬坑里有人醒')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'E1S01 时序分镜' })).toBeTruthy();
  });
});

describe('StoryboardWorkspace continue gate', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('disables the continue button and shows done/total while the episode is unfinished', () => {
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={pendingBoards(breakdownEightScenes.map(scene => scene.scene_id), {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        })}
        progress={{ current_episode: 1, episodes: [{ number: 1, total: 8, done: 1, complete: false }] }}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(true);
    expect(screen.getByText(/第 1 集分镜 1\/8，全部完成后可继续/)).toBeTruthy();
  });

  it('enables the continue button once every scene of the current episode is done', async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();
    const breakdown = [
      { scene_id: 'E1S01', content: '第一集开场' },
      { scene_id: 'E1S02', content: '第一集反转' },
    ];
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={{
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
          E1S02: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        }}
        progress={{ current_episode: 1, episodes: [{ number: 1, total: 2, done: 2, complete: true }] }}
        breakdownScenes={breakdown}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={onContinue}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(false);
    expect(screen.queryByText(/全部完成后可继续/)).toBeNull();
    await user.click(continueButton);
    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it('keeps an old task usable when only the breakdown exists without the stage-4 contract', () => {
    // 旧任务：stage2 已写 2_breakdown，但 stage4 是旧版单板产物(无 4_scene_boards / 4_progress)。
    // 后端对这类任务不做 4_progress 完成度判定，前端也不得锁定或禁用「继续视觉制作」。
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={shots}
        taskId="task-1"
        breakdownScenes={[
          { scene_id: 'E1S01', content: '第一集开场' },
          { scene_id: 'E1S02', content: '第一集反转' },
          { scene_id: 'E2S01', content: '第二集开场' },
        ]}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(false);
    expect(screen.queryByText(/全部完成后可继续/)).toBeNull();
    // 大纲骨架仍然渲染(R1)，但不出现锁定态。
    const nav = screen.getByRole('complementary', { name: '分集与时序分镜目录' });
    expect(within(nav).getByText('E2S01')).toBeTruthy();
    expect(within(nav).queryByText('待上一集完成')).toBeNull();
  });

  it('is disabled at exactly 7/8 and enabled at 8/8 of the same episode', () => {
    const sceneIds = breakdownEightScenes.map(scene => scene.scene_id);
    const doneBoard = { status: 'done', shots_total: 9, shots_done: 9, episode: 1 } as const;
    const sevenOfEight = Object.fromEntries(
      sceneIds.map((sceneId, index) => [sceneId, index < 7 ? doneBoard : { ...doneBoard, status: 'pending' as const, shots_done: 0 }]),
    );
    const { unmount } = render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={sevenOfEight}
        progress={{ current_episode: 1, episodes: [{ number: 1, total: 8, done: 7, complete: false }] }}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    let continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(true);
    expect(screen.getByText(/第 1 集分镜 7\/8，全部完成后可继续/)).toBeTruthy();
    unmount();

    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={Object.fromEntries(sceneIds.map(sceneId => [sceneId, doneBoard]))}
        progress={{ current_episode: 1, episodes: [{ number: 1, total: 8, done: 8, complete: true }] }}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(false);
  });

  it('stays strict when 4_progress claims complete but 4_scene_boards still shows pending scenes', () => {
    // 手工构造的不一致：契约谎报 complete=true / done=8，场景板却全是 pending。宁严勿松：不放行。
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={[]}
        taskId="task-1"
        sceneBoards={pendingBoards(breakdownEightScenes.map(scene => scene.scene_id))}
        progress={{ current_episode: 2, episodes: [{ number: 1, total: 8, done: 8, complete: true }] }}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(true);
    // 展示数字同样从严：done 取契约与场景板中的较小值。
    expect(screen.getByText(/第 1 集分镜 0\/8，全部完成后可继续/)).toBeTruthy();
  });

  it('does not crash on a malformed 4_progress and falls back to the strict board-derived gate', () => {
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={pendingBoards(breakdownEightScenes.map(scene => scene.scene_id), {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        })}
        progress={{
          current_episode: '2',
          episodes: { bogus: true },
        } as unknown as StoryboardProgress}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(true);
    expect(screen.getByText(/第 1 集分镜 1\/8，全部完成后可继续/)).toBeTruthy();
  });

  it('does not crash when the episodes array itself contains null holes', () => {
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={e1s01Shots}
        taskId="task-1"
        sceneBoards={pendingBoards(breakdownEightScenes.map(scene => scene.scene_id), {
          E1S01: { status: 'done', shots_total: 9, shots_done: 9, episode: 1 },
        })}
        progress={{
          current_episode: 1,
          episodes: [null, { number: 1, total: 8, done: 1, complete: false }],
        } as unknown as StoryboardProgress}
        breakdownScenes={breakdownEightScenes}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(true);
    expect(screen.getByText(/第 1 集分镜 1\/8，全部完成后可继续/)).toBeTruthy();
  });

  it('keeps the legacy behavior when the contract props are absent', () => {
    render(
      <StoryboardWorkspace
        title="乱葬坑里有人醒"
        shots={shots}
        taskId="task-1"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    // 回退现状：不传新 props 时按钮仅依赖 onContinue，不出现门禁提示。
    const continueButton = screen.getByRole('button', { name: /确认分镜，继续视觉制作/ }) as HTMLButtonElement;
    expect(continueButton.disabled).toBe(false);
    expect(screen.queryByText(/全部完成后可继续/)).toBeNull();
  });
});

describe('StoryboardWorkspace 场景描述可读性', () => {
  afterEach(() => cleanup());

  it('侧栏卡片截断的场景描述可通过 tooltip 与主区域读到全文', () => {
    // 卡片受侧栏宽度所限单行截断（末尾显示「…」）。选中后：卡片就地展开（CSS）、
    // 标题带原生 tooltip、主区域给出不截断的完整描述，三条路径都能读到全文。
    const full = '沈砚跪在太常寺天文台青石阶上，指尖划出三道血痕。阴影中一只玄色官靴走出，贺兰霆低声提及十年前沈砚父亲同样跪着死去。';
    render(
      <StoryboardWorkspace
        title="古装权谋短剧"
        shots={[{ shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/1.png', scene: full }]}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    const cardTitle = document.querySelector('.storyboard-scene-card__title');
    expect(cardTitle?.getAttribute('title')).toBe(full);
    expect(document.querySelector('.storyboard-scene-summary')?.textContent).toBe(full);
  });

  it('没有真实场景描述时不渲染占位摘要', () => {
    render(
      <StoryboardWorkspace
        title="古装权谋短剧"
        shots={[{ shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/1.png' }]}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(document.querySelector('.storyboard-scene-summary')).toBeNull();
  });
});
