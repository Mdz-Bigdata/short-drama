// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CharacterDesignerPage } from './CharacterDesignerPage';
import { ACTOR_SHEET_CELL_KEYS, normalizeCharacterDashboard } from './types';

const dashboard = normalizeCharacterDashboard({
  schemaVersion: 'character-dashboard.v1',
  taskId: 'character-task-tabs',
  sourceHash: 'c'.repeat(64),
  title: '雾港角色设定集',
  state: 'READY',
  viewContract: {
    version: 'five-view.v1',
    views: [
      { key: 'front', order: 1, angleDegrees: 0, labelZh: '正面全身', labelEn: 'Front full body' },
      { key: 'profile', order: 2, angleDegrees: 90, labelZh: '侧面全身', labelEn: 'Profile full body' },
      { key: 'back', order: 3, angleDegrees: 180, labelZh: '背面全身', labelEn: 'Back full body' },
      { key: 'face_front', order: 4, angleDegrees: 0, labelZh: '正脸特写', labelEn: 'Face front close-up' },
      { key: 'face_three_quarter', order: 5, angleDegrees: 45, labelZh: '3-4侧脸', labelEn: 'Face three-quarter' },
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
      sheetUrl: 'https://img.test/shen-actor-sheet.png',
      views: [
        { key: 'front', order: 1, imageUrl: 'https://img.test/front.png', available: true },
        { key: 'profile', order: 2, imageUrl: 'https://img.test/profile.png', available: true },
        { key: 'back', order: 3, imageUrl: 'https://img.test/back.png', available: true },
        { key: 'face_front', order: 4, imageUrl: 'https://img.test/face-front.png', available: true },
        { key: 'face_three_quarter', order: 5, imageUrl: 'https://img.test/face-34.png', available: true },
      ],
      // 25 格拆分资产齐全：「细节」页签展示其中的元素拆解 8 格 + 细节矩阵 12 格。
      sheetCells: ACTOR_SHEET_CELL_KEYS.map((key, index) => ({
        key,
        order: index + 1,
        imageUrl: `https://img.test/cell-${key}.png`,
      })),
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
        { key: 'profile', order: 2, imageUrl: null, available: false },
        { key: 'back', order: 3, imageUrl: null, available: false },
        { key: 'face_front', order: 4, imageUrl: null, available: false },
        { key: 'face_three_quarter', order: 5, imageUrl: null, available: false },
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

describe('CharacterDesignerPage actor sheet detail tab', () => {
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

  it('shows six identity views: three faces, then three full bodies', () => {
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    const tablist = screen.getByRole('tablist', { name: '沈砚之 身份视图' });
    expect(within(tablist).getAllByRole('tab').map(tab => tab.textContent)).toEqual([
      '正脸特写0°',
      '3-4侧脸45°',
      '右侧45°侧脸45°',
      '正面全身0°',
      '侧面全身90°',
      '背面全身180°',
    ]);
    // 右侧 45° 取自设定集格子，不是五个身份锚点之一。
    expect(within(tablist).getByRole('tab', { name: /右侧45°侧脸/ }).querySelector('img')?.getAttribute('src'))
      .toBe('https://img.test/cell-face_three_quarter_right.png');
  });

  it('tags a mirrored right 45° face as a fill', () => {
    const mirrored = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? {
          ...character,
          sheetCells: character.sheetCells.map(cell => cell.key === 'face_three_quarter_right'
            ? { ...cell, derivedFrom: 'face_three_quarter' as const }
            : cell),
        }
        : character),
    };
    render(<CharacterDesignerPage dashboard={mirrored} {...actions()} />);
    const tab = within(screen.getByRole('tablist', { name: '沈砚之 身份视图' })).getByRole('tab', { name: /右侧45°侧脸/ });
    expect(within(tab).getByText('补位').getAttribute('title')).toContain('水平翻转');
  });

  it('regenerates one character after confirmation', async () => {
    const user = userEvent.setup();
    const onRegenerateCharacter = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} onRegenerateCharacter={onRegenerateCharacter} />);
    await user.click(screen.getByRole('button', { name: '重新生成沈砚之的设定集' }));
    expect(confirm).toHaveBeenCalled();
    expect(onRegenerateCharacter).toHaveBeenCalledWith('沈砚之', 'sheet');
    await user.click(screen.getByRole('button', { name: '为沈砚之生成高清身份视图' }));
    expect(onRegenerateCharacter).toHaveBeenLastCalledWith('沈砚之', 'hd');
    confirm.mockRestore();
  });

  it('regenerates the selected actor or every actor from the 数字演员 toolbar', async () => {
    const user = userEvent.setup();
    const onRegenerate = vi.fn();
    const onRegenerateCharacter = vi.fn();
    const onRegenerateCharacters = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <CharacterDesignerPage
        dashboard={dashboard}
        {...actions()}
        onRegenerate={onRegenerate}
        onRegenerateCharacter={onRegenerateCharacter}
        onRegenerateCharacters={onRegenerateCharacters}
      />,
    );
    const toolbar = screen.getByLabelText('角色设计工作流操作');
    await user.click(within(toolbar).getByRole('button', { name: /重新生成「沈砚之」/ }));
    expect(onRegenerateCharacter).toHaveBeenCalledWith('沈砚之', 'sheet');

    await user.click(within(toolbar).getByRole('button', { name: /全部重新生成/ }));
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('全部 2 名数字演员'));
    expect(onRegenerateCharacters).toHaveBeenCalledWith(['沈砚之', '王景略']);

    // 「生成缺失图片」仍是重跑第 3 阶段，只补缺图或未通过质检的角色。
    await user.click(within(toolbar).getByRole('button', { name: /生成缺失图片/ }));
    expect(onRegenerate).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
  });

  it('skips actors already regenerating and does nothing when the user cancels', async () => {
    const user = userEvent.setup();
    const onRegenerateCharacters = vi.fn();
    const running = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? { ...character, regenerating: true }
        : character),
    };
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<CharacterDesignerPage dashboard={running} {...actions()} onRegenerateCharacter={vi.fn()} onRegenerateCharacters={onRegenerateCharacters} />);
    const toolbar = screen.getByLabelText('角色设计工作流操作');
    await user.click(within(toolbar).getByRole('button', { name: /全部重新生成/ }));
    expect(onRegenerateCharacters).not.toHaveBeenCalled();
    await user.click(within(toolbar).getByRole('button', { name: /全部重新生成/ }));
    expect(onRegenerateCharacters).toHaveBeenCalledWith(['王景略']);
    expect(within(screen.getByRole('region', { name: '角色列表，可上下滚动' })).getByText('重新生成中')).toBeTruthy();
    confirm.mockRestore();
  });

  it('shows a running regeneration and the reason a previous one failed', () => {
    const running = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? { ...character, regenerating: true }
        : character),
    };
    const { unmount } = render(<CharacterDesignerPage dashboard={running} {...actions()} onRegenerateCharacter={vi.fn()} />);
    const button = screen.getByRole('button', { name: '重新生成沈砚之的设定集' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain('设定集生成中');
    unmount();

    const failed = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? { ...character, regenerationError: '设定集质检失败：空白格' }
        : character),
    };
    render(<CharacterDesignerPage dashboard={failed} {...actions()} onRegenerateCharacter={vi.fn()} />);
    expect(screen.getByRole('alert').textContent).toContain('空白格');
  });

  it('shows the element and detail cells behind the 细节 tab, grouped 元素拆解 and 细节矩阵', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    await user.click(screen.getByRole('tab', { name: /细节/ }));

    const elements = screen.getByRole('region', { name: '元素拆解 8 格' });
    expect(within(elements).getAllByRole('button')).toHaveLength(8);
    expect(within(elements).getByRole('img', { name: '沈砚之 鞋履' })).toBeTruthy();
    expect(within(elements).getByRole('img', { name: '沈砚之 裙摆刺绣' })).toBeTruthy();

    const matrix = screen.getByRole('region', { name: '细节矩阵 12 格' });
    expect(within(matrix).getAllByRole('button')).toHaveLength(12);
    expect(within(matrix).getByRole('img', { name: '沈砚之 后脑发饰' })).toBeTruthy();
    expect(within(matrix).getByRole('img', { name: '沈砚之 动态姿态配件' })).toBeTruthy();

    // 身份视图选择器让位给细节面板，但切回去仍在。
    await user.click(screen.getByRole('tab', { name: '身份视图' }));
    expect(screen.getByRole('tablist', { name: '沈砚之 身份视图' })).toBeTruthy();
  });

  it('lists only the cells the model actually drew in the 细节 tab', async () => {
    const user = userEvent.setup();
    const drawn = new Set(['element_shoe', 'element_waist', 'face_back_hair', 'detail_eye']);
    const partial = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? {
          ...character,
          sheetCells: character.sheetCells.map(cell => drawn.has(cell.key) || cell.group !== 'elements' && cell.group !== 'detail_matrix'
            ? cell
            : { ...cell, imageUrl: null, available: false }),
        }
        : character),
    };
    render(<CharacterDesignerPage dashboard={partial} {...actions()} />);

    await user.click(screen.getByRole('tab', { name: /细节/ }));

    const elements = screen.getByRole('region', { name: '元素拆解 2 格' });
    expect(within(elements).getAllByRole('button')).toHaveLength(2);
    const matrix = screen.getByRole('region', { name: '细节矩阵 2 格' });
    expect(within(matrix).getAllByRole('button')).toHaveLength(2);
    expect(within(matrix).queryByText('前襟胸部纹样')).toBeNull();
  });

  it('fills every cell and tags the ones cropped from an identity panel', async () => {
    const user = userEvent.setup();
    const filled = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? {
          ...character,
          sheetCells: character.sheetCells.map(cell => cell.key === 'element_hem' || cell.key === 'detail_eye'
            ? { ...cell, derivedFrom: cell.key === 'element_hem' ? 'full_body' as const : 'portrait' as const }
            : cell),
        }
        : character),
    };
    render(<CharacterDesignerPage dashboard={filled} {...actions()} />);
    await user.click(screen.getByRole('tab', { name: /细节/ }));

    const elements = screen.getByRole('region', { name: '元素拆解 8 格' });
    const hem = within(elements).getByRole('button', { name: '查看沈砚之裙摆刺绣大图' });
    expect(within(hem).getByText('补位').getAttribute('title')).toContain('正面全身立绘');
    expect(within(elements).getAllByText('补位')).toHaveLength(1);
    const matrix = screen.getByRole('region', { name: '细节矩阵 12 格' });
    expect(within(matrix).getByText('补位').getAttribute('title')).toContain('大正面近景');
  });

  it('offers to really draw the 补位 detail cells from the 细节 tab and the profile', async () => {
    const user = userEvent.setup();
    const onRegenerateCharacter = vi.fn();
    const filled = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? {
          ...character,
          sheetCells: character.sheetCells.map(cell => ['element_fabric', 'element_hand', 'face_three_quarter_right'].includes(cell.key)
            ? { ...cell, derivedFrom: cell.key === 'face_three_quarter_right' ? 'face_three_quarter' as const : 'full_body' as const }
            : cell),
        }
        : character),
    };
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<CharacterDesignerPage dashboard={filled} {...actions()} onRegenerateCharacter={onRegenerateCharacter} />);
    await user.click(screen.getByRole('tab', { name: /细节/ }));

    // 右侧 45° 侧脸的镜像补位归高清身份视图管，不算在补画里。
    const fill = screen.getByRole('button', { name: '为沈砚之补画补位细节格' });
    expect(fill.textContent).toContain('补画 2 格');
    await user.click(fill);
    expect(onRegenerateCharacter).not.toHaveBeenCalled();
    await user.click(fill);
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('付费出图'));
    expect(onRegenerateCharacter).toHaveBeenCalledWith('沈砚之', 'details');

    await user.click(screen.getByRole('button', { name: '为沈砚之补画细节格' }));
    expect(onRegenerateCharacter).toHaveBeenLastCalledWith('沈砚之', 'details');
    confirm.mockRestore();
  });

  it('hides the detail fill when nothing is a 补位 crop or while regenerating', async () => {
    const user = userEvent.setup();
    const running = {
      ...dashboard,
      characters: dashboard.characters.map((character, index) => index === 0
        ? {
          ...character,
          regenerating: true,
          sheetCells: character.sheetCells.map(cell => cell.key === 'element_fabric' ? { ...cell, derivedFrom: 'full_body' as const } : cell),
        }
        : character),
    };
    const { unmount } = render(<CharacterDesignerPage dashboard={dashboard} {...actions()} onRegenerateCharacter={vi.fn()} />);
    await user.click(screen.getByRole('tab', { name: /细节/ }));
    expect(screen.queryByRole('button', { name: '为沈砚之补画补位细节格' })).toBeNull();
    unmount();

    render(<CharacterDesignerPage dashboard={running} {...actions()} onRegenerateCharacter={vi.fn()} />);
    await user.click(screen.getByRole('tab', { name: /细节/ }));
    expect((screen.getByRole('button', { name: '为沈砚之补画补位细节格' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('细节格正在后台补画，完成后自动刷新。')).toBeTruthy();
  });

  it('keeps the whole sheet viewable next to the split cells', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    await user.click(screen.getByRole('button', { name: '查看沈砚之设定集整板大图' }));

    const dialog = screen.getByRole('dialog', { name: '沈砚之 · 设定集整板' });
    expect(within(dialog).getByRole('img', { name: '沈砚之 设定集整板大图' }).getAttribute('src'))
      .toBe('https://img.test/shen-actor-sheet.png');
  });

  it('hides the 细节 tab for a legacy record with no split cells', async () => {
    const user = userEvent.setup();
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);

    const library = screen.getByRole('complementary', { name: '角色库' });
    await user.click(within(library).getByRole('button', { name: /王景略/ }));

    expect(screen.queryByRole('tab', { name: /细节/ })).toBeNull();
  });
});

