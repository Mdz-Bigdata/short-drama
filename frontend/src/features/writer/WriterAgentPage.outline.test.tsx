// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WriterAgentPage } from './WriterAgentPage';

const breakdown = {
  overview: {
    synopsis: '林夏在十二小时内追查失踪案。',
    genre: '都市悬疑',
    theme: '真相需要付出代价',
  },
  scenes: [
    {
      scene_id: 'E1S01',
      duration: '8s',
      content: '林夏在雨夜收到匿名录音。 对白： 林夏：你究竟隐瞒了什么？ 旁白：录音在雨声中戛然而止。',
      characters: ['林夏'],
    },
    {
      scene_id: 'E1S02',
      duration: '12s',
      content: '林夏质问导师，导师避开她的目光。 周教授：有些事你不该知道。',
      characters: ['林夏', '周教授'],
    },
    {
      scene_id: 'E2S01',
      duration: '10s',
      content: '证据指向周教授的实验室。',
      characters: ['林夏', '周教授'],
    },
  ],
  timeline: [
    { phase: '故事开始', title: '匿名录音', desc: '主角收到录音。', points: [] },
  ],
  roles: [
    { name: '林夏', position: '女主角' },
    { name: '周教授', position: '反派' },
  ],
  relationships: [{ from: '林夏', to: '周教授', relation: '师生对立' }],
};

const script = [
  '第1集 匿名录音',
  '林夏：你究竟隐瞒了什么？',
  '第2集 实验室疑云',
  '证据指向周教授的实验室。',
].join('\n');

describe('WriterAgentPage script outline view', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('switches to a picture-free script outline table with scenes, durations, dialogue and roles', async () => {
    const user = userEvent.setup();
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={breakdown}
        script={script}
        requestedEpisodeCount={2}
        episodes={[]}
      />,
    );

    await user.click(screen.getByRole('button', { name: '剧本大纲' }));

    expect(screen.getByRole('heading', { name: '剧本大纲' })).toBeTruthy();
    const region = screen.getByRole('region', { name: '剧本明细表，可横向滚动' });
    const table = within(region).getByRole('table');
    const headers = within(table).getAllByRole('columnheader').map(cell => cell.textContent);
    expect(headers).toEqual(['场景', '时长', '内容', '对话', '角色']);
    expect(headers).not.toContain('画面');

    expect(within(table).getByText('E1S01')).toBeTruthy();
    expect(within(table).getByText('第 1 集第 1 镜')).toBeTruthy();
    expect(within(table).getByText('第 1 集第 2 镜')).toBeTruthy();
    expect(within(table).getByText('第 2 集第 1 镜')).toBeTruthy();
    expect(within(table).getByText('你究竟隐瞒了什么？')).toBeTruthy();
    expect(within(table).getByText('录音在雨声中戛然而止。')).toBeTruthy();
    expect(within(table).getByText('有些事你不该知道。')).toBeTruthy();
    expect(within(table).getAllByText('林夏、周教授').length).toBe(2);

    // 看板独有的模块在大纲视图下隐藏
    expect(screen.queryByRole('heading', { name: '爽点节奏' })).toBeNull();

    await user.click(screen.getByRole('button', { name: '创作看板' }));
    expect(screen.getByRole('heading', { name: '爽点节奏' })).toBeTruthy();
  });

  it('opens per-episode plain text from the total episode stat', async () => {
    const user = userEvent.setup();
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={breakdown}
        script={script}
        requestedEpisodeCount={2}
        episodes={[]}
      />,
    );

    await user.click(screen.getByRole('button', { name: /总集数 2/ }));
    const dialog = screen.getByRole('dialog', { name: '十二小时 分集剧本文本' });
    expect(within(dialog).getByRole('button', { name: /第 1 集/ })).toBeTruthy();

    const firstText = within(dialog).getByLabelText('第 1 集剧本文本');
    expect(firstText.textContent).toContain('林夏：你究竟隐瞒了什么？');
    expect(firstText.textContent).not.toContain('实验室');

    await user.click(within(dialog).getByRole('button', { name: /第 2 集/ }));
    expect(within(dialog).getByLabelText('第 2 集剧本文本').textContent).toContain('证据指向周教授的实验室。');

    await user.click(within(dialog).getByRole('button', { name: '关闭分集剧本' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('routes the scene and character stats to the character agent previews', async () => {
    const user = userEvent.setup();
    const onOpenScenes = vi.fn();
    const onOpenActors = vi.fn();
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={breakdown}
        script={script}
        requestedEpisodeCount={2}
        episodes={[]}
        onOpenScenes={onOpenScenes}
        onOpenActors={onOpenActors}
      />,
    );

    await user.click(screen.getByRole('button', { name: /场景 3/ }));
    expect(onOpenScenes).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /角色 2/ }));
    expect(onOpenActors).toHaveBeenCalledTimes(1);
  });
});
