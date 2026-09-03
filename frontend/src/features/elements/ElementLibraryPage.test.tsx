// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(settle => { resolve = settle; });
  return { promise, resolve };
}


const elementLibraryStylesheet = readFileSync(
  resolve(process.cwd(), 'src/features/elements/ElementLibraryPage.css'),
  'utf8',
);


function makeSpatialAsset(kind: 'scene' | 'prop', index: number) {
  const label = kind === 'scene' ? '场景' : '道具';
  return {
    id: `${kind}-${index}`,
    kind,
    name: `${label}${String(index).padStart(2, '0')}`,
    description: `${label}${index}的空间、材质与连续性描述`,
    status: 'ready',
    version: 2,
    metadata: {},
    files: [{
      id: `${kind}-${index}-reference`,
      slot: 'reference',
      mime_type: 'image/png',
      media_kind: 'image' as const,
      size_bytes: 2048,
      sha256: `${kind}-${index}-sha`,
      url: `/media/elements/${kind}-${index}.png`,
    }],
    model3d: null,
  };
}


describe('ElementLibraryPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
  });

  it('provides all five concrete pages and keeps costume assets image-only', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], page: 1, page_size: 24, total: 0 }),
    } as Response);
    const { container } = render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /演员元素库/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加演员' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /上传/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: '场景' }));
    expect(await screen.findByRole('heading', { name: /场景元素库/ })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '添加场景' }).length).toBeGreaterThan(0);
    const workspace = await screen.findByRole('region', { name: '场景 3D 资产工作台' });
    const scrollList = within(workspace).getByRole('region', { name: '场景资产列表，可上下滚动' });
    expect(scrollList.getAttribute('tabindex')).toBe('0');

    await userEvent.click(screen.getByRole('tab', { name: '服装' }));
    expect(await screen.findByRole('heading', { name: /服装元素库/ })).toBeTruthy();
    expect(screen.getAllByRole('tab')).toHaveLength(5);
    expect(screen.getByRole('button', { name: '添加服装' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '上传' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '上传 3D 模型' })).toBeNull();
    expect(container.querySelector('input[accept*=".glb"]')).toBeNull();
  });

  it('gives every effect card an accessible effect name and its related description', async () => {
    const effect = {
      id: 'effect-lightning',
      kind: 'effect' as const,
      name: '雷光贯穿石阶',
      description: '一道冷白雷光劈落，碎石与青蓝电弧向四周迸散，持续约一秒后熄灭。',
      status: 'ready',
      version: 2,
      metadata: {},
      files: [{
        id: 'effect-lightning-reference', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 4096, sha256: 'effect-lightning-sha', url: '/media/elements/effect-lightning.png',
      }],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [effect], page: 1, page_size: 50, total: 1 }),
    } as Response);

    render(<ElementLibraryPage initialKind="effect" embedded />);

    const card = await screen.findByRole('article', { name: '特效资产“雷光贯穿石阶”' });
    expect(within(card).getByRole('heading', { name: '雷光贯穿石阶' })).toBeTruthy();
    expect(within(card).getByText(effect.description)).toBeTruthy();
  });

  it('opens a complete costume panorama and zooms around the clicked detail position', async () => {
    const costume = {
      id: 'costume-black-robe',
      kind: 'costume' as const,
      name: '玄黑官袍大氅',
      description: '玄黑提花官袍配宽肩大氅，银线暗纹沿衣襟延伸，展示完整正面轮廓与下摆。',
      status: 'ready',
      version: 3,
      metadata: {},
      files: [{
        id: 'costume-black-robe-reference', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 8192, sha256: 'costume-black-robe-sha', url: '/media/elements/costume-black-robe.png',
      }],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [costume], page: 1, page_size: 50, total: 1 }),
    } as Response);
    const stylesheet = document.createElement('style');
    stylesheet.textContent = elementLibraryStylesheet;
    document.head.append(stylesheet);

    try {
      render(<ElementLibraryPage initialKind="costume" embedded />);

      const card = await screen.findByRole('article', { name: '服装资产“玄黑官袍大氅”' });
      expect(within(card).getByText(costume.description)).toBeTruthy();
      const openButton = within(card).getByRole('button', { name: '查看服装资产“玄黑官袍大氅”全景图' });
      const cardImage = within(openButton).getByRole('img', { name: '玄黑官袍大氅 参考图' });
      expect(getComputedStyle(cardImage).objectFit).toBe('contain');

      await userEvent.click(openButton);
      const dialog = screen.getByRole('dialog', { name: '玄黑官袍大氅 · 服装全景细节' });
      expect(within(dialog).getByText(costume.description)).toBeTruthy();
      expect(within(dialog).getByRole('status', { name: '当前缩放比例' }).textContent).toBe('1.0×');

      const detailStage = within(dialog).getByRole('button', { name: '点击服装全景图局部放大' });
      vi.spyOn(detailStage, 'getBoundingClientRect').mockReturnValue({
        x: 0, y: 0, left: 0, top: 0, right: 1000, bottom: 500, width: 1000, height: 500,
        toJSON: () => ({}),
      });
      fireEvent.click(detailStage, { clientX: 250, clientY: 375 });

      expect(within(dialog).getByRole('status', { name: '当前缩放比例' }).textContent).toBe('1.5×');
      expect(within(dialog).getByText('观察位置 X 25% · Y 75%')).toBeTruthy();
      const detailImage = within(detailStage).getByRole('img', { name: '玄黑官袍大氅 服装全景图' });
      expect(detailImage.style.transform).toBe('scale(1.5)');
      expect(detailImage.style.transformOrigin).toBe('25% 75%');

      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('dialog', { name: '玄黑官袍大氅 · 服装全景细节' })).toBeNull();
      await waitFor(() => expect(document.activeElement).toBe(openButton));
    } finally {
      stylesheet.remove();
    }
  });

  it.each([
    ['scene' as const, '场景', '太常寺天文台', '夜，内景，青石阶、星盘与司天仪'],
    ['prop' as const, '道具', '竹筒', '绑于腰间，内藏密信，筒身有旧铜扣'],
  ])('shows the selected %s reference image and description in the center stage', async (kind, label, name, description) => {
    const asset = {
      ...makeSpatialAsset(kind, 1),
      name,
      description,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [asset], page: 1, page_size: 50, total: 1 }),
    } as Response);

    render(<ElementLibraryPage initialKind={kind} onBack={() => undefined} />);

    const preview = await screen.findByRole('region', { name: `${label}资产“${name}”参考预览` });
    expect(within(preview).getByRole('img', { name: `${name} 参考图` })).toBeTruthy();
    expect(within(preview).getByText(description)).toBeTruthy();
  });

  it.each([
    ['scene' as const, '场景', 25],
    ['prop' as const, '道具', 29],
  ])('keeps all %s assets in a bounded vertical scroll rail', async (kind, label, count) => {
    const assets = Array.from({ length: count }, (_, index) => makeSpatialAsset(kind, index + 1));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: assets, page: 1, page_size: 50, total: count }),
    } as Response);
    const stylesheet = document.createElement('style');
    stylesheet.textContent = elementLibraryStylesheet;
    document.head.append(stylesheet);

    try {
      render(<ElementLibraryPage initialKind={kind} onBack={() => undefined} />);

      const workspace = await screen.findByRole('region', { name: `${label} 3D 资产工作台` });
      const scrollList = within(workspace).getByRole('region', { name: `${label}资产列表，可上下滚动` });
      expect(within(scrollList).getAllByRole('button', { name: new RegExp(`查看${label}资产`) })).toHaveLength(count);
      expect(within(scrollList).getByRole('button', { name: `查看${label}资产“${label}${count}”` })).toBeTruthy();

      const rail = scrollList.closest('.asset-rail');
      const firstItem = scrollList.querySelector('.asset-rail-item');
      expect(rail).not.toBeNull();
      expect(firstItem).not.toBeNull();
      expect(getComputedStyle(rail as Element).minHeight).toBe('0px');
      expect(getComputedStyle(rail as Element).overflow).toBe('hidden');
      expect(getComputedStyle(scrollList).overflowY).toBe('auto');
      expect(getComputedStyle(firstItem as Element).flexShrink).toBe('0');
    } finally {
      stylesheet.remove();
    }
  });

  it('embeds one asset page without duplicate portal chrome and reports server totals after mutations', async () => {
    const createdCostume = {
      id: 'costume-1', kind: 'costume' as const, name: '雨夜巡警制服', description: '防雨长外套', status: 'draft',
      version: 1, metadata: {}, files: [], model3d: null,
    };
    let created = false;
    const onCountChange = vi.fn();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        created = true;
        return { ok: true, json: async () => createdCostume } as Response;
      }
      if (url.includes('/api/elements?kind=costume')) {
        return {
          ok: true,
          json: async () => ({ items: created ? [createdCostume] : [], page: 1, page_size: 50, total: created ? 1 : 0 }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const { container } = render(
      <ElementLibraryPage
        initialKind="costume"
        embedded
        onCountChange={onCountChange}
      />,
    );

    expect(await screen.findByText('还没有服装元素')).toBeTruthy();
    expect(container.querySelector('main')).toBeNull();
    expect(screen.queryByRole('button', { name: /返回创作台/ })).toBeNull();
    expect(screen.queryByRole('tablist', { name: '元素类型' })).toBeNull();
    expect(screen.getByRole('region', { name: '服装资产工作区' })).toBeTruthy();
    await waitFor(() => expect(onCountChange).toHaveBeenCalledWith('costume', 0));

    await userEvent.click(screen.getByRole('button', { name: '添加服装' }));
    await userEvent.type(screen.getByPlaceholderText('输入服装名称'), '雨夜巡警制服');
    await userEvent.click(screen.getByRole('button', { name: '保存元素' }));

    expect((await screen.findAllByText('雨夜巡警制服')).length).toBeGreaterThan(0);
    await waitFor(() => expect(onCountChange).toHaveBeenCalledWith('costume', 1));
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('replaces an empty card with the generated private reference image', async () => {
    const emptyCostume = {
      id: 'costume-empty', kind: 'costume' as const, name: '太后朝服', description: '绯红凤袍与金线云纹',
      status: 'draft', version: 1, metadata: {}, files: [], model3d: null,
    };
    const generatedCostume = {
      ...emptyCostume,
      status: 'ready',
      version: 2,
      files: [{
        id: 'costume-reference', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 2048, sha256: 'generated-sha',
        url: '/api/elements/costume-empty/files/costume-reference/content?v=2',
      }],
    };
    let generated = false;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements/costume-empty/regenerate') && options?.method === 'POST') {
        generated = true;
        return { ok: true, json: async () => generatedCostume } as Response;
      }
      if (url.includes('/api/elements?kind=costume')) {
        return {
          ok: true,
          json: async () => ({ items: [generated ? generatedCostume : emptyCostume], total: 1 }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });

    render(<ElementLibraryPage initialKind="costume" onBack={() => undefined} />);

    expect((await screen.findAllByText('太后朝服')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('img', { name: '太后朝服 参考图' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '重新生成' }));

    expect(await screen.findByRole('img', { name: '太后朝服 参考图' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('已重新生成“太后朝服”的参考图');
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/elements?kind=costume'))).toHaveLength(2);
  });

  it('runs a category generation job and reloads every missing reference image', async () => {
    const emptyEffect = {
      id: 'effect-empty', kind: 'effect' as const, name: '铁门缓缓开启', description: '门轴摩擦扬尘',
      status: 'draft', version: 1, metadata: { task_id: 'task-effects' }, files: [], model3d: null,
    };
    const readyEffect = {
      ...emptyEffect,
      status: 'ready',
      version: 2,
      files: [{
        id: 'effect-reference', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 4096, sha256: 'effect-sha',
        url: '/api/elements/effect-empty/files/effect-reference/content?v=2',
      }],
    };
    let completed = false;
    const onGenerationStateChange = vi.fn();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements/generation-jobs') && options?.method === 'POST') {
        expect(JSON.parse(String(options.body))).toEqual({ kind: 'effect', task_id: 'task-effects' });
        return {
          ok: true,
          json: async () => ({
            id: 'generation-job-1', kind: 'effect', status: 'queued', total: 1,
            processed: 0, succeeded: 0, failed: 0, remaining: 1, errors: [],
          }),
        } as Response;
      }
      if (url.endsWith('/api/elements/generation-jobs/generation-job-1')) {
        completed = true;
        return {
          ok: true,
          json: async () => ({
            id: 'generation-job-1', kind: 'effect', status: 'completed', total: 1,
            processed: 1, succeeded: 1, failed: 0, remaining: 0, errors: [],
          }),
        } as Response;
      }
      if (url.includes('/api/elements?kind=effect')) {
        return {
          ok: true,
          json: async () => ({ items: [completed ? readyEffect : emptyEffect], total: 1 }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { rerender } = render(
      <ElementLibraryPage
        initialKind="effect"
        embedded
        taskId="task-effects"
        regenerateAllToken={0}
        onGenerationStateChange={onGenerationStateChange}
      />,
    );
    expect((await screen.findAllByText('铁门缓缓开启')).length).toBeGreaterThan(0);

    rerender(
      <ElementLibraryPage
        initialKind="effect"
        embedded
        taskId="task-effects"
        regenerateAllToken={1}
        onGenerationStateChange={onGenerationStateChange}
      />,
    );

    expect(await screen.findByRole('img', { name: '铁门缓缓开启 参考图' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('1 项特效参考图已生成完整');
    expect(onGenerationStateChange).toHaveBeenCalledWith(true);
    expect(onGenerationStateChange).toHaveBeenLastCalledWith(false);
    expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/api/elements/generation-jobs') && init?.method === 'POST'
    ))).toBe(true);
  });

  it('reveals and focuses the create form when the empty scene stage adds its first asset', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], page: 1, page_size: 50, total: 0 }),
    } as Response);
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    render(<ElementLibraryPage initialKind="scene" onBack={() => undefined} />);

    const workspace = await screen.findByRole('region', { name: '场景 3D 资产工作台' });
    await userEvent.click(within(workspace).getByRole('button', { name: '添加场景' }));

    const nameInput = await screen.findByPlaceholderText('输入场景名称');
    await waitFor(() => expect(document.activeElement).toBe(nameInput));
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
  });

  it('deletes a selected reference image while keeping its asset available', async () => {
    const poster = {
      id: 'poster-1', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 1_024, sha256: 'poster-sha', url: '/media/elements/poster.png',
    };
    const prop = {
      id: 'prop-1', kind: 'prop' as const, name: '旧怀表', description: '铜制道具', status: 'ready',
      version: 2, metadata: {}, files: [poster], model3d: null,
    };
    let current = prop;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements/prop-1/files/poster-1') && options?.method === 'DELETE') {
        current = { ...prop, version: 3, files: [] };
        return { ok: true, json: async () => current } as Response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        return { ok: true, json: async () => ({ items: [current], page: 1, page_size: 50, total: 1 }) } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('img', { name: '旧怀表 参考图' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '删除参考图' }));

    await waitFor(() => expect(screen.queryByRole('img', { name: '旧怀表 参考图' })).toBeNull());
    expect(screen.getAllByText('旧怀表').length).toBeGreaterThan(0);
    expect(screen.getByRole('status').textContent).toContain('已删除“旧怀表”的参考图');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: '上传参考图' })));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('旧怀表'));
    expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/api/elements/prop-1/files/poster-1') && init?.method === 'DELETE'
    ))).toBe(true);
  });

  it('identifies destructive actions by asset name when multiple cards are visible', async () => {
    const makeActor = (id: string, name: string) => ({
      id,
      kind: 'actor' as const,
      name,
      description: '',
      status: 'draft',
      version: 1,
      metadata: {},
      files: [{
        id: `${id}-poster`,
        slot: 'front',
        mime_type: 'image/png',
        media_kind: 'image' as const,
        size_bytes: 512,
        sha256: `${id}-sha`,
        url: `/media/elements/${id}.png`,
      }],
      model3d: null,
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [makeActor('actor-shen', '沈知微'), makeActor('actor-lu', '陆行远')],
        page: 1,
        page_size: 50,
        total: 2,
      }),
    } as Response);

    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    expect(await screen.findByRole('button', { name: '删除“沈知微”的正面视图' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除演员资产“沈知微”' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除“陆行远”的正面视图' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除演员资产“陆行远”' })).toBeTruthy();
  });

  it('confirms and deletes the selected asset with a locked destructive action', async () => {
    const prop = {
      id: 'prop-delete', kind: 'prop' as const, name: '废弃道具', description: '', status: 'draft',
      version: 1, metadata: {}, files: [], model3d: null,
    };
    const deletion = deferred<Response>();
    let deleted = false;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements/prop-delete') && options?.method === 'DELETE') {
        const response = await deletion.promise;
        deleted = true;
        return response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        return {
          ok: true,
          json: async () => ({ items: deleted ? [] : [prop], page: 1, page_size: 50, total: deleted ? 0 : 1 }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect((await screen.findAllByText('废弃道具')).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button', { name: '删除资产' }));
    expect((screen.getByRole('button', { name: '正在删除资产' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '添加道具' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '上传参考图' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByRole('button', { name: '上传 3D 模型' }).every(button => (button as HTMLButtonElement).disabled)).toBe(true);

    const modelInput = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    await userEvent.upload(modelInput!, new File(['blocked'], 'must-not-upload.glb', { type: 'model/gltf-binary' }));
    expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/api/elements/prop-delete/model') && init?.method === 'POST'
    ))).toBe(false);

    await act(async () => {
      deletion.resolve({ ok: true, json: async () => ({ deleted: true, id: 'prop-delete' }) } as Response);
      await deletion.promise;
    });

    expect(await screen.findByText('还没有道具资产')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('已删除道具资产“废弃道具”');
    await waitFor(() => expect(document.activeElement).toBe(screen.getAllByRole('button', { name: '添加道具' })[0]));
    expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/api/elements/prop-delete') && init?.method === 'DELETE'
    ))).toBe(true);
  });

  it('uploads a GLB through the dedicated scene model endpoint', async () => {
    const item = {
      id: 'scene-1',
      kind: 'scene',
      name: '雨夜巷口',
      description: '狭窄巷道与霓虹灯牌',
      status: 'ready',
      version: 1,
      metadata: {},
      files: [],
      model3d: null,
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, options) => ({
      ok: true,
      json: async () => options?.method === 'POST' ? item : ({ items: [item], page: 1, page_size: 50, total: 1 }),
    } as Response));
    const { container } = render(<ElementLibraryPage initialKind="scene" onBack={() => undefined} />);

    expect((await screen.findAllByText('雨夜巷口')).length).toBeGreaterThan(0);
    const input = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    expect(input).toBeTruthy();
    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(input!, new File(['glTF-fixture'], 'alley.glb', { type: 'model/gltf-binary' }));

    await waitFor(() => {
      const upload = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/api/elements/scene-1/model') && init?.method === 'POST');
      expect(upload).toBeTruthy();
      expect(upload?.[1]?.body).toBeInstanceOf(FormData);
      expect((upload?.[1]?.body as FormData).get('file')).toBeInstanceOf(File);
    });
  });

  it('queues a GLB for an empty prop library, creates the prop, then uploads the model', async () => {
    const createdProp = {
      id: 'prop-new',
      kind: 'prop',
      name: '黄铜怀表',
      description: '贯穿全剧的关键道具',
      status: 'draft',
      version: 1,
      metadata: {},
      files: [],
      model3d: null,
    };
    let propCreated = false;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        propCreated = true;
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.endsWith('/api/elements/prop-new/model') && options?.method === 'POST') {
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        return {
          ok: true,
          json: async () => ({
            items: propCreated ? [createdProp] : [],
            page: 1,
            page_size: 50,
            total: propCreated ? 1 : 0,
          }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();
    const modelInput = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    expect(modelInput).toBeTruthy();

    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['glTF-fixture'], 'pocket-watch.glb', { type: 'model/gltf-binary' }));

    expect(screen.queryByText(/请先添加.*再上传/)).toBeNull();
    expect(await screen.findByText(/pocket-watch\.glb/)).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText('输入道具名称'), '黄铜怀表');
    await userEvent.type(screen.getByPlaceholderText('身份、状态、材质、空间或效果约束'), '贯穿全剧的关键道具');
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));

    await waitFor(() => {
      const createIndex = fetchMock.mock.calls.findIndex(([url, init]) => String(url).endsWith('/api/elements') && init?.method === 'POST');
      const modelIndex = fetchMock.mock.calls.findIndex(([url, init]) => String(url).endsWith('/api/elements/prop-new/model') && init?.method === 'POST');
      expect(createIndex).toBeGreaterThanOrEqual(0);
      expect(modelIndex).toBeGreaterThan(createIndex);
      expect(fetchMock.mock.calls[modelIndex]?.[1]?.body).toBeInstanceOf(FormData);
      expect((fetchMock.mock.calls[modelIndex]?.[1]?.body as FormData).get('file')).toBeInstanceOf(File);
    });
  });

  it('queues a reference image for an empty prop library and uploads it after creation', async () => {
    const createdProp = {
      id: 'prop-with-poster',
      kind: 'prop',
      name: '旧车票',
      description: '',
      status: 'draft',
      version: 1,
      metadata: {},
      files: [],
      model3d: null,
    };
    let propCreated = false;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        propCreated = true;
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.endsWith('/api/elements/prop-with-poster/files') && options?.method === 'POST') {
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        return {
          ok: true,
          json: async () => ({
            items: propCreated ? [createdProp] : [],
            page: 1,
            page_size: 50,
            total: propCreated ? 1 : 0,
          }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();
    const imageInput = container.querySelector<HTMLInputElement>('input[accept*=".png"]');
    expect(imageInput).toBeTruthy();

    await userEvent.click(screen.getAllByRole('button', { name: '上传参考图' })[0]);
    await userEvent.upload(imageInput!, new File(['image-fixture'], 'ticket.png', { type: 'image/png' }));

    expect(screen.queryByText(/请先添加.*再上传/)).toBeNull();
    expect(await screen.findByText(/ticket\.png/)).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText('输入道具名称'), '旧车票');
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));

    await waitFor(() => {
      const createIndex = fetchMock.mock.calls.findIndex(([url, init]) => String(url).endsWith('/api/elements') && init?.method === 'POST');
      const uploadIndex = fetchMock.mock.calls.findIndex(([url, init]) => String(url).endsWith('/api/elements/prop-with-poster/files') && init?.method === 'POST');
      expect(createIndex).toBeGreaterThanOrEqual(0);
      expect(uploadIndex).toBeGreaterThan(createIndex);
      const form = fetchMock.mock.calls[uploadIndex]?.[1]?.body as FormData;
      expect(form).toBeInstanceOf(FormData);
      expect(form.get('slot')).toBe('reference');
      expect(form.get('file')).toBeInstanceOf(File);
    });
  });

  it('keeps the queued file after an upload failure and retries without creating a duplicate asset', async () => {
    const createdProp = {
      id: 'prop-retry',
      kind: 'prop',
      name: '故障怀表',
      description: '',
      status: 'draft',
      version: 1,
      metadata: {},
      files: [],
      model3d: null,
    };
    let propCreated = false;
    let modelAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        propCreated = true;
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.endsWith('/api/elements/prop-retry/model') && options?.method === 'POST') {
        modelAttempts += 1;
        if (modelAttempts <= 2) {
          const detail = modelAttempts === 1 ? '模型存储暂时不可用' : '替换模型仍未上传成功';
          return { ok: false, status: 503, json: async () => ({ detail }) } as Response;
        }
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        return {
          ok: true,
          json: async () => ({
            items: propCreated ? [createdProp] : [],
            page: 1,
            page_size: 50,
            total: propCreated ? 1 : 0,
          }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();
    const modelInput = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['glTF-fixture'], 'retry-watch.glb', { type: 'model/gltf-binary' }));
    await userEvent.type(screen.getByPlaceholderText('输入道具名称'), '故障怀表');
    await userEvent.click(screen.getByRole('button', { name: /保存并上传 3D 模型/ }));

    expect((await screen.findByRole('alert')).textContent).toContain('道具已创建，但模型存储暂时不可用');
    expect(screen.getByText(/retry-watch\.glb/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试上传 3D 模型' })).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/api/elements') && init?.method === 'POST')).toHaveLength(1);

    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['fixed-glTF-fixture'], 'fixed-watch.glb', { type: 'model/gltf-binary' }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('替换模型仍未上传成功'));
    expect(screen.queryByText(/retry-watch\.glb/)).toBeNull();
    expect(screen.getByText(/fixed-watch\.glb/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试上传 3D 模型' })).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: '重试上传 3D 模型' }));

    await waitFor(() => expect(screen.queryByText(/fixed-watch\.glb/)).toBeNull());
    expect(modelAttempts).toBe(3);
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/api/elements') && init?.method === 'POST')).toHaveLength(1);
    const modelCalls = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/api/elements/prop-retry/model') && init?.method === 'POST');
    expect(((modelCalls[0]?.[1]?.body as FormData).get('file') as File).name).toBe('retry-watch.glb');
    expect(((modelCalls[1]?.[1]?.body as FormData).get('file') as File).name).toBe('fixed-watch.glb');
    expect(((modelCalls[2]?.[1]?.body as FormData).get('file') as File).name).toBe('fixed-watch.glb');
  });

  it('does not attach a newer queued file to an older create workflow after switching asset types', async () => {
    const oldCreate = deferred<Response>();
    let createCalls = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        createCalls += 1;
        return oldCreate.promise;
      }
      if (url.endsWith('/api/elements/prop-old/model') && options?.method === 'POST') {
        return { ok: false, status: 503, json: async () => ({ detail: '旧流程上传失败' }) } as Response;
      }
      if (url.includes('/api/elements?')) {
        return { ok: true, json: async () => ({ items: [], page: 1, page_size: 50, total: 0 }) } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();
    const modelInput = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['old'], 'old-watch.glb', { type: 'model/gltf-binary' }));
    await userEvent.type(screen.getByPlaceholderText('输入道具名称'), '旧流程道具');
    await userEvent.click(screen.getByRole('button', { name: /保存并上传 3D 模型/ }));
    await waitFor(() => expect(createCalls).toBe(1));
    expect((screen.getByRole('button', { name: '移除' }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.click(screen.getByRole('tab', { name: '场景' }));
    expect(await screen.findByRole('heading', { name: /场景元素库/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: '道具' }));
    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();

    await act(async () => {
      oldCreate.resolve({
        ok: true,
        json: async () => ({
          id: 'prop-old', kind: 'prop', name: '旧流程道具', description: '', status: 'draft',
          version: 1, metadata: {}, files: [], model3d: null,
        }),
      } as Response);
      await oldCreate.promise;
    });
    await waitFor(() => expect((screen.getAllByRole('button', { name: '上传 3D 模型' })[0] as HTMLButtonElement).disabled).toBe(false));

    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/elements/prop-old/model'))).toBe(false);
    expect(screen.queryByText('旧流程上传失败')).toBeNull();
    expect(screen.queryByRole('button', { name: '重试上传 3D 模型' })).toBeNull();

    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['new'], 'new-watch.glb', { type: 'model/gltf-binary' }));

    expect(await screen.findByText(/new-watch\.glb/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '保存并上传 3D 模型' })).toBeTruthy();
  });

  it('keeps a refresh error visible after creating and uploading the first model', async () => {
    const createdProp = {
      id: 'prop-refresh-error', kind: 'prop', name: '刷新故障道具', description: '', status: 'draft',
      version: 1, metadata: {}, files: [], model3d: null,
    };
    let refreshes = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/elements') && options?.method === 'POST') {
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.endsWith('/api/elements/prop-refresh-error/model') && options?.method === 'POST') {
        return { ok: true, json: async () => createdProp } as Response;
      }
      if (url.includes('/api/elements?kind=prop')) {
        refreshes += 1;
        if (refreshes === 1) {
          return { ok: true, json: async () => ({ items: [], page: 1, page_size: 50, total: 0 }) } as Response;
        }
        return { ok: false, status: 503, json: async () => ({ detail: '元素列表刷新失败' }) } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /道具元素库/ })).toBeTruthy();
    const modelInput = container.querySelector<HTMLInputElement>('input[accept*=".glb"]');
    await userEvent.click(screen.getAllByRole('button', { name: '上传 3D 模型' })[0]);
    await userEvent.upload(modelInput!, new File(['glTF'], 'refresh-error.glb', { type: 'model/gltf-binary' }));
    await userEvent.type(screen.getByPlaceholderText('输入道具名称'), '刷新故障道具');
    await userEvent.click(screen.getByRole('button', { name: /保存并上传 3D 模型/ }));

    expect((await screen.findByRole('alert')).textContent).toContain('元素列表刷新失败');
    expect(screen.queryByText(/refresh-error\.glb/)).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/elements/prop-refresh-error/model'))).toBe(true);
  });

  it('keeps file cancellation and regeneration locked for the whole create workflow', async () => {
    const firstList = deferred<Response>();
    const createResponse = deferred<Response>();
    const existingActor = {
      id: 'actor-existing', kind: 'actor', name: '已有演员', description: '', status: 'draft',
      version: 1, metadata: {}, files: [], model3d: null,
    };
    const createdActor = {
      id: 'actor-new', kind: 'actor', name: '新演员', description: '', status: 'draft',
      version: 1, metadata: {}, files: [], model3d: null,
    };
    let listCalls = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.includes('/api/elements?kind=actor')) {
        listCalls += 1;
        if (listCalls === 1) return firstList.promise;
        return { ok: true, json: async () => ({ items: [existingActor, createdActor], total: 2 }) } as Response;
      }
      if (url.endsWith('/api/elements') && options?.method === 'POST') return createResponse.promise;
      if (url.endsWith('/api/elements/actor-new/files') && options?.method === 'POST') {
        return { ok: true, json: async () => createdActor } as Response;
      }
      if (url.endsWith('/api/elements/actor-existing/regenerate')) {
        throw new Error('regeneration must stay locked while creation is in flight');
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const { container } = render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    const imageInput = container.querySelector<HTMLInputElement>('input[accept*=".png"]');
    await userEvent.click(screen.getByRole('button', { name: '上传' }));
    await userEvent.upload(imageInput!, new File(['portrait'], 'new-actor.png', { type: 'image/png' }));
    expect(await screen.findByText(/new-actor\.png/)).toBeTruthy();

    await act(async () => {
      firstList.resolve({ ok: true, json: async () => ({ items: [existingActor], total: 1 }) } as Response);
      await firstList.promise;
    });
    expect((await screen.findAllByText('已有演员')).length).toBeGreaterThan(0);
    await userEvent.type(screen.getByPlaceholderText('输入演员名称'), '新演员');
    await userEvent.click(screen.getByRole('button', { name: /保存并上传参考图/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/api/elements') && init?.method === 'POST')).toBe(true));

    expect((screen.getByRole('button', { name: '移除' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '添加上传' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '重新生成' }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      createResponse.resolve({ ok: true, json: async () => createdActor } as Response);
      await createResponse.promise;
    });
    await waitFor(() => expect(screen.queryByText(/new-actor\.png/)).toBeNull());
  });

  it('keeps the latest asset type when an earlier list request resolves last', async () => {
    const actorResponse = deferred<Response>();
    const sceneResponse = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
      const url = String(input);
      if (url.includes('kind=actor')) return actorResponse.promise;
      if (url.includes('kind=scene')) return sceneResponse.promise;
      throw new Error(`unexpected URL: ${url}`);
    });
    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('kind=actor'))).toBe(true));
    await userEvent.click(screen.getByRole('tab', { name: '场景' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('kind=scene'))).toBe(true));

    sceneResponse.resolve({
      ok: true,
      json: async () => ({
        items: [{
          id: 'scene-current', kind: 'scene', name: '当前场景', description: '', status: 'draft',
          version: 1, metadata: {}, files: [], model3d: null,
        }],
        total: 1,
      }),
    } as Response);
    expect((await screen.findAllByText('当前场景')).length).toBeGreaterThan(0);

    await act(async () => {
      actorResponse.resolve({
        ok: true,
        json: async () => ({
          items: [{
            id: 'actor-stale', kind: 'actor', name: '过期演员结果', description: '', status: 'draft',
            version: 1, metadata: {}, files: [], model3d: null,
          }],
          total: 1,
        }),
      } as Response);
      await actorResponse.promise;
    });

    expect(screen.getByRole('heading', { name: /场景元素库/ })).toBeTruthy();
    expect(screen.queryByText('过期演员结果')).toBeNull();
    expect(screen.getAllByText('当前场景').length).toBeGreaterThan(0);
  });
});

