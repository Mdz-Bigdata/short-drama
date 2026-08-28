// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CharacterDesignerPage } from './CharacterDesignerPage';
import { normalizeCharacterDashboard } from './types';

const dashboard = normalizeCharacterDashboard({
  schemaVersion: 'character-dashboard.v1',
  taskId: 'character-task-tabs',
  sourceHash: 'c'.repeat(64),
  title: '雾港角色设定集',
  state: 'READY',
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
  characters: [
    {
      characterId: 'character-shen-yanzhi',
      name: '沈砚之',
      role: '男主角',
      identity: '现代文学系博士',
      description: '银丝半框眼镜与白衬衫构成身份锚点。',
      states: [{ stateId: 'base', title: '基础造型', dna: '冷静克制', clothing: '白衬衫' }],
      assetState: 'READY',
      views: [
        { key: 'front', order: 1, imageUrl: 'https://img.test/front.png', available: true },
        { key: 'front_three_quarter', order: 2, imageUrl: 'https://img.test/front-45.png', available: true },
        { key: 'profile', order: 3, imageUrl: 'https://img.test/profile.png', available: true },
        { key: 'rear_three_quarter', order: 4, imageUrl: 'https://img.test/rear-135.png', available: true },
        { key: 'back', order: 5, imageUrl: 'https://img.test/back.png', available: true },
      ],
      quality: { passed: true, uniqueViewHashes: 5, issues: [] },
    },
    {
      characterId: 'character-wang-jinglue',
      name: '王景略',
      role: '权臣',
      identity: '门阀家主',
      description: '绛紫官袍与白玉如意。',
      states: [{ stateId: 'base', title: '基础造型', dna: '威仪深沉', clothing: '绛紫官袍' }],
      assetState: 'READY',
      views: [
        { key: 'front', order: 1, imageUrl: 'https://img.test/wang-front.png', available: true },
        { key: 'front_three_quarter', order: 2, imageUrl: null, available: false },
        { key: 'profile', order: 3, imageUrl: null, available: false },
        { key: 'rear_three_quarter', order: 4, imageUrl: null, available: false },
        { key: 'back', order: 5, imageUrl: null, available: false },
      ],
      quality: { passed: null, uniqueViewHashes: 1, issues: [] },
    },
  ],
  rawText: '沈砚之与王景略在书房对峙。',
});

const actions = () => ({
  onRefresh: vi.fn(),
  onRegenerate: vi.fn(),
  onExport: vi.fn(),
  onContinue: vi.fn(),
});

describe('CharacterDesignerPage asset tab placement and actor naming', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ({
      ok: true,
      json: async () => ({ items: [], page: 1, page_size: 1, total: 0 }),
    }) as Response);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders the asset tabs above the hero header', () => {
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    const tablist = screen.getByRole('tablist', { name: '角色资产类型' });
    const heading = screen.getByRole('heading', { level: 1, name: '沈砚之' });
    const ordering = tablist.compareDocumentPosition(heading);
    expect(ordering & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the selected actor name on the actor tab and the asset label elsewhere', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    expect(screen.getByRole('heading', { level: 1, name: '沈砚之' })).toBeTruthy();

    const library = screen.getByRole('complementary', { name: '角色库' });
    await user.click(within(library).getByRole('button', { name: /王景略/ }));
    expect(screen.getByRole('heading', { level: 1, name: '王景略' })).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: /拍摄场地/ }));
    expect(screen.getByRole('heading', { level: 1, name: '拍摄场地' })).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: /数字演员/ }));
    expect(screen.getByRole('heading', { level: 1, name: '王景略' })).toBeTruthy();
  });

  it('starts on the requested asset tab when opened from the writer stats', () => {
    render(<CharacterDesignerPage dashboard={dashboard} initialAssetKind="scene" {...actions()} />);

    expect(screen.getByRole('tab', { name: /拍摄场地/, selected: true })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: '拍摄场地' })).toBeTruthy();
  });
});
