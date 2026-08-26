// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WriterAgentPage } from './WriterAgentPage';

const breakdown = {
  overview: {
    synopsis: '林夏在十二小时内追查失踪案，并发现导师隐瞒了关键证据。',
    genre: '都市悬疑',
    theme: '真相需要付出代价',
  },
  scenes: [
    { scene_id: 'E1S01', duration: '8s', content: '林夏在雨夜收到匿名录音。', characters: ['林夏'] },
    { scene_id: 'E1S02', duration: '12s', content: '林夏质问导师，导师避开她的目光。', characters: ['林夏', '周教授'] },
    { scene_id: 'E2S01', duration: '10s', content: '证据指向周教授的实验室。', characters: ['林夏', '周教授'] },
  ],
  timeline: [
    { phase: '故事开始', title: '匿名录音', desc: '主角收到失踪者留下的录音。', points: ['建立倒计时'] },
    { phase: '危机', title: '导师说谎', desc: '最信任的人暴露破绽。', points: ['关系反转'] },
  ],
  roles: [
    { name: '林夏', position: '女主角' },
    { name: '周教授', position: '反派' },
  ],
  relationships: [{ from: '林夏', to: '周教授', relation: '师生对立' }],
};

describe('WriterAgentPage', () => {
  afterEach(cleanup);

  it('renders the writer dashboard with timeline, episodes and relationship graph', async () => {
    const user = userEvent.setup();
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={breakdown}
        script="第1集 匿名录音\n林夏：你究竟隐瞒了什么？"
        requestedEpisodeCount={2}
        episodes={[]}
        onPlanEpisodes={vi.fn()}
        onProduceEpisode={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: '十二小时' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '爽点节奏' })).toBeTruthy();
    expect(screen.getByLabelText('按场景展开的剧本节奏时间轴')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '分集概览' })).toBeTruthy();
    expect(screen.getAllByText('第 2 集').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('img', { name: /2名角色、1条人物关系/ })).toBeTruthy();
    expect(screen.getAllByText('师生对立').length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('button', { name: '时间线' }));
    expect(screen.getByLabelText('剧情关键事件时间线')).toBeTruthy();
    expect(screen.getByText('最信任的人暴露破绽。')).toBeTruthy();
  });

  it('shows meaningful empty states before the writer asset is generated', () => {
    render(<WriterAgentPage title="待创作项目" requestedEpisodeCount={3} />);

    expect(screen.getByText('等待生成')).toBeTruthy();
    expect(screen.getByText('剧本结构化完成后，场景节奏轴将在这里生成。')).toBeTruthy();
    expect(screen.getByText('识别角色后，这里会生成以主角为中心的人物关系图谱。')).toBeTruthy();
  });

  it('presents the story overview as labeled genre, theme and world-setting details', () => {
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={{
          ...breakdown,
          overview: {
            synopsis: '林夏必须在十二小时内找到失踪者，并判断导师是否值得信任。',
            genre: '都市悬疑',
            theme: '真相与信任的代价',
            world_setting: '近未来沿海都市，公共记忆可以被数字化存取。',
          },
        }}
        script="正文"
      />,
    );

    const overview = within(screen.getByRole('region', { name: '故事大纲' }));
    expect(overview.getByText('题材')).toBeTruthy();
    expect(overview.getByText('都市悬疑')).toBeTruthy();
    expect(overview.getByText('核心主题')).toBeTruthy();
    expect(overview.getByText('真相与信任的代价')).toBeTruthy();
    expect(overview.getByText('世界设定')).toBeTruthy();
    expect(overview.getByText('近未来沿海都市，公共记忆可以被数字化存取。')).toBeTruthy();
  });

  it('removes model preambles and Markdown control characters from the visible synopsis', () => {
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={{
          ...breakdown,
          overview: {
            ...breakdown.overview,
            synopsis: [
              '我将严格遵循“山音超级编剧大师”核心理念与抖音短剧黄金结构，为你交付12集完整分集剧本。',
              '以下内容仅包含摄影机可拍到的画面与可听到的声音。',
              '### 一、输入来源与关键假设',
              '**故事梗概**：林夏在雨夜收到失踪者的匿名录音，并在十二小时内追查真相。',
            ].join('\n'),
          },
        }}
        script="正文"
      />,
    );

    const overviewText = screen.getByRole('region', { name: '故事大纲' }).textContent || '';
    expect(overviewText).toContain('林夏在雨夜收到失踪者的匿名录音，并在十二小时内追查真相。');
    expect(overviewText).not.toContain('我将严格遵循');
    expect(overviewText).not.toContain('以下内容仅包含');
    expect(overviewText).not.toContain('###');
    expect(overviewText).not.toContain('**');
  });

  it('keeps legitimate story prose that naturally begins with “我将”', () => {
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={{
          ...breakdown,
          overview: {
            ...breakdown.overview,
            synopsis: '我将逃离这座城市，却在最后一班地铁里发现失踪多年的姐姐。',
          },
        }}
        script="正文"
      />,
    );

    const overview = screen.getByRole('region', { name: '故事大纲' });
    expect(overview.textContent).toContain('我将逃离这座城市，却在最后一班地铁里发现失踪多年的姐姐。');
  });

  it('does not mistake first-person story promises for a model preamble', () => {
    const legitimateSynopsis = '我将严格遵循父亲留下的建筑结构，为你找到失踪的姐姐。以下内容仅包含她在日记里记录的真相。';
    render(
      <WriterAgentPage
        title="消失的建筑师"
        breakdown={{
          ...breakdown,
          overview: {
            ...breakdown.overview,
            synopsis: legitimateSynopsis,
          },
        }}
        script="正文"
      />,
    );

    const overviewText = screen.getByRole('region', { name: '故事大纲' }).textContent || '';
    expect(overviewText).toContain(legitimateSynopsis);
  });

  it('preserves hash-number locations and underscored story identifiers verbatim', () => {
    const technicalSynopsis = '主角抵达 #7 站台，读取 state_modern 档案后发现姐姐留下的坐标。';
    render(
      <WriterAgentPage
        title="第七站台"
        breakdown={{
          ...breakdown,
          overview: {
            ...breakdown.overview,
            synopsis: technicalSynopsis,
          },
        }}
        script="正文"
      />,
    );

    const overviewText = screen.getByRole('region', { name: '故事大纲' }).textContent || '';
    expect(overviewText).toContain('#7 站台');
    expect(overviewText).toContain('state_modern');
    expect(overviewText).toContain(technicalSynopsis);
  });

  it('cleans a flattened model preamble and inline Markdown while preserving the later synopsis prose', () => {
    render(
      <WriterAgentPage
        title="乱葬坑里有人醒"
        breakdown={{
          ...breakdown,
          overview: {
            ...breakdown.overview,
            synopsis: '我将严格遵循短剧黄金结构为你完成创作。以下内容仅包含可拍摄画面。### 一、输入来源与关键假设 **核心剧情**：沈砚之从乱葬坑苏醒，必须在追兵封城前找到自己的真实身份。',
          },
        }}
        script="正文"
      />,
    );

    const overviewText = screen.getByRole('region', { name: '故事大纲' }).textContent || '';
    expect(overviewText).toContain('沈砚之从乱葬坑苏醒，必须在追兵封城前找到自己的真实身份。');
    expect(overviewText).not.toContain('我将严格遵循');
    expect(overviewText).not.toContain('以下内容仅包含');
    expect(overviewText).not.toContain('###');
    expect(overviewText).not.toContain('**');
  });

  it('opens the screenplay from the book button and supports numbered, button and keyboard pagination', async () => {
    const user = userEvent.setup();
    const longScript = [
      '# 第一集',
      `第一页正文${'线索持续推进。'.repeat(180)}`,
      '',
      '| 场次 | 地点 | 角色 | 剧情目标 |',
      '| --- | --- | --- | --- |',
      '| E1S01 | 档案室 | 林夏、周教授 | 找到失踪记录 |',
      '| E1S02 | 天台 | 林夏 | 揭开匿名录音来源 |',
      '',
      `第二页正文${'危机逐步升级。'.repeat(180)}`,
    ].join('\n');

    render(<WriterAgentPage title="十二小时" breakdown={breakdown} script={longScript} />);

    const openButton = screen.getByRole('button', { name: '分页阅读完整剧本' });
    await user.click(openButton);

    const dialog = screen.getByRole('dialog', { name: '十二小时 · 完整剧本' });
    expect(within(dialog).getByText(/第 1 \/ \d+ 页/)).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: '上一页' }).hasAttribute('disabled')).toBe(true);
    expect(within(dialog).getByRole('button', { name: '第 1 页' }).getAttribute('aria-current')).toBe('page');

    await user.click(within(dialog).getByRole('button', { name: '下一页' }));
    expect(within(dialog).getByText(/第 2 \/ \d+ 页/)).toBeTruthy();

    await user.keyboard('{ArrowRight}');
    expect(within(dialog).getByText(/第 3 \/ \d+ 页/)).toBeTruthy();
    await user.keyboard('{ArrowLeft}');
    expect(within(dialog).getByText(/第 2 \/ \d+ 页/)).toBeTruthy();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '十二小时 · 完整剧本' })).toBeNull();
    expect(document.activeElement).toBe(openButton);
  });

  it('renders Markdown pipe tables as semantic horizontally scrollable multidimensional tables', async () => {
    const user = userEvent.setup();
    const tableScript = [
      '### 角色总表',
      '| character_id | 姓名假设 | 状态列表 | 身份定位 | 视觉锚点 |',
      '| :--- | :--- | :--- | :--- | :--- |',
      '| char_001 | 沈砚之 | 现代、孤儿 | 主角 | 银丝眼镜 |',
      '| char_002 | 王景略 | 权臣 | 反派 | 绯紫宽袍 |',
    ].join('\n');

    render(<WriterAgentPage title="角色圣经" breakdown={breakdown} script={tableScript} />);
    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));

    const table = screen.getByRole('table', { name: '角色总表' });
    expect(table.closest('.writer-markdown-table-scroll')).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'character_id' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '沈砚之' })).toBeTruthy();
    expect(screen.queryByText('| character_id | 姓名假设 | 状态列表 | 身份定位 | 视觉锚点 |')).toBeNull();
  });

  it('draws distinct directed paths and labels for multidirectional character relationships', () => {
    const multidirectionalBreakdown = {
      ...breakdown,
      roles: [
        { name: '林夏', position: '女主角' },
        { name: '周教授', position: '反派' },
        { name: '阿岚', position: '盟友' },
      ],
      relationships: [
        { from: '林夏', to: '周教授', relation: '追查' },
        { from: '周教授', to: '林夏', relation: '欺骗' },
        { from: '林夏', to: '阿岚', relation: '保护' },
        { from: '阿岚', to: '林夏', relation: '信任' },
      ],
    };
    const { container } = render(<WriterAgentPage title="十二小时" breakdown={multidirectionalBreakdown} script="正文" />);

    expect(screen.getByRole('img', { name: /3名角色、4条人物关系/ })).toBeTruthy();
    const paths = Array.from(container.querySelectorAll('path[data-relation-edge]'));
    expect(paths).toHaveLength(4);
    expect(new Set(paths.map(path => path.getAttribute('d'))).size).toBe(4);
    paths.forEach(path => expect(path.getAttribute('marker-end')).toMatch(/^url\(#/));
    expect(screen.getAllByText('追查').length).toBeGreaterThan(0);
    expect(screen.getAllByText('欺骗').length).toBeGreaterThan(0);
  });

  it('uses separate lanes for duplicate forward edges when a reverse edge also exists', () => {
    const overlappingBreakdown = {
      ...breakdown,
      roles: [
        { name: '林夏', position: '女主角' },
        { name: '周教授', position: '反派' },
      ],
      relationships: [
        { from: '林夏', to: '周教授', relation: '追查' },
        { from: '林夏', to: '周教授', relation: '质疑' },
        { from: '周教授', to: '林夏', relation: '误导' },
      ],
    };
    const { container } = render(<WriterAgentPage title="十二小时" breakdown={overlappingBreakdown} script="正文" />);

    const paths = Array.from(container.querySelectorAll('path[data-relation-edge]'));
    expect(paths).toHaveLength(3);
    expect(new Set(paths.map(path => path.getAttribute('d'))).size).toBe(3);
  });

  it('uses real scene co-occurrence as a bidirectional relationship fallback', () => {
    const fallbackRelationshipBreakdown = {
      ...breakdown,
      relationships: [],
      scenes: [
        { scene_id: 'E1S01', content: '二人初次交锋。', characters: ['林夏', '周教授'] },
        { scene_id: 'E1S02', content: '二人在天台对峙。', characters: ['林夏', '周教授'] },
      ],
    };
    const { container } = render(<WriterAgentPage title="十二小时" breakdown={fallbackRelationshipBreakdown} script="正文" />);

    expect(screen.getByRole('img', { name: /2名角色、1条人物关系/ })).toBeTruthy();
    expect(screen.getAllByText('同场互动 · 2 场').length).toBeGreaterThan(0);
    const edge = container.querySelector('path[data-relation-edge]');
    expect(edge?.getAttribute('marker-start')).toMatch(/^url\(#/);
    expect(edge?.getAttribute('marker-end')).toMatch(/^url\(#/);
  });

  it('recognizes backend co-occurrence relationships as bidirectional without inventing a second edge', () => {
    const backendFallback = {
      ...breakdown,
      relationships: [{ from: '林夏', to: '周教授', relation: '同场互动 · 2 场' }],
    };
    const { container } = render(<WriterAgentPage title="十二小时" breakdown={backendFallback} script="正文" />);

    const edge = container.querySelector('path[data-relation-edge]');
    expect(edge?.getAttribute('marker-start')).toMatch(/^url\(#/);
    expect(screen.getByLabelText('双向关系')).toBeTruthy();
  });

  it('clamps the active screenplay page when refreshed content becomes shorter', async () => {
    const user = userEvent.setup();
    const longScript = `# 长篇剧本\n${'线索继续推进。'.repeat(900)}`;
    const { rerender } = render(<WriterAgentPage title="十二小时" breakdown={breakdown} script={longScript} />);

    await user.click(screen.getByRole('button', { name: '分页阅读完整剧本' }));
    await user.click(screen.getByRole('button', { name: '第 3 页' }));
    expect(screen.getByText(/第 3 \/ \d+ 页/)).toBeTruthy();

    rerender(<WriterAgentPage title="十二小时" breakdown={breakdown} script="刷新后的单页剧本。" />);

    expect(screen.getByText('第 1 / 1 页')).toBeTruthy();
    expect(screen.getByText('刷新后的单页剧本。')).toBeTruthy();
  });

  it('calculates legacy scene durations with mixed minute and second formats', () => {
    render(
      <WriterAgentPage
        title="十二小时"
        breakdown={{
          ...breakdown,
          scenes: [
            { scene_id: 'E1S01', duration: '1m 5s', content: '第一场' },
            { scene_id: 'E1S02', duration: '2分钟15秒', content: '第二场' },
          ],
        }}
        script="正文"
      />,
    );

    expect(screen.getAllByText('3 分钟').length).toBeGreaterThanOrEqual(1);
  });

  it('keeps relationships beyond the twelve-node graph visible in the relationship list', () => {
    const roles = Array.from({ length: 14 }, (_, index) => ({
      name: `角色${index + 1}`,
      position: index === 0 ? '主角' : '剧情角色',
    }));
    const relationships = Array.from({ length: 13 }, (_, index) => ({
      from: `角色${index + 1}`,
      to: `角色${index + 2}`,
      relation: index === 12 ? '终局同盟' : `关系${index + 1}`,
    }));

    render(<WriterAgentPage title="群像剧" breakdown={{ ...breakdown, roles, relationships }} script="正文" />);

    expect(screen.getByText('终局同盟')).toBeTruthy();
    expect(screen.getAllByText('角色14').length).toBeGreaterThanOrEqual(1);
  });

  it('caps SVG edges while retaining the complete relationship count for pagination', () => {
    const denseRelationships = Array.from({ length: 120 }, (_, index) => ({
      from: '林夏',
      to: '周教授',
      relation: `关系${index + 1}`,
    }));
    const { container } = render(
      <WriterAgentPage
        title="密集关系"
        breakdown={{ ...breakdown, relationships: denseRelationships }}
        script="正文"
      />,
    );

    expect(container.querySelectorAll('path[data-relation-edge]').length).toBeLessThanOrEqual(80);
    expect(screen.getByText('120')).toBeTruthy();
    expect(screen.getByRole('navigation', { name: '人物关系列表分页' })).toBeTruthy();
  });

  it('keeps relationship endpoints visible even when they are absent from a full role contract', () => {
    const fullRoles = Array.from({ length: 500 }, (_, index) => ({
      name: `档案角色${index + 1}`,
      position: index === 0 ? '主角' : '剧情角色',
    }));
    render(
      <WriterAgentPage
        title="群像档案"
        breakdown={{
          ...breakdown,
          roles: fullRoles,
          relationships: [{ from: '外部证人甲', to: '外部证人乙', relation: '关键证词交换' }],
        }}
        script="正文"
      />,
    );

    expect(screen.getAllByText('关键证词交换').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('外部证人甲').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('外部证人乙').length).toBeGreaterThanOrEqual(1);
  });
});
