// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { pushEdit, startHistory, undo, type DocHistory } from './canvasHistory';
import { canvasMenu, menuIds, nodeMenu } from './canvasMenus';
import type { CanvasDoc, CanvasNode, NodeKind, NodeOutput, NodePayload } from './canvasTypes';
import { useCanvasNodeActions } from './useCanvasNodeActions';

const node = (id: string, kind: NodeKind, x: number, y: number, payload: NodePayload = {}): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width: 200, height: 100, artifact_id: null, payload,
});
const picture = (id: string, x: number, y: number, label?: string) => node(id, 'media', x, y, { label, output: { medium: 'image', url: `/media/${id}.png` } });

const BOARD: CanvasDoc = {
  nodes: [
    picture('a', 0, 0, '雨街'), picture('b', 300, 0), node('gen', 'image_gen', 0, 300, { prompt: '雨夜的街', label: '首帧草图' }),
    node('words', 'note', 600, 300, { text: '雨夜' }), node('vid', 'video_gen', 900, 0, { label: '成片' }),
  ],
  edges: [{ id: 'e1', source: 'a', target: 'vid', kind: 'reference', payload: { role: 'first_frame' } }],
};

/** The hook over a real undo stack, with the workspace's other parts as spies. */
function mount(initial: CanvasDoc = BOARD, outputs: Record<string, NodeOutput> = {}) {
  const state: { history: DocHistory } = { history: startHistory(initial) };
  const spies = {
    say: vi.fn(), select: vi.fn(), reloadAndShow: vi.fn(async () => undefined), flush: vi.fn(async () => true),
    edit: vi.fn((change: (doc: CanvasDoc) => CanvasDoc) => { state.history = pushEdit(state.history, change(state.history.doc), null); }),
  };
  const hook = renderHook(() => useCanvasNodeActions({
    projectId: 'p1', canvasId: 'main', currentDoc: () => state.history.doc, outputs: { current: outputs }, currentVersion: () => 7,
    surface: { current: { centre: () => ({ x: 1000, y: 2000 }) } }, ...spies,
  }));
  return { hook, state, ...spies, run: (id: string, context: { nodeId?: string; ids?: string[]; world?: { x: number; y: number } } = {}) => {
    let handled = false;
    act(() => { handled = hook.result.current.run(id, { world: context.world ?? { x: 0, y: 0 }, ids: new Set(context.ids ?? []), nodeId: context.nodeId }); });
    return handled;
  } };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('the menus the workspace asks for', () => {
  it('a node\'s menu offers what that node has', () => {
    const { hook } = mount(BOARD, { gen: { medium: 'image', url: '/media/run.png', run_id: 'r1' } });
    const menuOf = (id: string) => {
      const target = BOARD.nodes.find(item => item.id === id)!;
      return menuIds(hook.result.current.nodeMenu(nodeMenu({ node: target, selectionCount: 1 }), target, new Set([id])));
    };
    expect(menuOf('a')).toEqual(['rename', 'copy', 'duplicate', 'crop', 'grid-split', 'download', 'delete']);
    expect(menuOf('gen')).toEqual(['run', 'rename', 'copy', 'duplicate', 'crop', 'grid-split', 'download', 'copy-prompt', 'delete']);
    expect(menuOf('words')).toEqual(['rename', 'copy', 'duplicate', 'delete']);
    expect(menuOf('vid')).toEqual(['run', 'rename', 'copy', 'duplicate', 'delete']);
  });

  it('an image node with no result yet offers only its prompt', () => {
    const { hook } = mount();
    const target = BOARD.nodes.find(item => item.id === 'gen')!;
    expect(menuIds(hook.result.current.nodeMenu(nodeMenu({ node: target, selectionCount: 1 }), target, new Set(['gen'])))).toEqual(['run', 'rename', 'copy', 'duplicate', 'copy-prompt', 'delete']);
  });

  it('a multi-selection offers the batch connect only with two or more pictures or clips', () => {
    const { hook } = mount();
    const target = BOARD.nodes[0];
    const menuOf = (ids: string[]) => menuIds(hook.result.current.nodeMenu(nodeMenu({ node: target, selectionCount: ids.length }), target, new Set(ids)));
    expect(menuOf(['a', 'b'])).toContain('connect-to-video');
    expect(menuOf(['a', 'words'])).not.toContain('connect-to-video');
    expect(menuOf(['a', 'b'])).not.toContain('crop');
    expect(hook.result.current.connectAction(new Set(['a', 'b']))).toBeTypeOf('function');
    expect(hook.result.current.connectAction(new Set(['a', 'words']))).toBeUndefined();
  });

  it('the empty-canvas menu gains the template, and ids that are not this hook\'s are left to the workspace', () => {
    const { hook, run } = mount();
    expect(menuIds(hook.result.current.paneMenu(canvasMenu({ canPaste: false, addKinds: ['note'] })))).toContain('template:first-last');
    expect(run('delete', { nodeId: 'a' })).toBe(false);
    expect(run('add:note')).toBe(false);
    expect(hook.result.current.modal).toBe(false);
  });
});

describe('copying a prompt and downloading', () => {
  it('copies the node\'s prompt and says so', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const { run, say } = mount();
    expect(run('copy-prompt', { nodeId: 'gen' })).toBe(true);
    await waitFor(() => expect(say).toHaveBeenCalledWith('提示词已复制。'));
    expect(writeText).toHaveBeenCalledWith('雨夜的街');
    run('copy-prompt', { nodeId: 'a' });
    expect(say).toHaveBeenLastCalledWith('这个节点没有提示词。');
  });

  it('downloads what the node shows under the node\'s name', async () => {
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) { clicked.push(this.download); });
    const fetched = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['x']) } as Response);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:made'), revokeObjectURL: vi.fn() }));
    const { run, say } = mount(BOARD, { gen: { medium: 'image', url: '/media/run.webp' } });
    run('download', { nodeId: 'gen' });
    await waitFor(() => expect(say).toHaveBeenCalledWith('已下载：首帧草图.webp'));
    expect(fetched).toHaveBeenCalledWith('http://localhost:8000/media/run.webp', { credentials: 'include' });
    expect(clicked).toEqual(['首帧草图.webp']);
    run('download', { nodeId: 'words' });
    expect(say).toHaveBeenLastCalledWith('这个节点还没有可以下载的内容。');
  });
});

