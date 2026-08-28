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
});