describe('asset image viewer across all five kinds', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const makeListResponse = (items: unknown[]) => ({
    ok: true,
    json: async () => ({ items, page: 1, page_size: 50, total: items.length }),
  } as Response);

  it('opens the actor view image in the viewer labelled 数字演员 and supports keyboard reopen', async () => {
    const actor = {
      id: 'actor-viewer',
      kind: 'actor' as const,
      name: '沈砚之',
      description: '玄衣束发，左眉有旧疤',
      status: 'ready',
      version: 2,
      metadata: {},
      files: [{
        id: 'actor-front', slot: 'front', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 1024, sha256: 'actor-front-sha', url: '/media/elements/actor-front.png',
      }],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeListResponse([actor]));

    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    const openButton = await screen.findByRole('button', { name: '查看数字演员“沈砚之”的正面视图' });
    await userEvent.click(openButton);

    const dialog = screen.getByRole('dialog', { name: '沈砚之 · 数字演员全景细节' });
    // 逐图放大：弹层描述标注当前查看的是哪一张五视图。
    expect(within(dialog).getByText(/正面视图/)).toBeTruthy();
    expect(within(dialog).getByText(/左眉有旧疤/)).toBeTruthy();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '沈砚之 · 数字演员全景细节' })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(openButton));

    // 键盘可达：入口是原生按钮，Enter 直接开启。
    await userEvent.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: '沈砚之 · 数字演员全景细节' })).toBeTruthy();
  });

  it('hides the actor viewer entry for a five-view slot with no upload', async () => {
    const actor = {
      id: 'actor-partial',
      kind: 'actor' as const,
      name: '陆行远',
      description: '',
      status: 'draft',
      version: 1,
      metadata: {},
      files: [{
        id: 'actor-partial-front', slot: 'front', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 512, sha256: 'actor-partial-sha', url: '/media/elements/actor-partial-front.png',
      }],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeListResponse([actor]));

    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    expect(await screen.findByRole('button', { name: '查看数字演员“陆行远”的正面视图' })).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText(/上传视图/), 'back');
    expect(screen.getByText('背面视图未上传')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /查看数字演员/ })).toBeNull();
  });

  it('opens the scene reference from the centre stage with the 拍摄场地 label via keyboard', async () => {
    const scene = {
      ...makeSpatialAsset('scene', 1),
      name: '金銮殿',
      description: '晨光透过藻井，蟠龙金柱与丹陛台阶',
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeListResponse([scene]));

    render(<ElementLibraryPage initialKind="scene" onBack={() => undefined} />);

    const openButton = await screen.findByRole('button', { name: '查看拍摄场地“金銮殿”全景图' });
    openButton.focus();
    await userEvent.keyboard('{Enter}');

    const dialog = screen.getByRole('dialog', { name: '金銮殿 · 拍摄场地全景细节' });
    expect(within(dialog).getByText(scene.description)).toBeTruthy();
    expect(within(dialog).getByRole('img', { name: '金銮殿 拍摄场地全景图' })).toBeTruthy();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '金銮殿 · 拍摄场地全景细节' })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(openButton));
  });

  it('opens the prop reference with the 拍摄道具 label and offers no entry without an image', async () => {
    const withImage = {
      ...makeSpatialAsset('prop', 1),
      name: '青铜司南',
      description: '掌心大小，盘面刻二十八宿',
    };
    const withoutImage = { ...makeSpatialAsset('prop', 2), name: '无图令牌', files: [] };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeListResponse([withImage, withoutImage]));

    render(<ElementLibraryPage initialKind="prop" onBack={() => undefined} />);

    const openButton = await screen.findByRole('button', { name: '查看拍摄道具“青铜司南”全景图' });
    await userEvent.click(openButton);
    const dialog = screen.getByRole('dialog', { name: '青铜司南 · 拍摄道具全景细节' });
    expect(within(dialog).getByText(withImage.description)).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(document.activeElement).toBe(openButton));

    // 无参考图的资产只有上传引导，不出现放大入口。
    await userEvent.click(screen.getByRole('button', { name: '查看道具资产“无图令牌”' }));
    expect(await screen.findByText(/无图令牌 尚无参考图或 3D 模型/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /查看拍摄道具“无图令牌”/ })).toBeNull();
  });

  it('opens the effect detail image in the viewer labelled 特效', async () => {
    const effect = {
      id: 'effect-viewer',
      kind: 'effect' as const,
      name: '火折子爆燃',
      description: '橙红火舌腾起半尺，火星向四周迸散',
      status: 'ready',
      version: 1,
      metadata: {},
      files: [{
        id: 'effect-viewer-reference', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const,
        size_bytes: 2048, sha256: 'effect-viewer-sha', url: '/media/elements/effect-viewer.png',
      }],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeListResponse([effect]));

    render(<ElementLibraryPage initialKind="effect" embedded />);

    const openButton = await screen.findByRole('button', { name: '查看特效资产“火折子爆燃”细节图' });
    await userEvent.click(openButton);

    const dialog = screen.getByRole('dialog', { name: '火折子爆燃 · 特效全景细节' });
    expect(within(dialog).getByText(effect.description)).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '火折子爆燃 · 特效全景细节' })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(openButton));
  });
});