describe('the first/last-frame template', () => {
  it('lands where the menu was opened as one edit, selected, and one undo takes it back', () => {
    const { run, state, edit, select } = mount();
    expect(run('template:first-last', { world: { x: 40, y: 900 } })).toBe(true);
    expect(edit).toHaveBeenCalledTimes(1);
    const doc = state.history.doc;
    expect(doc.nodes).toHaveLength(BOARD.nodes.length + 4);
    const group = doc.nodes.find(item => item.kind === 'group')!;
    expect([group.x, group.y, group.payload.label]).toEqual([40, 900, '首尾帧生视频']);
    const made = doc.nodes.filter(item => item.payload.groupId === group.id);
    expect(made.map(item => [item.kind, item.payload.label ?? ''])).toEqual([['image_gen', '首帧'], ['image_gen', '尾帧'], ['video_gen', '']]);
    expect(doc.edges.slice(-2).map(item => item.payload.role)).toEqual(['first_frame', 'last_frame']);
    expect(select).toHaveBeenCalledWith(new Set([group.id]), new Set());
    expect(state.history.past).toHaveLength(1);
    expect(undo(state.history).doc).toBe(BOARD);
  });

  it('from the toolbar it lands at the middle of the view', () => {
    const { hook, state } = mount();
    render(hook.result.current.toolbar);
    fireEvent.click(screen.getByRole('button', { name: '模板：首尾帧生视频' }));
    const group = state.history.doc.nodes.find(item => item.kind === 'group')!;
    expect([group.x, group.y]).toEqual([1000, 2000]);
  });
});

