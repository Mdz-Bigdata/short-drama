// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterDesignerPage } from './CharacterDesignerPage';
import {
  buildLegacyCharacterDashboard,
  normalizeCharacterDashboard,
  sanitizeCharacterMediaUrl,
} from './types';

const dashboard = normalizeCharacterDashboard({
  schemaVersion: 'character-dashboard.v1',
  taskId: 'character-task-1',
  sourceHash: 'a'.repeat(64),
  title: '雾港角色设定集',
  state: 'INCOMPLETE',
  viewContract: {
    version: 'five-view.v1',
    views: [
      { key: 'front', order: 1, angleDegrees: 0, labelZh: '正面', labelEn: 'Front view' },
      { key: 'front_three_quarter', order: 2, angleDegrees: 45, labelZh: '正面四分之三', labelEn: 'Front three-quarter view' },
      { key: 'profile', order: 3, angleDegrees: 90, labelZh: '标准侧面', labelEn: 'Standard profile view' },
      { key: 'rear_three_quarter', order: 4, angleDegrees: 135, labelZh: '背面四分之三', labelEn: 'Rear three-quarter view' },
      { key: 'back', order: 5, angleDegrees: 180, labelZh: '背面', labelEn: 'Back view' },
    ],
  },
  project: { genre: '民国悬疑', platform: '竖屏短剧' },
  characters: [
    {
      characterId: 'character-0123456789abcdef',
      name: '沈知微',
      role: '女主角',
      identity: '十九岁，侦探学徒',
      description: '低马尾与深蓝学生装构成稳定身份锚点。',
      colors: [{ name: '午夜蓝', hex: '#18233A' }],
      states: [{ stateId: 'base', title: '基础造型', dna: '敏锐克制', hair: '低马尾', clothing: '深蓝学生装' }],
      assetState: 'PARTIAL',
      views: [
        { key: 'front', order: 1, imageUrl: 'https://img.test/front.png', available: true },
        { key: 'front_three_quarter', order: 2, imageUrl: 'https://img.test/front-45.png', available: true },
        { key: 'profile', order: 3, imageUrl: 'https://img.test/profile.png', available: true },
        { key: 'rear_three_quarter', order: 4, imageUrl: null, available: false },
        { key: 'back', order: 5, imageUrl: null, available: false },
      ],
      quality: { passed: null, uniqueViewHashes: 3, issues: [{ code: 'missing', message: '背部视角尚未生成' }] },
    },
  ],
  rawText: '沈知微从雨夜码头走来，衣角沾着潮湿的雾气。',
});

const interactiveDashboard = normalizeCharacterDashboard({
  schemaVersion: 'character-dashboard.v1',
  taskId: 'character-task-interactive',
  sourceHash: 'b'.repeat(64),
  title: '渡口角色设定集',
  state: 'INCOMPLETE',
  viewContract: dashboard.viewContract,
  characters: [
    {
      characterId: 'character-shen-zhiwei',
      name: '沈知微',
      role: '女主角',
      identity: '十九岁的侦探学徒',
      description: '深蓝学生装，行动谨慎。',
      states: [{ stateId: 'base', title: '基础造型', dna: '敏锐克制', clothing: '深蓝学生装' }],
      assetState: 'READY',
      views: dashboard.viewContract.views.map(view => ({
        key: view.key,
        order: view.order,
        imageUrl: `https://img.test/shen-${view.key}.png`,
        available: true,
      })),
      quality: { passed: true, uniqueViewHashes: 5, issues: [] },
    },
    {
      characterId: 'character-lu-xingyuan',
      name: '陆行远',
      role: '巡警',
      identity: '二十七岁的码头巡警',
      description: '灰色巡警制服，左眉有一道旧疤。',
      states: [{ stateId: 'rain', title: '雨夜执勤', dna: '沉稳警觉', clothing: '灰色巡警制服' }],
      assetState: 'PARTIAL',
      views: dashboard.viewContract.views.map((view, index) => ({
        key: view.key,
        order: view.order,
        imageUrl: index < 2 ? `https://img.test/lu-${view.key}.png` : null,
        available: index < 2,
      })),
      quality: { passed: null, uniqueViewHashes: 2, issues: [{ code: 'missing', message: '陆行远仍缺三个背部视角' }] },
    },
  ],
  rawText: '渡口雨夜，沈知微与陆行远第一次交换线索。',
});

const actions = () => ({
  onRefresh: vi.fn(),
  onRegenerate: vi.fn(),
  onExport: vi.fn(),
  onContinue: vi.fn(),
});

