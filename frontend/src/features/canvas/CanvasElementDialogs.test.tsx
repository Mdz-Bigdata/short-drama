// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasElementPickerDialog, CanvasSaveElementDialog } from './CanvasElementDialogs';
import { SAVABLE_KINDS, savablePicture, type LibraryElement } from './canvasElementsApi';
import { menuIds, nodeMenu } from './canvasMenus';
import type { CanvasDoc, CanvasNode, NodeKind, NodeOutput } from './canvasTypes';

const BASE = '/api/studio/projects/p1/canvas';

interface Call { method: string; path: string; query: URLSearchParams; body: { picks?: unknown[]; name?: string; kind?: string; expected_version?: number } }

const image = (elementId: string, id: string, slot: string) => ({ id, slot, url: `/api/elements/${elementId}/files/${id}/content?v=3` });

const LIBRARY: LibraryElement[] = [
  { id: 'e-lin', kind: 'actor', name: '林晚', images: [image('e-lin', 'f-front', 'front'), image('e-lin', 'f-face', 'face_front'), image('e-lin', 'f-back', 'back')] },
  { id: 'e-umbrella', kind: 'prop', name: '红伞', images: [image('e-umbrella', 'f-ref', 'reference')] },
  { id: 'e-street', kind: 'scene', name: '雨街', images: [image('e-street', 'f-wide', 'reference')] },
];

function installServer(options: { maxTake?: number; pageSize?: number; saveStatus?: number; saveDetail?: string } = {}) {
  const calls: Call[] = [];
  const pageSize = options.pageSize ?? 60;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = new URL(String(input), 'http://localhost:8000');
    const method = init?.method ?? 'GET';
    const body: Call['body'] = typeof init?.body === 'string' ? JSON.parse(init.body) : {};
    calls.push({ method, path: url.pathname, query: url.searchParams, body });
    if (url.pathname === `${BASE}/elements` && method === 'GET') {
      const kind = url.searchParams.get('kind');
      const needle = url.searchParams.get('q') ?? '';
      const page = Number(url.searchParams.get('page') ?? 1);
      const rows = LIBRARY.filter(item => (!kind || item.kind === kind) && item.name.includes(needle));
      return {
        ok: true, status: 200,
        json: async () => ({ items: rows.slice((page - 1) * pageSize, page * pageSize), total: rows.length, page, page_size: pageSize, kinds: ['actor', 'prop', 'scene'], max_take: options.maxTake ?? 24 }),
      } as Response;
    }
    if (url.pathname === `${BASE}/elements` && method === 'POST') {
      const nodeIds = (body.picks ?? []).map((_, index) => `n${index + 1}`);
      return { ok: true, status: 200, json: async () => ({ version: 8, node_ids: nodeIds, elements: [] }) } as Response;
    }
    if (url.pathname === `${BASE}/nodes/img/element` && method === 'POST') {
      if (options.saveStatus) return { ok: false, status: options.saveStatus, json: async () => ({ detail: options.saveDetail }) } as Response;
      return { ok: true, status: 200, json: async () => ({ id: 'e-new', name: body.name, kind: body.kind }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) } as Response;
  });
  return calls;
}

function openPicker(overrides: Partial<Parameters<typeof CanvasElementPickerDialog>[0]> = {}) {
  const props = { projectId: 'p1', canvasId: 'main', prepare: vi.fn(async () => 7), onApplied: vi.fn(), onClose: vi.fn(), ...overrides };
  render(<CanvasElementPickerDialog {...props} />);
  return props;
}