describe('connecting a selection to a video node', () => {
  it('asks which video node, connects in one edit, and says how many were connected and skipped', () => {
    const { hook, run, state, say, edit, select } = mount();
    // a → vid is already there; b and gen are new.
    expect(run('connect-to-video', { ids: ['a', 'b', 'gen', 'words'] })).toBe(true);
    expect(hook.result.current.modal).toBe(true);
    const view = render(hook.result.current.dialogs);
    expect(screen.getByRole('dialog', { name: '连到视频节点' })).toBeTruthy();
    expect(screen.getByText(/把选中的 3 个图片 \/ 视频节点/)).toBeTruthy();
    expect(screen.getByText('已有 1 条输入')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    view.unmount();

    expect(edit).toHaveBeenCalledTimes(1);
    expect(state.history.doc.edges.map(item => [item.source, item.target, item.payload.role])).toEqual([
      ['a', 'vid', 'first_frame'], ['gen', 'vid', 'ref_image'], ['b', 'vid', 'ref_image'],
    ]);
    expect(say).toHaveBeenLastCalledWith('已连接 2 条，跳过 1 条');
    expect(select).toHaveBeenLastCalledWith(new Set(['vid']), new Set());
    expect(hook.result.current.modal).toBe(false);
    expect(state.history.past).toHaveLength(1);
    expect(undo(state.history).doc).toBe(BOARD);
  });

  it('a new video node is made to the right of the selection in the same edit', () => {
    const { hook, run, state, say } = mount();
    run('connect-to-video', { ids: ['a', 'b'] });
    const view = render(hook.result.current.dialogs);
    fireEvent.click(screen.getByRole('radio', { name: '新建视频节点' }));
    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    view.unmount();
    const doc = state.history.doc;
    const made = doc.nodes[doc.nodes.length - 1];
    expect(made.kind).toBe('video_gen');
    expect(made.x).toBeGreaterThanOrEqual(500);
    expect(doc.edges.slice(1).map(item => [item.source, item.target, item.payload.role])).toEqual([['a', made.id, 'ref_image'], ['b', made.id, 'ref_image']]);
    expect(say).toHaveBeenLastCalledWith('已连接 2 条，跳过 0 条');
    expect(state.history.past).toHaveLength(1);
  });

  it('when every connection is skipped nothing is edited', () => {
    const both: CanvasDoc = { ...BOARD, edges: [...BOARD.edges, { id: 'e2', source: 'b', target: 'vid', kind: 'reference', payload: { role: 'ref_image' } }] };
    const { hook, run, say, edit } = mount(both);
    run('connect-to-video', { ids: ['a', 'b'] });
    const view = render(hook.result.current.dialogs);
    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    view.unmount();
    expect(edit).not.toHaveBeenCalled();
    expect(say).toHaveBeenLastCalledWith('已连接 0 条，跳过 2 条');
  });

  it('is refused with fewer than two pictures or clips', () => {
    const { hook, run, say } = mount();
    run('connect-to-video', { ids: ['a', 'words'] });
    expect(hook.result.current.modal).toBe(false);
    expect(say).toHaveBeenLastCalledWith('至少选中两个图片或视频节点。');
  });
});

describe('crop and grid split', () => {
  function installServer() {
    const calls: Array<{ path: string; body: Record<string, number> }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = new URL(String(input), 'http://localhost:8000');
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {};
      calls.push({ path: url.pathname, body });
      const count = url.pathname.endsWith('/grid-split') ? body.rows * body.columns : 1;
      return { ok: true, status: 200, json: async () => ({ version: 8, node_ids: Array.from({ length: count }, (_, index) => `new${index + 1}`), source_node_id: 'a', connected: false }) } as Response;
    });
    return calls;
  }

  it('a split saves first, asks the server, then catches the canvas up and selects the new nodes', async () => {
    const calls = installServer();
    const { hook, run, say, select, reloadAndShow, flush, edit } = mount();
    expect(run('grid-split', { nodeId: 'a' })).toBe(true);
    expect(hook.result.current.modal).toBe(true);
    render(hook.result.current.dialogs);
    expect(screen.getByRole('dialog', { name: '宫格拆分：雨街' })).toBeTruthy();
    expect((screen.getByRole('img') as HTMLImageElement).src).toBe('http://localhost:8000/media/a.png');
    fireEvent.click(screen.getByRole('button', { name: '拆分' }));
    await waitFor(() => expect(say).toHaveBeenCalledWith('已拆成 4 个素材节点。'));
    expect(flush).toHaveBeenCalledTimes(1);
    expect(calls).toEqual([{ path: '/api/studio/projects/p1/canvas/nodes/a/grid-split', body: { rows: 2, columns: 2, expected_version: 7 } }]);
    expect(reloadAndShow).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenLastCalledWith(new Set(['new1', 'new2', 'new3', 'new4']), new Set());
    // The server wrote the canvas; nothing was edited here.
    expect(edit).not.toHaveBeenCalled();
    await waitFor(() => expect(hook.result.current.modal).toBe(false));
  });

  it('a crop opens on the picture the node shows now', () => {
    installServer();
    const { hook, run } = mount(BOARD, { gen: { medium: 'image', url: '/media/run.png' } });
    run('crop', { nodeId: 'gen' });
    render(hook.result.current.dialogs);
    expect(screen.getByRole('dialog', { name: '裁剪：首帧草图' })).toBeTruthy();
    expect((screen.getByRole('img') as HTMLImageElement).src).toBe('http://localhost:8000/media/run.png');
  });

  it('a node with no picture is told so and no dialog opens', () => {
    const { hook, run, say } = mount();
    run('crop', { nodeId: 'gen' });
    expect(say).toHaveBeenLastCalledWith('这个节点还没有图片，裁不了。');
    run('grid-split', { nodeId: 'words' });
    expect(say).toHaveBeenLastCalledWith('这个节点还没有图片，拆不了。');
    expect(hook.result.current.modal).toBe(false);
  });

  it('the canvas that cannot be saved is not cut', async () => {
    const calls = installServer();
    const mounted = mount();
    mounted.flush.mockResolvedValue(false);
    mounted.run('grid-split', { nodeId: 'a' });
    render(mounted.hook.result.current.dialogs);
    fireEvent.click(screen.getByRole('button', { name: '拆分' }));
    expect((await screen.findByRole('alert')).textContent).toContain('画布还没保存成功');
    expect(calls).toHaveLength(0);
    expect(mounted.reloadAndShow).not.toHaveBeenCalled();
  });
});

describe('the inspector\'s buttons', () => {
  it('are the same actions, for what the node has', () => {
    const { hook } = mount(BOARD, { gen: { medium: 'image', url: '/media/run.png' } });
    const shown = { gen: { medium: 'image' as const, url: '/media/run.png' } };
    const view = render(<div>{hook.result.current.inspectorActions(BOARD.nodes[2], BOARD, shown)}</div>);
    expect(screen.getAllByRole('button').map(button => button.textContent)).toEqual(['裁剪', '宫格拆分', '下载', '复制提示词']);
    fireEvent.click(screen.getByRole('button', { name: '裁剪' }));
    expect(hook.result.current.modal).toBe(true);
    view.unmount();
    expect(hook.result.current.inspectorActions(BOARD.nodes[3], BOARD, {})).toBeNull();
  });
});
