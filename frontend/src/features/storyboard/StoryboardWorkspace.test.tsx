// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';

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