describe('CharacterDesignerPage', () => {
  afterEach(cleanup);

  it('renders the canonical five slots and supports keyboard tab navigation', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    expect(screen.getByRole('heading', { level: 1, name: '沈知微' })).toBeTruthy();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(5);
    expect(tabs.map(tab => tab.textContent)).toEqual([
      '正面0°',
      '正面四分之三45°',
      '标准侧面90°',
      '背面四分之三135°',
      '背面180°',
    ]);

    tabs[0].focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(tabs[2].getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel').textContent).toContain('标准侧面');
    expect(screen.getByText('背部视角尚未生成')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '查看角色总数 1 详情' }));
    expect(screen.getByRole('dialog', { name: '角色资产概览 · 角色总数 1' }).textContent)
      .toContain('1 个角色');
    await user.keyboard('{Escape}');
  });

  it('switches the viewer, inspector and evidence when a different character is selected', async () => {
    const user = userEvent.setup();
    const { container } = render(<CharacterDesignerPage dashboard={interactiveDashboard} {...actions()} />);

    await user.click(screen.getByRole('button', { name: /02.*陆行远.*巡警/ }));

    expect(screen.getByRole('heading', { level: 1, name: '陆行远' })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 1, name: '渡口角色设定集' })).toBeNull();
    expect(screen.getByRole('button', { name: /02.*陆行远.*巡警/ }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByAltText('陆行远 正面 0度').getAttribute('src')).toBe('https://img.test/lu-front.png');
    expect(within(screen.getByLabelText('角色基本信息')).getByText('二十七岁的码头巡警')).toBeTruthy();
    const evidence = container.querySelector('.character-evidence');
    expect(evidence).toBeTruthy();
    expect(within(evidence as HTMLElement).getAllByText(/灰色巡警制服/).length).toBeGreaterThan(0);
    expect(within(evidence as HTMLElement).getByText('陆行远仍缺三个背部视角')).toBeTruthy();
  });

  it('opens information matched to every overview number independently', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={interactiveDashboard} {...actions()} />);

    const checks = [
      {
        trigger: '查看角色总数 2 详情',
        dialog: '角色资产概览 · 角色总数 2',
        content: '沈知微、陆行远',
      },
      {
        trigger: '查看可交付角色 1 详情',
        dialog: '角色资产概览 · 可交付角色 1',
        content: '沈知微',
      },
      {
        trigger: '查看有效视图 7 详情',
        dialog: '角色资产概览 · 有效视图 7',
        content: '沈知微 5 / 5、陆行远 2 / 5',
      },
      {
        trigger: '查看应交视图 10 详情',
        dialog: '角色资产概览 · 应交视图 10',
        content: '2 个角色 × 5 个标准视角',
      },
    ];

    for (const check of checks) {
      await user.click(screen.getByRole('button', { name: check.trigger }));
      expect(screen.getByRole('dialog', { name: check.dialog }).textContent).toContain(check.content);
      await user.keyboard('{Escape}');
    }

    for (const view of interactiveDashboard.viewContract.views) {
      await user.click(screen.getByRole('button', {
        name: `查看${view.angleDegrees}度${view.labelZh}契约详情`,
      }));
      const dialog = screen.getByRole('dialog', {
        name: `五视图契约 · ${view.angleDegrees}° ${view.labelZh}`,
      });
      expect(dialog.textContent).toContain(view.labelEn);
      expect(dialog.textContent).toContain('沈知微：已就绪');
      expect(dialog.textContent).toContain(`陆行远：${view.angleDegrees < 90 ? '已就绪' : '待生成'}`);
      await user.keyboard('{Escape}');
    }
  });

  it('opens every independent five-view image in an accessible large-image dialog', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={interactiveDashboard} {...actions()} />);

    for (const definition of interactiveDashboard.viewContract.views) {
      await user.click(screen.getByRole('tab', { name: `${definition.labelZh}${definition.angleDegrees}°` }));
      const trigger = screen.getByRole('button', { name: `查看沈知微${definition.labelZh}大图` });
      await user.click(trigger);

      const dialog = screen.getByRole('dialog', { name: `沈知微 · ${definition.labelZh}` });
      expect(within(dialog).getByRole('img').getAttribute('src')).toBe(`https://img.test/shen-${definition.key}.png`);
      const closeButton = within(dialog).getByRole('button', { name: '关闭大图' });
      const originalLink = within(dialog).getByRole('link', { name: '在新窗口打开原图' });
      expect(document.activeElement).toBe(closeButton);

      await user.keyboard('{Shift>}{Tab}{/Shift}');
      expect(document.activeElement).toBe(originalLink);
      await user.keyboard('{Tab}');
      expect(document.activeElement).toBe(closeButton);

      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(trigger);
    }
  });

  it('keeps a legacy sheet as a review reference and lets the user inspect it at full size', async () => {
    const user = userEvent.setup();
    const legacy = buildLegacyCharacterDashboard({
      title: '旧版角色资产',
      sheets: { 陆行远: 'https://img.test/legacy-sheet.png' },
      dna: { characters: [{ name: '陆行远', identity: '码头巡警' }] },
      raw: '陆行远，二十七岁。',
    });
    render(<CharacterDesignerPage dashboard={legacy} {...actions()} />);

    expect(screen.getAllByText('待质量审核').length).toBeGreaterThan(0);
    expect(screen.getByText(/尚未拆分并通过五视图质检/)).toBeTruthy();
    expect(screen.getByLabelText('五视图已完成 0 / 5')).toBeTruthy();
    const tabs = screen.getAllByRole('tab');
    tabs.forEach(tab => expect(within(tab).queryByRole('img')).toBeNull());

    await user.click(screen.getByRole('button', { name: '查看陆行远整板参考图大图' }));
    const dialog = screen.getByRole('dialog', { name: '陆行远 · 整板参考图' });
    expect(within(dialog).getByRole('img').getAttribute('src')).toBe('https://img.test/legacy-sheet.png');
  });

  it('falls back to an explicit missing-state when a legacy sheet cannot load', () => {
    const legacy = buildLegacyCharacterDashboard({
      title: '旧版角色资产',
      sheets: { 陆行远: 'https://img.test/missing-legacy-sheet.png' },
      dna: { characters: [{ name: '陆行远', identity: '码头巡警' }] },
      raw: '陆行远，二十七岁。',
    });
    const actionHandlers = actions();
    const { rerender } = render(<CharacterDesignerPage dashboard={legacy} {...actionHandlers} />);

    fireEvent.error(screen.getByRole('img', { name: '陆行远 旧版五视图整板参考图' }));

    expect(screen.queryByRole('button', { name: '查看陆行远整板参考图大图' })).toBeNull();
    expect(screen.getByText('整板参考图加载失败')).toBeTruthy();
    expect(screen.getByText('正面尚未生成')).toBeTruthy();

    const recovered = buildLegacyCharacterDashboard({
      title: '旧版角色资产',
      sheets: { 陆行远: 'https://img.test/recovered-legacy-sheet.png' },
      dna: { characters: [{ name: '陆行远', identity: '码头巡警' }] },
      raw: '陆行远，二十七岁。',
    });
    rerender(<CharacterDesignerPage dashboard={recovered} {...actionHandlers} />);

    expect(screen.getByRole('img', { name: '陆行远 旧版五视图整板参考图' }).getAttribute('src'))
      .toBe('https://img.test/recovered-legacy-sheet.png');
  });

  it('shows a refreshed five-view URL after the previous image failed', () => {
    const actionHandlers = actions();
    const { rerender } = render(<CharacterDesignerPage dashboard={interactiveDashboard} {...actionHandlers} />);

    fireEvent.error(screen.getByRole('img', { name: '沈知微 正面 0度' }));
    expect(screen.queryByRole('button', { name: '查看沈知微正面大图' })).toBeNull();

    const refreshed = normalizeCharacterDashboard({
      ...interactiveDashboard,
      characters: interactiveDashboard.characters.map(character => character.name === '沈知微'
        ? {
          ...character,
          views: character.views.map(view => view.key === 'front'
            ? { ...view, imageUrl: 'https://img.test/shen-front-recovered.png', available: true }
            : view),
        }
        : character),
    });
    rerender(<CharacterDesignerPage dashboard={refreshed} {...actionHandlers} />);

    expect(screen.getByRole('img', { name: '沈知微 正面 0度' }).getAttribute('src'))
      .toBe('https://img.test/shen-front-recovered.png');
  });

  it('exposes complete long-form details and makes the character card a keyboard-scrollable region', async () => {
    const user = userEvent.setup();
    const longIdentity = `身份信息：${'雨夜渡口的秘密与人物动机。'.repeat(30)}`;
    const longEvidence = `角色原文：${'这一段必须可以完整阅读。'.repeat(40)}`;
    const detailed = normalizeCharacterDashboard({
      ...interactiveDashboard,
      project: {
        ...interactiveDashboard.project,
        constraints: '跨五个角度必须保持面部、服装、体态与标志性配饰完全一致。'.repeat(12),
      },
      characters: [{
        ...interactiveDashboard.characters[0],
        identity: longIdentity,
        description: '这是完整角色描述，不应永久停留在三行截断状态。',
      }],
      rawText: longEvidence,
    });
    const { container } = render(<CharacterDesignerPage dashboard={detailed} {...actions()} />);

    const scrollRegion = container.querySelector('.character-designer');
    expect(scrollRegion?.getAttribute('tabindex')).toBe('0');
    expect(scrollRegion?.getAttribute('aria-label')).toBe('角色设计完整内容，可上下滚动');

    await user.click(screen.getByRole('button', { name: '查看沈知微完整角色档案' }));
    expect(screen.getByRole('dialog', { name: '沈知微 · 完整角色档案' }).textContent).toContain(longIdentity);
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '查看角色原文与风险完整内容' }));
    expect(screen.getByRole('dialog', { name: '角色原文与风险' }).textContent).toContain(longEvidence);
    await user.keyboard('{Escape}');

    const projectTrigger = screen.getByRole('button', { name: '查看约束完整内容' });
    await user.click(projectTrigger);
    expect(screen.getByRole('dialog', { name: '项目角色设计基准 · 约束' }).textContent)
      .toContain('跨五个角度必须保持面部、服装、体态与标志性配饰完全一致。');
    const closeButton = screen.getByRole('button', { name: '关闭详情' });
    await user.keyboard('{Tab}');
    expect(document.activeElement).toBe(closeButton);
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(document.activeElement).toBe(closeButton);
    await user.click(closeButton);
    expect(document.activeElement).toBe(projectTrigger);

    await user.click(projectTrigger);
    const backdrop = document.querySelector('.character-dialog-backdrop');
    expect(backdrop).toBeTruthy();
    fireEvent.click(backdrop as HTMLElement);
    expect(screen.queryByRole('dialog', { name: '项目角色设计基准 · 约束' })).toBeNull();
    expect(document.activeElement).toBe(projectTrigger);
  });

  it('renders pipe-delimited character source data as an accessible multidimensional table', async () => {
    const user = userEvent.setup();
    const tableDashboard = normalizeCharacterDashboard({
      ...interactiveDashboard,
      rawText: [
        '### 1.1 角色总表',
        '| character_id | 姓名假设 | 状态列表 | 身份定位 | 视觉锚点 |',
        '|---|---|---|---|---|',
        '| char_001 | 沈知微 | state_modern | 主角 | 清瘦书生骨相 |',
        '| char_002 | 陆行远 | state_rain | 巡警 | 左眉旧疤 |',
      ].join('\n'),
    });
    render(<CharacterDesignerPage dashboard={tableDashboard} {...actions()} />);

    await user.click(screen.getByRole('button', { name: '查看角色原文与风险完整内容' }));
    const dialog = screen.getByRole('dialog', { name: '角色原文与风险' });
    const table = within(dialog).getByRole('table', { name: '1.1 角色总表' });
    expect(within(table).getByRole('columnheader', { name: 'character_id' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '沈知微' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '左眉旧疤' })).toBeTruthy();
    const scrollRegion = table.closest('.writer-markdown-table-scroll');
    expect(scrollRegion?.getAttribute('role')).toBe('region');
    expect(scrollRegion?.getAttribute('tabindex')).toBe('0');
  });

  it('rejects unsafe artwork URLs at the dashboard normalization boundary', () => {
    const unsafeUrls = [
      'javascript:alert(1)',
      'file:///etc/passwd',
      'data:image/svg+xml,<svg/>',
      'https://user:secret@img.test/front.png',
      '/media/../private/secret.png',
      '/media/%2e%2e/private/secret.png',
      '/media/%252e%252e/private/secret.png',
      '/media/characters/%5c..%5csecret.png',
      '//img.test/front.png',
    ];
    unsafeUrls.forEach(url => expect(sanitizeCharacterMediaUrl(url)).toBeNull());

    expect(sanitizeCharacterMediaUrl('https://img.test/front.png')).toBe('https://img.test/front.png');
    expect(sanitizeCharacterMediaUrl('http://img.test/profile.png')).toBe('http://img.test/profile.png');
    expect(sanitizeCharacterMediaUrl('/media/characters/%E6%B2%88%E7%9F%A5%E5%BE%AE.png'))
      .toBe('/media/characters/%E6%B2%88%E7%9F%A5%E5%BE%AE.png');

    const normalized = normalizeCharacterDashboard({
      characters: [{
        name: '危险旧资产',
        sheetUrl: 'javascript:alert(1)',
        assetState: 'READY',
        quality: { passed: true },
        views: [
          { key: 'front', imageUrl: 'data:image/svg+xml,<svg/>' },
          { key: 'front_three_quarter', imageUrl: 'file:///tmp/front.png' },
          { key: 'profile', imageUrl: 'https://user:secret@img.test/profile.png' },
          { key: 'rear_three_quarter', imageUrl: '/media/%2e%2e/private.png' },
          { key: 'back', imageUrl: '/media/characters\\..\\private.png' },
        ],
      }],
    });

    expect(normalized.characters[0].sheetUrl).toBeNull();
    expect(normalized.characters[0].views.every(view => view.imageUrl === null && !view.available)).toBe(true);
    expect(normalized.characters[0].assetState).toBe('MISSING');
  });
});