describe('CharacterDesignerPage screenplay actor extraction', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function mockFetch(importBody: Record<string, unknown>) {
    return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/production-assets/')) {
        return { ok: true, json: async () => importBody } as Response;
      }
      expect(init?.method ?? 'GET').toBe('GET');
      return { ok: true, json: async () => ({ items: [], page: 1, page_size: 1, total: 0 }) } as Response;
    });
  }

  it('imports the screenplay cast and reports how many arrived with images', async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch({ created: 3, skipped: 1, with_image: 2 });
    const handlers = actions();
    render(<CharacterDesignerPage dashboard={dashboard} taskId="task-9" {...handlers} />);

    await user.click(screen.getByRole('button', { name: /从剧本提取演员/ }));

    expect(await screen.findByText(/已从剧本提取 3 位演员，其中 2 位带参考图，跳过 1 位已存在演员。/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/drama/task-9/production-assets/actor/import',
      expect.objectContaining({ method: 'POST' }),
    );
    // A successful import must refresh the dashboard so new actors show up.
    expect(handlers.onRefresh).toHaveBeenCalled();
  });

  it('explains an image-free import instead of implying failure', async () => {
    const user = userEvent.setup();
    mockFetch({ created: 2, skipped: 0, with_image: 0 });
    render(<CharacterDesignerPage dashboard={dashboard} taskId="task-9" {...actions()} />);

    await user.click(screen.getByRole('button', { name: /从剧本提取演员/ }));

    expect(await screen.findByText(/已从剧本提取 2 位演员，暂无参考图，可上传或重新生成。/)).toBeTruthy();
  });

  it('surfaces a failed extraction without clearing the workspace', async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/production-assets/')) {
        return { ok: false, status: 500, json: async () => ({ detail: 'boom' }) } as Response;
      }
      return { ok: true, json: async () => ({ items: [], page: 1, page_size: 1, total: 0 }) } as Response;
    });
    render(<CharacterDesignerPage dashboard={dashboard} taskId="task-9" {...actions()} />);

    await user.click(screen.getByRole('button', { name: /从剧本提取演员/ }));

    expect(await screen.findByText(/从剧本提取演员失败/)).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: '沈砚之' })).toBeTruthy();
  });

  it('hides the extraction action when the page has no task context', () => {
    render(<CharacterDesignerPage dashboard={dashboard} {...actions()} />);
    expect(screen.queryByRole('button', { name: /从剧本提取演员/ })).toBeNull();
  });
});