function openSave(overrides: Partial<Parameters<typeof CanvasSaveElementDialog>[0]> = {}) {
  const props = {
    projectId: 'p1', canvasId: 'main', nodeId: 'img', defaultName: '雨夜老宅', previewUrl: '/media/canvas_a.png',
    prepare: vi.fn(async () => 7), onSaved: vi.fn(), onClose: vi.fn(), ...overrides,
  };
  render(<CanvasSaveElementDialog {...props} />);
  return props;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('taking pictures from the element library', () => {
  it('lists the library with name, kind and thumbnail, and puts the picked pictures on the saved version', async () => {
    const calls = installServer();
    const props = openPicker();

    const lin = await screen.findByRole('button', { name: '林晚 · 演员' });
    expect(screen.getByRole('button', { name: '红伞 · 道具' })).toBeTruthy();
    expect(lin.querySelector('img')?.getAttribute('src')).toBe('http://localhost:8000/api/elements/e-lin/files/f-front/content?v=3');
    const apply = screen.getByRole('button', { name: '放到画布' }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '红伞 · 道具' }));
    expect(screen.getByRole('button', { name: '红伞 · 道具' }).getAttribute('aria-pressed')).toBe('true');
    // An element with more views: its main picture by the card, the others one by one.
    fireEvent.click(screen.getByRole('button', { name: '其余 2 张图' }));
    fireEvent.click(screen.getByRole('button', { name: '林晚 的第 2 张图' }));
    expect(screen.getByRole('button', { name: '其余 2 张图，已选 1 张' })).toBeTruthy();
    expect(screen.getByText('已选 2 张图片')).toBeTruthy();

    fireEvent.click(apply);
    await waitFor(() => expect(props.onApplied).toHaveBeenCalledWith({ version: 8, node_ids: ['n1', 'n2'], elements: [] }));
    expect(props.prepare).toHaveBeenCalledTimes(1);
    const post = calls.find(call => call.method === 'POST')!;
    expect(post.query.get('canvas_id')).toBe('main');
    expect(post.body).toEqual({
      picks: [{ element_id: 'e-umbrella', file_id: 'f-ref' }, { element_id: 'e-lin', file_id: 'f-face' }],
      expected_version: 7,
    });
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('narrows by kind and by search on the server, and unpicks on a second click', async () => {
    const calls = installServer();
    openPicker();
    await screen.findByRole('button', { name: '林晚 · 演员' });

    fireEvent.change(screen.getByRole('combobox', { name: '元素类型' }), { target: { value: 'prop' } });
    await waitFor(() => expect(screen.queryByRole('button', { name: '林晚 · 演员' })).toBeNull());
    expect(screen.getByRole('button', { name: '红伞 · 道具' })).toBeTruthy();
    expect(calls.at(-1)!.query.get('kind')).toBe('prop');

    fireEvent.change(screen.getByRole('textbox', { name: '搜索元素' }), { target: { value: '没有这个' } });
    expect(await screen.findByText('没有符合条件的元素。')).toBeTruthy();
    expect(calls.at(-1)!.query.get('q')).toBe('没有这个');

    fireEvent.change(screen.getByRole('textbox', { name: '搜索元素' }), { target: { value: '' } });
    const umbrella = await screen.findByRole('button', { name: '红伞 · 道具' });
    fireEvent.click(umbrella);
    fireEvent.click(umbrella);
    expect(screen.getByText('已选 0 张图片')).toBeTruthy();
    expect((screen.getByRole('button', { name: '放到画布' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('loads further pages and will not take more than the limit', async () => {
    const calls = installServer({ pageSize: 2, maxTake: 1 });
    openPicker();
    await screen.findByRole('button', { name: '林晚 · 演员' });
    expect(screen.queryByRole('button', { name: '雨街 · 场景' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '加载更多（已列出 2 / 3）' }));
    fireEvent.click(await screen.findByRole('button', { name: '雨街 · 场景' }));
    expect(calls.at(-1)!.query.get('page')).toBe('2');
    expect(screen.queryByRole('button', { name: /加载更多/ })).toBeNull();

    const apply = screen.getByRole('button', { name: '放到画布' }) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '红伞 · 道具' }));
    expect(apply.disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('一次最多取用 1 张图片');
  });

  it('says why when the canvas cannot be saved first, takes nothing and stays open', async () => {
    const calls = installServer();
    const props = openPicker({ prepare: vi.fn(async () => { throw new Error('画布还没保存成功，先解决保存问题。'); }) });
    fireEvent.click(await screen.findByRole('button', { name: '红伞 · 道具' }));
    fireEvent.click(screen.getByRole('button', { name: '放到画布' }));
    expect((await screen.findByRole('alert')).textContent).toContain('画布还没保存成功');
    expect(calls.some(call => call.method === 'POST')).toBe(false);
    expect(props.onApplied).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it('says so when the library has nothing to take, and closes on Escape', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], total: 0, page: 1, page_size: 60, kinds: [], max_take: 24 }) } as Response);
    const props = openPicker();
    expect(await screen.findByText('元素库里还没有带图片的元素。')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalled();
  });
});

describe('keeping a node\'s picture in the element library', () => {
  it('asks for a name and a kind, saves the canvas first, and reports the new element', async () => {
    const calls = installServer();
    const props = openSave();

    const name = screen.getByRole('textbox', { name: '名称' }) as HTMLInputElement;
    expect(name.value).toBe('雨夜老宅');
    const kind = screen.getByRole('combobox', { name: '类型' }) as HTMLSelectElement;
    expect([...kind.options].map(option => option.value)).toEqual([...SAVABLE_KINDS]);
    expect(SAVABLE_KINDS).not.toContain('costume');
    expect(kind.value).toBe('prop');

    fireEvent.change(name, { target: { value: '  老宅正门 ' } });
    fireEvent.change(kind, { target: { value: 'scene' } });
    fireEvent.click(screen.getByRole('button', { name: '存入元素库' }));

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith({ id: 'e-new', name: '老宅正门', kind: 'scene' }));
    expect(props.prepare).toHaveBeenCalledTimes(1);
    const post = calls.find(call => call.method === 'POST')!;
    expect(post.path).toBe(`${BASE}/nodes/img/element`);
    expect(post.query.get('canvas_id')).toBe('main');
    expect(post.body).toEqual({ name: '老宅正门', kind: 'scene' });
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('needs a name, and shows the server\'s refusal without closing', async () => {
    installServer({ saveStatus: 422, saveDetail: '这个节点还没有图片结果，存不进元素库' });
    const props = openSave({ defaultName: '' });
    const submit = screen.getByRole('button', { name: '存入元素库' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByRole('textbox', { name: '名称' }), { target: { value: '试试' } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    expect((await screen.findByRole('alert')).textContent).toContain('这个节点还没有图片结果');
    expect(props.onSaved).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
    expect(submit.disabled).toBe(false);
  });

  it('explains what an actor still needs', () => {
    installServer();
    openSave();
    expect(screen.queryByText(/正面全身位/)).toBeNull();
    fireEvent.change(screen.getByRole('combobox', { name: '类型' }), { target: { value: 'actor' } });
    expect(screen.getByText(/正面全身位/)).toBeTruthy();
  });
});

describe('which nodes have a picture to keep', () => {
  const node = (id: string, kind: NodeKind, output?: NodeOutput): CanvasNode => (
    { id, kind, track: 'freezone', x: 0, y: 0, width: 200, height: 100, artifact_id: null, payload: output ? { output } : {} }
  );
  const picture: NodeOutput = { medium: 'image', url: '/media/a.png' };

  it('a media node holding an image, or a node whose active generation is an image', () => {
    const doc: CanvasDoc = {
      nodes: [node('pic', 'media', picture), node('clip', 'media', { medium: 'video', url: '/media/a.mp4' }), node('img', 'image_gen'), node('tool', 'tool'), node('words', 'note')],
      edges: [],
    };
    const outputs = { tool: { medium: 'text' as const, url: '', text: '写好了' } };
    expect(savablePicture(doc.nodes[0], doc, outputs)?.url).toBe('/media/a.png');
    expect(savablePicture(doc.nodes[1], doc, outputs)).toBeNull();
    expect(savablePicture(doc.nodes[2], doc, outputs)).toBeNull();
    expect(savablePicture(doc.nodes[2], doc, { img: { medium: 'image', url: '/media/run.png' } })?.url).toBe('/media/run.png');
    expect(savablePicture(doc.nodes[3], doc, outputs)).toBeNull();
    expect(savablePicture(doc.nodes[4], doc, outputs)).toBeNull();
    expect(savablePicture(undefined, doc, outputs)).toBeNull();
  });

  it('the node menu offers it only then', () => {
    const img = node('img', 'image_gen');
    expect(menuIds(nodeMenu({ node: img, selectionCount: 1, canSaveElement: true }))).toEqual(['run', 'rename', 'copy', 'duplicate', 'save-element', 'delete']);
    expect(menuIds(nodeMenu({ node: img, selectionCount: 1, canSaveElement: false }))).not.toContain('save-element');
    expect(menuIds(nodeMenu({ node: img, selectionCount: 3, canSaveElement: true }))).not.toContain('save-element');
  });
});
