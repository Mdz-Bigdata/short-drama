// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WriterAgentPage } from './WriterAgentPage';

const scenes = Array.from({ length: 12 }, (_, index) => ({
  scene_id: `E${index + 1}S01`,
  duration: '10s',
  content: `第${index + 1}集场景：主角推进主线。 林夏：第${index + 1}集关键台词。`,
  characters: ['林夏'],
}));

const script = Array.from({ length: 12 }, (_, index) => [
  `第${index + 1}集 关键事件${index + 1}`,
  `第${index + 1}集正文内容。`,
].join('\n')).join('\n');

const episodes = Array.from({ length: 12 }, (_, index) => ({
  index: index + 1,
  title: `第${index + 1}集 关键事件${index + 1}`,
  status: 'idle' as const,
}));

function renderPage() {
  return render(
    <WriterAgentPage
      title="十二小时"
      breakdown={{ scenes, timeline: [], roles: [{ name: '林夏', position: '女主角' }], relationships: [] }}
      script={script}
      requestedEpisodeCount={12}
      episodes={episodes}
    />,
  );
}

describe('WriterAgentPage episode overview interactions', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('names what is wrong with an episode the server reports as not well formed', () => {
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={{ scenes, timeline: [], roles: [{ name: '林夏', position: '女主角' }], relationships: [] }}
        script={script}
        requestedEpisodeCount={12}
        episodes={episodes.map(episode => (episode.index === 3
          ? {
            ...episode,
            sceneCount: 1,
            durationSeconds: 8,
            issues: [
              { code: 'episode_too_few_scenes', message: '本集只有 1 个分镜，至少需要 2 个', severity: 'error' as const },
              { code: 'episode_too_short', message: '本集各分镜时长合计 8 秒，不能少于 60 秒', severity: 'error' as const },
            ],
          }
          : { ...episode, sceneCount: 10, durationSeconds: 90, issues: [] }))}
      />,
    );

    const notes = screen.getByRole('list', { name: '第 3 集待处理问题' });
    expect(within(notes).getByText('本集只有 1 个分镜，至少需要 2 个')).toBeTruthy();
    expect(within(notes).getByText('本集各分镜时长合计 8 秒，不能少于 60 秒')).toBeTruthy();
    expect(notes.closest('article')?.className).toContain('has-issue');
    // A well-formed episode carries no notice at all.
    expect(screen.queryByRole('list', { name: '第 2 集待处理问题' })).toBeNull();
  });

  it('shows nine episodes per page with next-page navigation', async () => {
    const user = userEvent.setup();
    renderPage();

    const map = screen.getByRole('heading', { name: '分集概览' }).closest('section') as HTMLElement;
    expect(within(map).getAllByText(/^第 \d+ 集$/)).toHaveLength(9);
    expect(within(map).getByText('第 9 集')).toBeTruthy();
    expect(within(map).queryByText('第 10 集')).toBeNull();

    const pagination = screen.getByRole('navigation', { name: '分集概览分页' });
    expect(within(pagination).getByText('1 / 2 页 · 共 12 集')).toBeTruthy();
    expect(within(pagination).getByRole('button', { name: '上一页' })).toHaveProperty('disabled', true);

    await user.click(within(pagination).getByRole('button', { name: '下一页' }));
    expect(within(map).getAllByText(/^第 \d+ 集$/)).toHaveLength(3);
    expect(within(map).getByText('第 12 集')).toBeTruthy();
    expect(within(pagination).getByRole('button', { name: '下一页' })).toHaveProperty('disabled', true);

    await user.click(within(pagination).getByRole('button', { name: '上一页' }));
    expect(within(map).getByText('第 1 集')).toBeTruthy();
  });

  it('opens the episode script text from the episode card title', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /关键事件3/ }));

    const dialog = screen.getByRole('dialog', { name: '十二小时 分集剧本文本' });
    expect(within(dialog).getByLabelText('第 3 集剧本文本').textContent).toContain('第3集正文内容。');
  });

  it('opens the per-episode scene breakdown from the scene count', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: '查看第 2 集的 1 个场景' }));

    const dialog = screen.getByRole('dialog', { name: '第 2 集场景明细' });
    expect(within(dialog).getByText('E2S01')).toBeTruthy();
    expect(within(dialog).getByText(/第2集场景：主角推进主线/)).toBeTruthy();
    expect(within(dialog).getByText('第2集关键台词。')).toBeTruthy();
    expect(within(dialog).queryByText('E3S01')).toBeNull();

    await user.click(within(dialog).getByRole('button', { name: '关闭场景明细' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('takes the keyboard into an episode dialog and gives it back to the card on Esc', async () => {
    const user = userEvent.setup();
    renderPage();

    const title = screen.getByRole('button', { name: /关键事件3/ });
    await user.click(title);
    const textDialog = screen.getByRole('dialog', { name: '十二小时 分集剧本文本' });
    expect(document.activeElement).toBe(within(textDialog).getByRole('button', { name: '关闭分集剧本' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(title);

    const count = screen.getByRole('button', { name: '查看第 2 集的 1 个场景' });
    await user.click(count);
    const sceneDialog = screen.getByRole('dialog', { name: '第 2 集场景明细' });
    expect(document.activeElement).toBe(within(sceneDialog).getByRole('button', { name: '关闭场景明细' }));
    await user.keyboard('{Escape}');
    expect(document.activeElement).toBe(count);
  });

  it('keeps Tab and Shift+Tab inside an open episode dialog', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /关键事件3/ }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 分集剧本文本' });
    const close = within(dialog).getByRole('button', { name: '关闭分集剧本' });
    const text = within(dialog).getByLabelText('第 3 集剧本文本');

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(text);
    await user.tab();
    expect(document.activeElement).toBe(close);
  });
});