describe('actor five-view preview switching', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows the image of whichever view the slot selector names', async () => {
    const actor = {
      id: 'actor-views',
      kind: 'actor' as const,
      name: '沈砚之',
      description: '',
      status: 'draft',
      version: 2,
      metadata: {},
      files: [
        { id: 'f-front', slot: 'front', mime_type: 'image/png', media_kind: 'image' as const, size_bytes: 1, sha256: 'a', url: '/media/elements/front.png' },
        { id: 'f-profile', slot: 'profile', mime_type: 'image/png', media_kind: 'image' as const, size_bytes: 1, sha256: 'b', url: '/media/elements/profile.png' },
      ],
      model3d: null,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [actor], page: 1, page_size: 50, total: 1 }),
    } as Response);

    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    // Opens on 正面 and shows the front render.
    const front = await screen.findByRole('img', { name: '沈砚之 正面视图' });
    expect((front as HTMLImageElement).src).toContain('/media/elements/front.png');

    // Switching the selector swaps every card to that view's image.
    await userEvent.selectOptions(screen.getByLabelText(/上传视图/), 'profile');
    const profile = await screen.findByRole('img', { name: '沈砚之 侧面视图' });
    expect((profile as HTMLImageElement).src).toContain('/media/elements/profile.png');
    expect(screen.queryByRole('img', { name: '沈砚之 正面视图' })).toBeNull();
    expect(screen.getByRole('button', { name: '删除“沈砚之”的侧面视图' })).toBeTruthy();

    // A view with no upload states that plainly instead of faking a fallback.
    await userEvent.selectOptions(screen.getByLabelText(/上传视图/), 'back');
    expect(screen.queryByRole('img', { name: /沈砚之/ })).toBeNull();
    expect(screen.getByText('背面视图未上传')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /删除“沈砚之”的背面视图/ })).toBeNull();
  });
});
