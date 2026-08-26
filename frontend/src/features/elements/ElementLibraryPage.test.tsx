// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(settle => { resolve = settle; });
  return { promise, resolve };
}


describe('ElementLibraryPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
  });

  it('provides all four concrete pages and add/upload/regenerate actions', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], page: 1, page_size: 24, total: 0 }),
    } as Response);
    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /演员元素库/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加演员' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /上传/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: '场景' }));
    expect(await screen.findByRole('heading', { name: /场景元素库/ })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '添加场景' }).length).toBeGreaterThan(0);
    expect(await screen.findByRole('region', { name: '场景 3D 资产工作台' })).toBeTruthy();
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

    expect(await screen.findByRole('button', { name: '删除“沈知微”的参考图' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除演员资产“沈知微”' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除“陆行远”的参考图' })).toBeTruthy();
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
