// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasWorkspace } from './CanvasWorkspace';
import { kindLabel } from './canvasLabels';
import type { CanvasEdge, CanvasNode, NodeKind } from './canvasTypes';

vi.mock('../directorDesk/DirectorDesk', () => ({
  DirectorDesk: ({ sceneId, initialShotId, initialSideTab, initialReference, onClose }: {
    sceneId: string; initialShotId?: number; initialSideTab?: string; initialReference?: { url: string }; onClose: () => void;
  }) => (
    <div role="dialog" aria-label="desk">
      <span data-testid="desk-args">{JSON.stringify({ sceneId, initialShotId, initialSideTab, initialReference })}</span>
      <input aria-label="inside the desk" />
      <button type="button" onClick={onClose}>close desk</button>
    </div>
  ),
}));
vi.mock('./PanoramaViewer', () => ({
  default: ({ url, onFail }: { url: string; onFail?: () => void }) => (
    <div data-testid="panorama">{url}<button type="button" aria-label="panorama fails to load" onClick={onFail} /></div>
  ),
}));

const OPTIONS = {
  models: { image: 'seedream', video: 'seedance2.0', audio: 'tts' }, enabled: { image: [], video: [], audio: [] }, video_durations: [5, 6, 7, 8],
  kinds: {
    image_gen: { runnable: true, reason: '' }, video_gen: { runnable: true, reason: '至少连一张参考图' }, audio_gen: { runnable: true, reason: '', modes: { speech: true, music: false, sfx: false } },
    video_compose: { runnable: true, reason: '本机拼接' },
  },
};

const node = (id: string, kind: NodeKind, patch: Partial<CanvasNode> = {}): CanvasNode => ({
  id, kind, track: 'freezone', x: 0, y: 0, width: 200, height: 150, artifact_id: null, payload: {}, ...patch,
});

interface Server {
  version: number;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  outputs: Record<string, unknown>;
  latest: Record<string, unknown>;
  puts: Array<{ expected_version: number; nodes: CanvasNode[]; edges: CanvasEdge[] }>;
  conflict: boolean;
  calls: Array<{ method: string; path: string; body: unknown }>;
  handlers: Array<(method: string, path: string, body: never) => unknown>;
}

let server: Server;

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function installServer(initial: Partial<Server> = {}) {
  server = { version: 0, nodes: [], edges: [], outputs: {}, latest: {}, puts: [], conflict: false, calls: [], handlers: [], ...initial };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input).replace('http://localhost:8000', '');
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    const path = url.split('?')[0];
    server.calls.push({ method, path, body });
    for (const handler of server.handlers) {
      const answer = handler(method, path, body as never);
      if (answer !== undefined) return answer as Response;
    }
    if (path === '/api/studio/tasks/t1/canvas-project') {
      return ok({ project_id: 'p1', task_id: 't1', canvases: [{ id: 'main', project_id: 'p1', title: '主画布', bookmarks: [], version: server.version }] });
    }
    if (path.endsWith('/history')) return ok({ node_id: '', active_run_id: null, runs: [] });
    if (path.endsWith('/canvas/run-options')) return ok(OPTIONS);
    if (path.endsWith('/canvas/shots')) return ok({ shots: [{ scene_id: 'E1S01', shot_id: 1, desc: '' }, { scene_id: 'E1S01', shot_id: 2, desc: '' }] });
    if (path.endsWith('/canvas/outputs')) return ok({ version: server.version, outputs: server.outputs, latest: server.latest, history_counts: {}, running: 0 });
    if (path.endsWith('/canvas') && method === 'GET') return ok({ project_id: 'p1', version: server.version, nodes: server.nodes, edges: server.edges, created_at: '' });
    if (path.endsWith('/canvas') && method === 'PUT') {
      const request = body as Server['puts'][number];
      server.puts.push(request);
      if (server.conflict) return { ok: false, status: 409, json: async () => ({ detail: 'canvas version conflict' }) } as Response;
      server.version = request.expected_version + 1;
      server.nodes = request.nodes;
      server.edges = request.edges;
      return ok({ project_id: 'p1', version: server.version, nodes: request.nodes, edges: request.edges, created_at: '' });
    }
    return ok({});
  });
}

async function openCanvas() {
  const onClose = vi.fn();
  const view = render(<CanvasWorkspace taskId="t1" onClose={onClose} />);
  await screen.findByLabelText('添加节点');
  await waitFor(() => expect(server.calls.some(call => call.path.endsWith('/canvas/outputs'))).toBe(true));
  await act(async () => { await Promise.resolve(); });
  return { onClose, ...view };
}

function surface() {
  return screen.getByRole('application');
}

function press(key: string, options: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(document.body, { key, ...options });
}

async function waitForSave() {
  await waitFor(() => expect(server.puts.length).toBeGreaterThan(0), { timeout: 3000 });
}

function pointer(type: 'pointerDown' | 'pointerMove' | 'pointerUp', element: Element, x: number, y: number, extra: Record<string, unknown> = {}) {
  fireEvent[type](element, { clientX: x, clientY: y, button: 0, pointerId: 1, bubbles: true, ...extra });
}

// jsdom has no PointerEvent, and without it fireEvent drops the coordinates.
class FakePointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}

describe('CanvasWorkspace', () => {
  beforeEach(() => {
    vi.stubGlobal('PointerEvent', FakePointerEvent);
    window.localStorage.clear();
    let frame = 0;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frame += 1;
      setTimeout(() => callback(0), 0);
      return frame;
    });
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    // The minimap draws on a 2D canvas, which jsdom does not have: without this every test logs "not implemented".
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('opens the project behind the task, loads an old canvas, and draws its nodes', async () => {
    installServer({
      version: 3,
      nodes: [node('legacy', 'media', { payload: { label: '旧素材' } }), node('art', 'artifact', { artifact_id: 'a1', x: 400, payload: { label: '旧产物' } }), node('old-note', 'note', { x: 800, payload: { text: '旧注释' } })],
      edges: [{ id: 'old', source: 'legacy', target: 'old-note', kind: 'lineage', payload: {} }],
    });
    await openCanvas();
    expect(await screen.findByText('旧素材')).toBeTruthy();
    expect(screen.getByText('旧产物')).toBeTruthy();
    expect((screen.getByLabelText('文本') as HTMLTextAreaElement).value).toBe('旧注释');
    expect(server.puts).toEqual([]);
  });

  it('adds a node from the rail and autosaves against the revision it read', async () => {
    installServer({ version: 4 });
    await openCanvas();
    fireEvent.click(screen.getByRole('button', { name: `添加：${kindLabel('image_gen')}` }));
    expect(await screen.findByLabelText('提示词')).toBeTruthy();
    await waitForSave();
    expect(server.puts[0].expected_version).toBe(4);
    expect(server.puts[0].nodes[0].kind).toBe('image_gen');
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('第 5 版'));
  });

  it('tells the person about a 409, overwrites nothing, stops saving, and offers a way out', async () => {
    installServer({ version: 1, nodes: [node('n', 'note', { payload: { text: '原文' } })] });
    await openCanvas();
    server.conflict = true;
    fireEvent.change(await screen.findByLabelText('文本'), { target: { value: '我的修改' } });
    expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toContain('已在别处被修改');
    const attempts = server.puts.length;
    expect(attempts).toBe(1);
    fireEvent.change(screen.getByLabelText('文本'), { target: { value: '接着改' } });
    await new Promise(resolve => setTimeout(resolve, 1400));
    expect(server.puts.length).toBe(attempts);
    expect((screen.getByLabelText('文本') as HTMLTextAreaElement).value).toBe('接着改');

    // Taking the latest ends the conflict and drops the local text.
    server.conflict = false;
    server.version = 7;
    server.nodes = [node('n', 'note', { payload: { text: '别人的' } })];
    fireEvent.click(screen.getByRole('button', { name: '载入最新版本（放弃我的修改）' }));
    await waitFor(() => expect((screen.getByLabelText('文本') as HTMLTextAreaElement).value).toBe('别人的'));
    expect(screen.queryByText('这张画布已在别处被修改（其他窗口或助手）。')).toBeNull();
  });

  it('keeps the conflicted version as a new canvas when asked', async () => {
    installServer({ version: 1, nodes: [node('n', 'note', { payload: { text: '原文' } })] });
    server.handlers.push((method, path, body) => {
      if (method === 'POST' && path.endsWith('/canvases')) return ok({ id: 'cv2', project_id: 'p1', title: (body as { title: string }).title, bookmarks: [], version: 0 });
      return undefined;
    });
    await openCanvas();
    server.conflict = true;
    fireEvent.change(await screen.findByLabelText('文本'), { target: { value: '我的版本' } });
    await screen.findByRole('alert', {}, { timeout: 3000 });
    server.conflict = false;
    fireEvent.click(screen.getByRole('button', { name: '把我的版本另存为新画布' }));
    await waitFor(() => expect(server.puts.some(item => item.expected_version === 0 && item.nodes[0].payload.text === '我的版本')).toBe(true));
    expect(await screen.findByRole('option', { name: '主画布（我的版本）' })).toBeTruthy();
  });

  it('undoes, redoes, deletes, duplicates and groups from the keyboard, but not while typing', async () => {
    installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲', text: 'A' } }), node('b', 'note', { x: 300, payload: { label: '乙', text: 'B' } })] });
    await openCanvas();
    const framed = await screen.findByTestId('node-a');
    pointer('pointerDown', within(framed).getByText('甲'), 10, 10);
    pointer('pointerUp', within(framed).getByText('甲'), 10, 10);

    // A Delete typed into a field belongs to the field.
    const field = within(framed).getByLabelText('文本');
    fireEvent.keyDown(field, { key: 'Delete' });
    expect(screen.getByTestId('node-a')).toBeTruthy();

    press('Delete');
    await waitFor(() => expect(screen.queryByTestId('node-a')).toBeNull());
    press('z', { ctrlKey: true });
    expect(await screen.findByTestId('node-a')).toBeTruthy();
    press('z', { ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(screen.queryByTestId('node-a')).toBeNull());
    press('z', { ctrlKey: true });
    const back = await screen.findByTestId('node-a');
    pointer('pointerDown', within(back).getByText('甲'), 10, 10);
    pointer('pointerUp', within(back).getByText('甲'), 10, 10);

    press('d', { ctrlKey: true });
    await waitFor(() => expect(screen.getAllByLabelText('文本')).toHaveLength(3));

    press('a', { ctrlKey: true });
    press('g', { ctrlKey: true });
    await waitFor(() => expect(surface().querySelector('.cn-group__head')?.textContent).toContain('分组'));
  });

  it('drags a node on commit only, in world units, and a click makes no edit', async () => {
    installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } })] });
    await openCanvas();
    const framed = await screen.findByTestId('node-a');
    const head = within(framed).getByText('甲');
    pointer('pointerDown', head, 100, 100);
    pointer('pointerUp', head, 100, 100);
    await new Promise(resolve => setTimeout(resolve, 0));
    pointer('pointerDown', head, 100, 100);
    pointer('pointerMove', head, 150, 130);
    pointer('pointerUp', head, 150, 130);
    await waitForSave();
    expect(server.puts).toHaveLength(1);
    expect(server.puts[0].nodes[0]).toMatchObject({ x: 50, y: 30 });
    press('z', { ctrlKey: true });
    await waitFor(() => expect(screen.getByTestId('node-a').style.transform).toBe('translate(0px, 0px)'));
  });

  it('snaps a dragged node to its neighbour and shows the guide while it does', async () => {
    installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } }), node('b', 'note', { x: 300, y: 500, payload: { label: '乙' } })] });
    await openCanvas();
    const head = within(await screen.findByTestId('node-a')).getByText('甲');
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    const world = surface().querySelector<HTMLElement>('.cn-world')!;
    const zoom = Number(/scale\(([\d.]+)\)/.exec(world.style.transform)![1]);
    pointer('pointerDown', head, 100, 100);
    pointer('pointerMove', head, 100 + 298 * zoom, 100);
    await waitFor(() => expect(surface().querySelector('.cn-guide--x')).toBeTruthy());
    pointer('pointerUp', head, 100 + 298 * zoom, 100);
    await waitForSave();
    expect(server.puts[0].nodes[0].x).toBe(300);
    expect(surface().querySelector('.cn-guide--x')).toBeNull();
    press('z', { ctrlKey: true });

    // Alt turns snapping off for one drag.
    pointer('pointerDown', head, 100, 100);
    pointer('pointerMove', head, 100 + 298 * zoom, 100, { altKey: true });
    pointer('pointerUp', head, 100 + 298 * zoom, 100, { altKey: true });
    await waitFor(() => expect(server.puts[server.puts.length - 1].nodes[0].x).toBe(298), { timeout: 3000 });
  });

  it('zooms to the cursor with a non-passive wheel listener, and leaves a text field scrolling itself', async () => {
    installServer({ version: 1, nodes: [node('a', 'note')] });
    await openCanvas();
    const world = surface().querySelector<HTMLElement>('.cn-world')!;
    const before = world.style.transform;
    const event = new WheelEvent('wheel', { deltaY: -100, clientX: 200, clientY: 100, bubbles: true, cancelable: true });
    surface().dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(world.style.transform).not.toBe(before);
    // Resting on a prompt field still zooms; typing in one, the wheel belongs to the field.
    const field = await screen.findByLabelText('文本');
    const passingOver = new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true });
    field.dispatchEvent(passingOver);
    expect(passingOver.defaultPrevented).toBe(true);
    field.focus();
    const settled = world.style.transform;
    const inField = new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true });
    field.dispatchEvent(inField);
    expect(inField.defaultPrevented).toBe(false);
    expect(world.style.transform).toBe(settled);
  });

  it('marquee-selects, and shift adds to the selection', async () => {
    installServer({ version: 1, nodes: [node('a', 'note', { x: 0, y: 0, payload: { label: '甲' } }), node('b', 'note', { x: 300, y: 0, payload: { label: '乙' } }), node('c', 'note', { x: 900, y: 900, payload: { label: '丙' } })] });
    await openCanvas();
    await screen.findByTestId('node-a');
    await act(async () => { surface().querySelector('.cn-world'); });
    const run = screen.getByRole('button', { name: /提交所选/ });
    expect((run as HTMLButtonElement).disabled).toBe(true);
    // Keep the view fixed at the identity so screen and world agree.
    pointer('pointerDown', surface(), 900, 700);
    pointer('pointerMove', surface(), 901, 701);
    pointer('pointerUp', surface(), 901, 701);
    expect(run.textContent).toMatch(/^.*提交所选$/);
    fireEvent.keyDown(document.body, { key: 'f' });
    fireEvent.keyDown(document.body, { key: 'a', ctrlKey: true });
    await waitFor(() => expect(run.textContent).toContain('(3)'));
  });

  it('refuses a connection the types do not allow and says why, and makes the edge when they do', async () => {
    installServer({
      version: 1,
      nodes: [node('gen', 'image_gen', { x: 0, y: 0, payload: { label: '图' } }), node('vid', 'video_gen', { x: 400, y: 0, payload: { label: '视频' } })],
    });
    await openCanvas();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    const world = surface().querySelector<HTMLElement>('.cn-world')!;
    const view = /translate\((-?[\d.]+)px, (-?[\d.]+)px\) scale\(([\d.]+)\)/.exec(world.style.transform)!;
    const [panX, panY, zoom] = [Number(view[1]), Number(view[2]), Number(view[3])];
    const at = (x: number, y: number) => [x * zoom + panX, y * zoom + panY] as const;

    const outOfVideo = screen.getByTestId('node-vid').querySelector('[data-port="out"]')!;
    const [ix, iy] = at(100, 50);
    pointer('pointerDown', outOfVideo, ...at(600, 75));
    pointer('pointerUp', outOfVideo, ix, iy);
    expect((await screen.findByRole('status', { name: '' }).catch(() => screen.getByText('目标节点不接受这种输入'))).textContent).toBeTruthy();
    expect(await screen.findByText('目标节点不接受这种输入')).toBeTruthy();

    const outOfImage = screen.getByTestId('node-gen').querySelector('[data-port="out"]')!;
    pointer('pointerDown', outOfImage, ...at(200, 75));
    pointer('pointerUp', outOfImage, ...at(500, 50));
    await waitForSave();
    expect(server.puts[server.puts.length - 1].edges[0]).toMatchObject({ source: 'gen', target: 'vid', kind: 'reference', payload: { role: 'ref_image' } });
    await waitFor(() => expect(surface().querySelector('.cn-edge--reference')).toBeTruthy());
  });

  it('draws shells instead of bodies when zoomed far out, and only what is in view', async () => {
    const many = Array.from({ length: 300 }, (_, index) => node(`n${index}`, 'image_gen', { x: (index % 20) * 320, y: Math.floor(index / 20) * 360, payload: { label: `节点${index}`, prompt: 'p' } }));
    installServer({ version: 1, nodes: many });
    const started = performance.now();
    await openCanvas();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    // The first look fits all 300 in view, so far out that every one is a shell with no body at all.
    await waitFor(() => expect(surface().querySelectorAll('.cn-shell').length).toBe(300));
    expect(surface().querySelectorAll('.cn-node').length).toBe(0);
    expect(surface().querySelectorAll('textarea').length).toBe(0);
    expect(performance.now() - started).toBeLessThan(5000);

    // Coming in close draws real bodies, and only for what the view can reach.
    fireEvent.click(screen.getByRole('tab', { name: '大纲' }));
    fireEvent.click(await screen.findByRole('button', { name: /节点0\b/ }));
    // 大纲跳转现在是平滑移过去的：等移动结束再数，途中远景会短暂画得多一些。
    await waitFor(() => {
      expect(surface().querySelectorAll('.cn-node').length).toBeGreaterThan(0);
      const drawn = surface().querySelectorAll('[data-node-id]').length;
      expect(drawn).toBeGreaterThan(0);
      expect(drawn).toBeLessThan(100);
    }, { timeout: 3000 });
  });

  it('jumps from the outline and saves a numbered bookmark without touching the drawing', async () => {
    installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } }), node('far', 'note', { x: 50000, y: 50000, payload: { label: '远方' } })] });
    await openCanvas();
    fireEvent.click(screen.getByRole('tab', { name: '大纲' }));
    fireEvent.click(await screen.findByRole('button', { name: /远方/ }));
    const world = surface().querySelector<HTMLElement>('.cn-world')!;
    await waitFor(() => expect(world.style.transform).toContain('-'));
    expect(await screen.findByTestId('node-far')).toBeTruthy();
    const jumped = world.style.transform;

    fireEvent.keyDown(document.body, { code: 'Digit3', key: '#', shiftKey: true });
    await waitFor(() => expect(server.calls.some(call => call.method === 'PATCH' && (call.body as { bookmarks?: unknown[] }).bookmarks?.length === 1)).toBe(true));
    fireEvent.keyDown(document.body, { key: 'f' });
    await waitFor(() => expect(world.style.transform).not.toBe(jumped));
    fireEvent.keyDown(document.body, { code: 'Digit3', key: '3' });
    await waitFor(() => expect(world.style.transform).toBe(jumped));
    expect(server.puts).toEqual([]);
  });

  it('switches canvases, saving what is pending first', async () => {
    installServer({ version: 1, nodes: [node('n', 'note', { payload: { text: 'x' } })] });
    server.handlers.push((method, path) => {
      if (method === 'POST' && path.endsWith('/canvases')) return ok({ id: 'cv2', project_id: 'p1', title: '画布 2', bookmarks: [], version: 0 });
      return undefined;
    });
    await openCanvas();
    fireEvent.change(await screen.findByLabelText('文本'), { target: { value: '没存的' } });
    server.handlers.push((method, path) => {
      if (method === 'GET' && path.endsWith('/canvas') && (server.calls[server.calls.length - 1].path)) return undefined;
      return undefined;
    });
    fireEvent.click(screen.getByRole('button', { name: '新建画布' }));
    await waitFor(() => expect(server.puts.some(item => item.nodes[0]?.payload.text === '没存的')).toBe(true));
    expect(await screen.findByRole('option', { name: '画布 2' })).toBeTruthy();
    expect((screen.getByLabelText('切换画布') as HTMLSelectElement).value).toBe('cv2');
  });

  it('does not close over an unsaved conflict without asking', async () => {
    installServer({ version: 1, nodes: [node('n', 'note', { payload: { text: 'x' } })] });
    const { onClose } = await openCanvas();
    server.conflict = true;
    fireEvent.change(await screen.findByLabelText('文本'), { target: { value: '要丢了' } });
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(await screen.findByText('还有修改没保存成功。')).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '放弃修改并关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  describe('running', () => {
    const ASSESS = {
      decision: 'admitted',
      nodes: [{ node_id: 'gen', kind: 'image_gen', label: '图', medium: 'image', model: 'seedream', quote: 'generate', paid: true, problems: [], requested_seconds: 0, scripted_seconds: 0, estimate: { priced: true, cost: 0.2, currency: 'CNY' } }],
      confirmations: [],
      estimate: { items: 1, paid_items: 1, unpriced_items: 0, totals: [{ currency: 'CNY', cost: 0.2 }] },
    };

    it('saves first, quotes, and spends only after the person confirms', async () => {
      installServer({ version: 1, nodes: [node('gen', 'image_gen', { payload: { label: '图', prompt: '雨夜' } })] });
      const starts: Array<Record<string, unknown>> = [];
      server.handlers.push((method, path, body) => {
        if (path.endsWith('/canvas/runs/assess')) return ok(ASSESS);
        if (method === 'POST' && path.endsWith('/canvas/runs')) {
          starts.push(body as Record<string, unknown>);
          return ok({ status: 'started', batch_id: 'b1', runs: [] });
        }
        return undefined;
      });
      await openCanvas();
      fireEvent.click(await screen.findByRole('button', { name: '运行' }));
      const dialog = await screen.findByRole('dialog', { name: '确认运行' });
      expect(within(dialog).getByText(/0.2 CNY/, { selector: 'p' })).toBeTruthy();
      expect(starts).toEqual([]);

      fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: '确认运行' })).toBeNull());
      expect(starts).toEqual([]);

      fireEvent.click(screen.getByRole('button', { name: '运行' }));
      fireEvent.click(within(await screen.findByRole('dialog', { name: '确认运行' })).getByRole('button', { name: '确认并运行' }));
      await waitFor(() => expect(starts).toHaveLength(1));
      expect(starts[0]).toMatchObject({ node_ids: ['gen'], expected_version: 1, confirm: true });
      expect(String(starts[0].operation_id)).toMatch(/^op_/);
    });

    it('shows a blocked batch with its reasons and no way to proceed', async () => {
      installServer({ version: 1, nodes: [node('vid', 'video_gen', { payload: { label: '视频' } })] });
      server.handlers.push((_, path) => {
        if (path.endsWith('/canvas/runs/assess')) {
          return ok({
            ...ASSESS, decision: 'blocked',
            nodes: [{ ...ASSESS.nodes[0], node_id: 'vid', kind: 'video_gen', label: '视频', quote: 'blocked', problems: [{ code: 'no_reference', message: '禁止文生视频', blocking: true }] }],
          });
        }
        return undefined;
      });
      await openCanvas();
      fireEvent.click(await screen.findByRole('button', { name: '运行' }));
      const dialog = await screen.findByRole('dialog', { name: '这批节点不能运行' });
      expect(within(dialog).getByText('禁止文生视频')).toBeTruthy();
      expect(within(dialog).queryByRole('button', { name: /确认/ })).toBeNull();
    });

    it('requires the duration tiers to be accepted before it can confirm', async () => {
      installServer({ version: 1, nodes: [node('vid', 'video_gen', { payload: { label: '视频' } })] });
      const starts: Array<{ confirmed_request_durations: unknown[] }> = [];
      server.handlers.push((method, path, body) => {
        if (path.endsWith('/canvas/runs/assess')) return ok({ ...ASSESS, decision: 'confirmation_required', confirmations: [{ scripted_seconds: 7, requested_seconds: 10, shot_count: 1 }] });
        if (method === 'POST' && path.endsWith('/canvas/runs')) {
          starts.push(body as { confirmed_request_durations: unknown[] });
          return ok({ status: 'started', batch_id: 'b1' });
        }
        return undefined;
      });
      await openCanvas();
      fireEvent.click(await screen.findByRole('button', { name: '运行' }));
      const dialog = await screen.findByRole('dialog', { name: '确认运行' });
      const go = within(dialog).getByRole('button', { name: '确认并运行' }) as HTMLButtonElement;
      expect(go.disabled).toBe(true);
      fireEvent.click(within(dialog).getByRole('checkbox'));
      expect(go.disabled).toBe(false);
      fireEvent.click(go);
      await waitFor(() => expect(starts[0]?.confirmed_request_durations).toEqual([{ scripted_seconds: 7, requested_seconds: 10 }]));
    });

    it('shows the result, keeps a history, restores and deletes', async () => {
      installServer({ version: 1, nodes: [node('gen', 'image_gen', { payload: { label: '图', prompt: '雨夜' } })], outputs: { gen: { medium: 'image', url: '/media/new.png', run_id: 'r2' } } });
      const history = {
        node_id: 'gen', active_run_id: 'r2',
        runs: [
          { id: 'r2', node_id: 'gen', batch_id: 'b', medium: 'image', status: 'done', model: 'm', request: {}, output: { medium: 'image', url: '/media/new.png' }, error: null, created_at: '2026-01-02T00:00:00Z' },
          { id: 'r1', node_id: 'gen', batch_id: 'b', medium: 'image', status: 'done', model: 'm', request: {}, output: { medium: 'image', url: '/media/old.png' }, error: null, created_at: '2026-01-01T00:00:00Z' },
        ],
      };
      const actions: string[] = [];
      server.handlers.push((method, path) => {
        if (path.endsWith('/nodes/gen/history')) return ok(history);
        if (path.endsWith('/history/r1/restore')) {
          actions.push('restore');
          return ok({ ...history, active_run_id: 'r1' });
        }
        if (method === 'DELETE' && path.endsWith('/history/r2')) {
          actions.push('delete');
          return ok({ ...history, active_run_id: 'r1', runs: [history.runs[1]] });
        }
        return undefined;
      });
      await openCanvas();
      const framed = await screen.findByTestId('node-gen');
      await waitFor(() => expect(framed.querySelector('img')?.getAttribute('src')).toBe('http://localhost:8000/media/new.png'));
      pointer('pointerDown', within(framed).getByText('图'), 5, 5);
      pointer('pointerUp', within(framed).getByText('图'), 5, 5);
      const strip = await screen.findByText('生成记录');
      const panel = strip.closest('.cn-history') as HTMLElement;
      await waitFor(() => expect(panel.querySelectorAll('li')).toHaveLength(2));
      fireEvent.click(within(panel).getByRole('button', { name: '恢复' }));
      await waitFor(() => expect(actions).toEqual(['restore']));
      fireEvent.click(within(panel).getAllByRole('button', { name: '删除这次生成' })[0]);
      await waitFor(() => expect(panel.querySelectorAll('li')).toHaveLength(1));
    });
  });

  describe('previz', () => {
    function previzServer() {
      installServer({
        version: 1,
        nodes: [
          node('img', 'media', { x: 0, payload: { label: '图', output: { medium: 'image', url: '/media/ref.png', provenance: { origin: 'upload' } } } }),
          node('pv', 'previz', { x: 400, payload: { label: '预演节点', sceneId: 'E1S01', shotId: 1 } }),
        ],
        edges: [{ id: 'e', source: 'img', target: 'pv', kind: 'reference', payload: { role: 'blockout_image' } }],
      });
      server.handlers.push((_, path) => {
        if (path === '/api/drama/t1/spatial/scenes/E1S01') {
          return ok({ plan: { actors: [{}, {}], landmarks: [{}], crowds: [], timelines: { 1: { duration_s: 4, fps: 24 }, 2: { duration_s: 9, fps: 24 } } } });
        }
        if (path === '/api/drama/t1/director-desk/scenes/E1S01/captures') {
          return ok({
            captures: [
              { id: 'still1', kind: 'still', shot_id: 1, url: 'http://x/desk_a.png', created_at: '2', stale: false },
              { id: 'clip1', kind: 'clip', shot_id: 1, url: 'http://x/desk_b.mp4', duration_s: 3, fps: 24, created_at: '1', stale: false },
              { id: 'old', kind: 'still', shot_id: 1, url: 'http://x/desk_c.png', created_at: '0', stale: true },
              { id: 'back', kind: 'backdrop', shot_id: 0, url: 'http://x/desk_d.png', created_at: '0', stale: false },
              { id: 'other', kind: 'still', shot_id: 2, url: 'http://x/desk_e.png', created_at: '0', stale: false },
            ],
            applied: {},
          });
        }
        return undefined;
      });
    }

    it('shows object and frame counts for its shot, and its captures as selectable outputs', async () => {
      previzServer();
      await openCanvas();
      const framed = await screen.findByTestId('node-pv');
      expect(await within(framed).findByText('3 个对象 · 96 帧')).toBeTruthy();
      const boxes = await within(framed).findAllByRole('checkbox') as HTMLInputElement[];
      // The backdrop and another shot's capture are not outputs of this node; the stale one is shown but cannot be picked.
      expect(boxes).toHaveLength(3);
      expect(boxes.filter(box => box.disabled)).toHaveLength(1);
      fireEvent.click(boxes.find(box => !box.disabled)!);
      await waitForSave();
      expect(server.puts[0].nodes.find(item => item.id === 'pv')?.payload.selectedCaptureIds).toEqual(['still1']);
    });

    it('opens the desk lazily with the upstream picture, keeps canvas keys out of it, and re-reads on close', async () => {
      previzServer();
      await openCanvas();
      const framed = await screen.findByTestId('node-pv');
      pointer('pointerDown', within(framed).getByText('预演节点'), 5, 5);
      pointer('pointerUp', within(framed).getByText('预演节点'), 5, 5);
      fireEvent.click(await within(framed).findByRole('button', { name: '打开预演台' }));
      const args = JSON.parse((await screen.findByTestId('desk-args')).textContent!);
      expect(args).toEqual({ sceneId: 'E1S01', initialShotId: 1, initialSideTab: 'blockout', initialReference: { url: 'http://localhost:8000/media/ref.png' } });

      // Delete pressed over the desk must not delete the selected node underneath it.
      fireEvent.keyDown(screen.getByLabelText('inside the desk'), { key: 'Delete' });
      press('Delete');
      expect(screen.getByTestId('node-pv')).toBeTruthy();

      const before = server.calls.filter(call => call.path.endsWith('/captures')).length;
      fireEvent.click(screen.getByRole('button', { name: 'close desk' }));
      await waitFor(() => expect(server.calls.filter(call => call.path.endsWith('/captures')).length).toBeGreaterThan(before));
      press('Delete');
      await waitFor(() => expect(screen.queryByTestId('node-pv')).toBeNull());
    });
  });

  it('keeps the upload note until every dropped file has finished, and leaves the reason when one fails', async () => {
    installServer();
    const finish: Array<(response: Response) => void> = [];
    server.handlers.push((method, path) => (
      method === 'POST' && path.endsWith('/canvas/uploads')
        ? new Promise<Response>(resolve => { finish.push(resolve); })
        : undefined
    ));
    await openCanvas();
    const files = [new File(['a'], 'a.png', { type: 'image/png' }), new File(['b'], 'b.png', { type: 'image/png' })];
    fireEvent.drop(surface(), { dataTransfer: { files } });

    const note = () => document.querySelector('.cn-notice')?.textContent ?? '';
    await waitFor(() => expect(note()).toContain('上传中：已完成 0/2…'));
    await waitFor(() => expect(finish).toHaveLength(2));

    // The first one landing does not clear the note for the one still on its way.
    await act(async () => { finish[0](ok({ medium: 'image', url: '/media/a.png', filename: 'a.png' })); });
    await waitFor(() => expect(note()).toContain('上传中：已完成 1/2…'));

    await act(async () => {
      finish[1]({ ok: false, status: 413, json: async () => ({ detail: '文件太大' }) } as Response);
    });
    await waitFor(() => expect(note()).toContain('文件太大'));

    // A single file afterwards starts a fresh count and clears the note once it lands.
    fireEvent.drop(surface(), { dataTransfer: { files: [files[0]] } });
    await waitFor(() => expect(note()).toContain('上传中…'));
    expect(note()).not.toContain('已完成');
    await waitFor(() => expect(finish).toHaveLength(3));
    await act(async () => { finish[2](ok({ medium: 'image', url: '/media/a2.png', filename: 'a.png' })); });
    await waitFor(() => expect(document.querySelector('.cn-notice')).toBeNull());
  });

  it('mounts the panorama viewer only on request, so a canvas of them holds one WebGL context', async () => {
    installServer({ version: 1, nodes: [node('p', 'panorama', { payload: { label: '全景', output: { medium: 'image', url: '/media/pano.jpg' } } })] });
    await openCanvas();
    const framed = await screen.findByTestId('node-p');
    expect(screen.queryByTestId('panorama')).toBeNull();
    pointer('pointerDown', within(framed).getByText('全景'), 5, 5);
    pointer('pointerUp', within(framed).getByText('全景'), 5, 5);

    // No WebGL: said in the node, nothing mounted, the canvas carries on.
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    fireEvent.click(await within(framed).findByRole('button', { name: '进入全景' }));
    expect(await within(framed).findByText('全景视图打开失败，这个浏览器可能不支持 WebGL。')).toBeTruthy();
    expect(screen.queryByTestId('panorama')).toBeNull();

    // Only WebGL is faked: the minimap's 2D context stays absent (it now shares the canvas element type).
    getContext.mockImplementation(((kind: string) => (kind === '2d' ? null : {})) as never);
    fireEvent.click(within(framed).getByRole('button', { name: '进入全景' }));
    expect((await screen.findByTestId('panorama')).textContent).toBe('/media/pano.jpg');

    // The picture cannot be read: back to the flat picture with the reason, and entering again clears it.
    fireEvent.click(screen.getByRole('button', { name: 'panorama fails to load' }));
    expect(await within(framed).findByText('全景图读取失败，已退回平面图。')).toBeTruthy();
    expect(screen.queryByTestId('panorama')).toBeNull();
    fireEvent.click(within(framed).getByRole('button', { name: '进入全景' }));
    expect(await screen.findByTestId('panorama')).toBeTruthy();
    expect(within(framed).queryByText('全景图读取失败，已退回平面图。')).toBeNull();
  });

  describe('commit', () => {
    const PREVIEW = {
      version: 1,
      nodes: [
        { node_id: 'gen', label: '图', kind: 'image_gen', medium: 'image', url: '/media/a.png', target_kind: 'asset', impact: { count: 2, shots: [{ scene_id: 'E1S01', shot_id: 1, desc: '' }, { scene_id: 'E1S01', shot_id: 2, desc: '' }] }, state: 'ready', reason: '', applies_to_shots: true },
        { node_id: 'anon', label: '来路不明', kind: 'media', medium: null, url: null, target_kind: null, impact: { count: 0, shots: [] }, state: 'no_provenance', reason: '', applies_to_shots: false },
      ],
      counts: { ready: 1, no_provenance: 1, already: 0, no_result: 0 },
      impacted_shots: 2,
    };

    it('previews the impact, commits, reports what was skipped, and retries what failed', async () => {
      installServer({ version: 1, nodes: [node('gen', 'image_gen', { payload: { label: '图' } }), node('anon', 'media', { x: 400, payload: { label: '来路不明' } })] });
      const commits: string[][] = [];
      let attempt = 0;
      server.handlers.push((method, path, body) => {
        if (path.endsWith('/canvas/commit/preview')) return ok(PREVIEW);
        if (method === 'POST' && path.endsWith('/canvas/commit')) {
          commits.push((body as { node_ids: string[] }).node_ids);
          attempt += 1;
          const canvas = { project_id: 'p1', version: server.version + attempt, nodes: server.nodes, edges: [], created_at: '' };
          return ok(attempt === 1
            ? { version: canvas.version, canvas, results: [{ node_id: 'gen', label: '图', status: 'failed', reason: '存储暂不可用' }, { node_id: 'anon', label: '来路不明', status: 'skipped', state: 'no_provenance' }], counts: { committed: 0, failed: 1, skipped: 1, no_provenance: 1 } }
            : { version: canvas.version, canvas, results: [{ node_id: 'gen', label: '图', status: 'committed' }], counts: { committed: 1, failed: 0, skipped: 0, no_provenance: 0 } });
        }
        return undefined;
      });
      await openCanvas();
      await screen.findByTestId('node-gen');
      press('a', { ctrlKey: true });
      fireEvent.click(await screen.findByRole('button', { name: /提交所选/ }));
      const dialog = await screen.findByRole('dialog', { name: '提交到项目' });
      expect(await within(dialog).findByText('影响 2 个镜头', { selector: 'p' })).toBeTruthy();
      expect(within(dialog).getByText('没有来源记录，跳过')).toBeTruthy();
      expect(within(dialog).getByText('将跳过 1 个：没有来源 1，没有结果 0，已提交 0')).toBeTruthy();
      // Only a video bound to shots gets the note about becoming a version of the shot.
      expect(within(dialog).queryByText(/可「选用此版」的版本/)).toBeNull();

      fireEvent.click(within(dialog).getByRole('button', { name: '提交 1 个节点' }));
      expect(await within(dialog).findByText('存储暂不可用')).toBeTruthy();
      expect(within(dialog).getByText(/已提交 0 个，跳过 1 个（其中没有来源 1 个），失败 1 个/)).toBeTruthy();
      expect(commits[0]).toEqual(['gen']);

      fireEvent.click(within(dialog).getByRole('button', { name: '重试失败的 1 个' }));
      await waitFor(() => expect(commits[1]).toEqual(['gen']));
      expect(await within(dialog).findByText(/已提交 1 个/)).toBeTruthy();
    });

    it('says a committed video also becomes a version the shot can pick', async () => {
      installServer({ version: 1, nodes: [node('clip', 'video_gen', { payload: { label: '视频' } })] });
      const video = { ...PREVIEW.nodes[0], node_id: 'clip', label: '视频', kind: 'video_gen', medium: 'video', url: '/media/v.mp4', target_kind: 'clip' };
      server.handlers.push((_method, path) => (path.endsWith('/canvas/commit/preview')
        ? ok({ ...PREVIEW, nodes: [video], counts: { ready: 1, no_provenance: 0, already: 0, no_result: 0 } })
        : undefined));
      await openCanvas();
      await screen.findByTestId('node-clip');
      press('a', { ctrlKey: true });
      fireEvent.click(await screen.findByRole('button', { name: /提交所选/ }));
      const dialog = await screen.findByRole('dialog', { name: '提交到项目' });
      expect(await within(dialog).findByText(/已经出过片的镜头，还会在镜头工作台里多一个可「选用此版」的版本/)).toBeTruthy();
    });
  });

  it('lists canvas versions and restores one as a new version', async () => {
    installServer({ version: 2, nodes: [node('n', 'note', { payload: { text: '现在' } })] });
    server.handlers.push((method, path) => {
      if (method === 'GET' && path.endsWith('/canvas/versions')) {
        return ok({ versions: [{ version: 2, created_at: '2026-01-02T00:00:00Z', node_count: 1, edge_count: 0 }, { version: 1, created_at: '2026-01-01T00:00:00Z', node_count: 1, edge_count: 0 }] });
      }
      if (path.endsWith('/versions/1/restore')) return ok({ project_id: 'p1', version: 3, nodes: [node('n', 'note', { payload: { text: '从前' } })], edges: [], created_at: '' });
      return undefined;
    });
    await openCanvas();
    fireEvent.click(screen.getByRole('tab', { name: '版本' }));
    fireEvent.click(await screen.findByRole('button', { name: '恢复' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认恢复' }));
    await waitFor(() => expect((screen.getByLabelText('文本') as HTMLTextAreaElement).value).toBe('从前'));
    expect(await screen.findByText(/已恢复到第 1 版/)).toBeTruthy();
    expect(server.puts).toEqual([]);
  });

  describe('infinite canvas', () => {
    function viewOf() {
      const world = surface().querySelector<HTMLElement>('.cn-world')!;
      const match = /translate\((-?[\d.e+-]+)px, (-?[\d.e+-]+)px\) scale\(([\d.e+-]+)\)/.exec(world.style.transform)!;
      return { x: Number(match[1]), y: Number(match[2]), zoom: Number(match[3]) };
    }

    /** The world point at the centre of the 1200×800 surface jsdom reports (it has no layout). */
    function centreOf(view = viewOf()) {
      return { x: (600 - view.x) / view.zoom, y: (400 - view.y) / view.zoom };
    }

    function click(element: Element, extra: Record<string, unknown> = {}) {
      pointer('pointerDown', element, 5, 5, extra);
      pointer('pointerUp', element, 5, 5, extra);
    }

    const lastPut = () => server.puts[server.puts.length - 1];

    it('zooms from the controls and the keyboard, and fits all or the selection with Mod+1 / Mod+2', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } }), node('b', 'note', { x: 3000, y: 2000, payload: { label: '乙' } })] });
      await openCanvas();
      await screen.findByTestId('node-a');
      const fitted = viewOf().zoom;
      expect(fitted).toBeLessThan(0.5);
      const percent = () => screen.getByRole('button', { name: '精确缩放' }).textContent;

      fireEvent.click(screen.getByRole('button', { name: '放大' }));
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(fitted + 0.1, 2));
      press('0', { ctrlKey: true, code: 'Digit0' });
      await waitFor(() => expect(viewOf().zoom).toBe(1));
      expect(percent()).toBe('100%');
      press('-', { metaKey: true });
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(0.9, 5));
      press('=', { ctrlKey: true });
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(1, 5));

      press('1', { ctrlKey: true, code: 'Digit1' });
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(fitted, 5));

      // Mod+2 with nothing selected leaves the view alone; with a node selected it frames that node.
      press('2', { ctrlKey: true, code: 'Digit2' });
      await new Promise(resolve => setTimeout(resolve, 50));
      expect(viewOf().zoom).toBeCloseTo(fitted, 5);
      click(within(screen.getByTestId('node-b')).getByText('乙'));
      press('2', { ctrlKey: true, code: 'Digit2' });
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(1.25, 5));
      expect(centreOf().x).toBeCloseTo(3100, 0);
      expect(centreOf().y).toBeCloseTo(2075, 0);
      fireEvent.click(screen.getByRole('button', { name: '适应画布' }));
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(fitted, 5));
      expect(server.puts).toEqual([]);
    });

    it('finds a node with Mod+F, glides to it and selects it', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } }), node('far', 'note', { x: 5000, y: 3000, payload: { label: '远方', text: '雨夜的码头' } })] });
      await openCanvas();
      press('f', { ctrlKey: true });
      const field = await screen.findByRole('combobox', { name: '搜索节点' });
      fireEvent.change(field, { target: { value: '码头' } });
      expect(await screen.findByRole('option', { name: /远方/ })).toBeTruthy();
      fireEvent.keyDown(field, { key: 'Enter' });
      await waitFor(() => expect(screen.queryByRole('dialog', { name: '搜索节点' })).toBeNull());
      // Far out, a hit is shown at a readable zoom (focusRect's 72% floor), centred.
      await waitFor(() => expect(viewOf().zoom).toBeCloseTo(0.72, 5));
      expect(centreOf().x).toBeCloseTo(5100, 0);
      expect(centreOf().y).toBeCloseTo(3075, 0);
      expect(screen.getByRole('button', { name: /提交所选/ }).textContent).toContain('(1)');
      expect(await screen.findByTestId('node-far')).toBeTruthy();
    });

    it('adds a node where the canvas menu was opened, and deletes it from its own menu', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } })] });
      await openCanvas();
      await screen.findByTestId('node-a');
      const view = viewOf();
      fireEvent.contextMenu(surface(), { clientX: 300, clientY: 200 });
      fireEvent.click(await screen.findByRole('menuitem', { name: '添加节点' }));
      fireEvent.click(await screen.findByRole('menuitem', { name: kindLabel('image_gen') }));
      expect(screen.queryByRole('menu')).toBeNull();
      await waitForSave();
      const made = lastPut().nodes.find(item => item.kind === 'image_gen')!;
      expect(made.x).toBe(Math.round((300 - view.x) / view.zoom));
      expect(made.y).toBe(Math.round((200 - view.y) / view.zoom));

      const framed = await screen.findByTestId(`node-${made.id}`);
      fireEvent.contextMenu(within(framed).getByText(kindLabel('image_gen'), { selector: 'strong' }), { clientX: 310, clientY: 210 });
      expect(screen.getByRole('menuitem', { name: '重命名' })).toBeTruthy();
      fireEvent.click(screen.getByRole('menuitem', { name: /^删除/ }));
      await waitFor(() => expect(screen.queryByTestId(`node-${made.id}`)).toBeNull());
      await waitFor(() => expect(lastPut().nodes.map(item => item.id)).toEqual(['a']), { timeout: 3000 });
    });

    it('offers the kinds that take an output when a connection is dropped on empty canvas, and wires the new node', async () => {
      installServer({ version: 1, nodes: [node('gen', 'image_gen', { payload: { label: '图' } })] });
      await openCanvas();
      const port = (await screen.findByTestId('node-gen')).querySelector('[data-port="out"]')!;
      pointer('pointerDown', port, 200, 75);
      pointer('pointerMove', port, 700, 300);
      pointer('pointerUp', port, 700, 300);
      const picker = await screen.findByRole('menu', { name: '新建并连接' });
      const offered = within(picker).getAllByRole('menuitem').map(item => item.textContent);
      expect(offered).toContain(kindLabel('video_gen'));
      expect(offered).not.toContain(kindLabel('note'));
      fireEvent.click(within(picker).getByRole('menuitem', { name: kindLabel('video_gen') }));
      await waitForSave();
      const made = lastPut().nodes.find(item => item.kind === 'video_gen')!;
      expect(lastPut().edges).toEqual([expect.objectContaining({ source: 'gen', target: made.id, kind: 'reference' })]);
    });

    it('aligns a multi-selection from its floating toolbar, as one undoable edit', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲' } }), node('b', 'note', { x: 300, y: 120, payload: { label: '乙' } })] });
      await openCanvas();
      await screen.findByTestId('node-b');
      expect(screen.queryByRole('toolbar', { name: '选区工具栏' })).toBeNull();
      press('a', { ctrlKey: true });
      const bar = await screen.findByRole('toolbar', { name: '选区工具栏' });
      fireEvent.click(within(bar).getByRole('button', { name: '顶对齐' }));
      await waitFor(() => expect(screen.getByTestId('node-b').style.transform).toBe('translate(300px, 0px)'));
      await waitForSave();
      expect(lastPut().nodes.find(item => item.id === 'b')).toMatchObject({ x: 300, y: 0 });
      press('z', { ctrlKey: true });
      await waitFor(() => expect(screen.getByTestId('node-b').style.transform).toBe('translate(300px, 120px)'));
    });

    it('folds a group: its members are not drawn and their edges attach to the group', async () => {
      installServer({
        version: 1,
        nodes: [
          node('a', 'note', { payload: { label: '甲' } }), node('b', 'note', { x: 0, y: 200, payload: { label: '乙' } }),
          node('gen', 'image_gen', { x: 700, y: 0, payload: { label: '图' } }),
        ],
        edges: [{ id: 'e1', source: 'a', target: 'gen', kind: 'dependency', payload: { role: 'prompt' } }],
      });
      await openCanvas();
      click(within(await screen.findByTestId('node-a')).getByText('甲'));
      click(within(screen.getByTestId('node-b')).getByText('乙'), { shiftKey: true });
      press('g', { ctrlKey: true });
      const head = await waitFor(() => {
        const found = surface().querySelector('.cn-group__head');
        expect(found).toBeTruthy();
        return found!;
      });
      fireEvent.doubleClick(head);
      await waitFor(() => expect(screen.queryByTestId('node-a')).toBeNull());
      expect(screen.queryByTestId('node-b')).toBeNull();
      expect(surface().querySelector('.cn-group.is-collapsed')?.textContent).toContain('2 个节点');
      expect(surface().querySelector('[data-edge-id="e1"]')).toBeTruthy();
      await waitForSave();
      expect(lastPut().nodes.find(item => item.kind === 'group')?.payload.collapsed).toBe(true);

      fireEvent.click(screen.getByRole('button', { name: '展开分组' }));
      expect(await screen.findByTestId('node-a')).toBeTruthy();
    });

    it('pastes a copied result hung on the same upstream node, from the paste event or the Mod+V fallback', async () => {
      installServer({
        version: 1,
        nodes: [node('src', 'note', { payload: { label: '提示', text: '雨夜' } }), node('gen', 'image_gen', { x: 400, payload: { label: '图' } })],
        edges: [{ id: 'e1', source: 'src', target: 'gen', kind: 'dependency', payload: { role: 'prompt' } }],
      });
      await openCanvas();
      click(within(await screen.findByTestId('node-gen')).getByText('图'));
      press('c', { ctrlKey: true });
      const copied = window.sessionStorage.getItem('novara.canvas.clip');
      expect(copied).toContain('novara-canvas-clip');

      fireEvent.paste(document.body, { clipboardData: { getData: (type: string) => (type === 'text/plain' ? copied : ''), files: [], items: [] } });
      await waitForSave();
      const pasted = lastPut().nodes.filter(item => item.kind === 'image_gen' && item.id !== 'gen');
      expect(pasted).toHaveLength(1);
      expect(lastPut().edges).toEqual(expect.arrayContaining([expect.objectContaining({ source: 'src', target: pasted[0].id, kind: 'dependency', payload: { role: 'prompt' } })]));

      // No paste event (the browser kept the clipboard to itself): this tab's own copy goes in.
      press('v', { ctrlKey: true });
      await waitFor(() => expect(lastPut().nodes.filter(item => item.kind === 'image_gen')).toHaveLength(3), { timeout: 3000 });
    });

    it('exports the canvas as a file and imports it back beside what is there, undoably', async () => {
      installServer({
        version: 1,
        nodes: [node('src', 'note', { payload: { label: '提示' } }), node('gen', 'image_gen', { x: 400, payload: { label: '图' } })],
        edges: [{ id: 'e1', source: 'src', target: 'gen', kind: 'dependency', payload: { role: 'prompt' } }],
      });
      const blobs: Blob[] = [];
      const names: string[] = [];
      Object.assign(URL, { createObjectURL: (blob: Blob) => { blobs.push(blob); return 'blob:canvas'; }, revokeObjectURL: () => undefined });
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
      try {
        await openCanvas();
        await screen.findByTestId('node-gen');
        fireEvent.click(screen.getByRole('button', { name: '导出画布' }));
        // The export button now offers the plain file or a bundle with media; the plain one is the old export.
        fireEvent.click(await screen.findByRole('button', { name: '导出 .json' }));
        expect(names).toEqual(['主画布.novara-canvas.json']);
        const text = await new Promise<string>(resolve => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.readAsText(blobs[0]);
        });
        expect(JSON.parse(text)).toMatchObject({ format: 'novara-canvas', nodes: [{ id: 'src' }, { id: 'gen' }], edges: [{ source: 'src', target: 'gen' }] });

        fireEvent.change(screen.getByLabelText('选择要导入的画布文件'), { target: { files: [new File([text], 'board.json', { type: 'application/json' })] } });
        await waitForSave();
        const saved = lastPut();
        expect(saved.nodes).toHaveLength(4);
        expect(saved.edges).toHaveLength(2);
        const imported = saved.nodes.filter(item => item.id !== 'src' && item.id !== 'gen');
        expect(Math.min(...imported.map(item => item.x))).toBeGreaterThan(600);
        expect(saved.edges[1]).toMatchObject({ source: imported[0].id, target: imported[1].id });
        press('z', { ctrlKey: true });
        await waitFor(() => expect(surface().querySelectorAll('[data-node-id]')).toHaveLength(2));
      } finally {
        delete (URL as unknown as Record<string, unknown>).createObjectURL;
        delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
      }
    });

    it('reloads after the assistant writes, and lights up just the nodes it changed', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲', text: '旧' } }), node('gen', 'image_gen', { x: 400, payload: { label: '图', prompt: '雨' } })] });
      server.handlers.push((method, path) => {
        if (path.endsWith('/canvas/runs/assess')) return ok({ decision: 'admitted', nodes: [], confirmations: [], estimate: { items: 1, paid_items: 0, unpriced_items: 0, totals: [] } });
        if (method === 'POST' && path.endsWith('/canvas/runs')) return ok({ status: 'started', batch_id: 'b1' });
        return undefined;
      });
      await openCanvas();
      await screen.findByTestId('node-a');
      // The assistant edits one node and adds another while the canvas is open.
      server.version = 2;
      server.nodes = [node('a', 'note', { payload: { label: '甲', text: '助手改过' } }), server.nodes[1], node('c', 'note', { x: 0, y: 400, payload: { label: '新的' } })];
      // Starting a run reads the outputs at once, and with them the canvas's new version.
      fireEvent.click(screen.getByRole('button', { name: '运行' }));
      await waitFor(() => expect((screen.getAllByLabelText('文本')[0] as HTMLTextAreaElement).value).toBe('助手改过'));
      expect(await screen.findByText('画布已在别处更新，已载入最新版本。')).toBeTruthy();
      expect(screen.getByTestId('node-a').classList.contains('cn-flash')).toBe(true);
      expect((await screen.findByTestId('node-c')).classList.contains('cn-flash')).toBe(true);
      expect(screen.getByTestId('node-gen').classList.contains('cn-flash')).toBe(false);
      await waitFor(() => expect(screen.getByTestId('node-a').classList.contains('cn-flash')).toBe(false), { timeout: 3000 });
      expect(server.puts).toEqual([]);
    });

    it('lists the shortcuts in groups in the help panel', async () => {
      installServer({ version: 1 });
      await openCanvas();
      press('?');
      const help = await screen.findByRole('complementary', { name: '快捷键' });
      for (const heading of ['视图', '选择', '编辑', '运行']) expect(within(help).getByRole('heading', { name: heading })).toBeTruthy();
      expect(within(help).getByText('搜索节点并跳过去')).toBeTruthy();
    });

    it('switches the background and remembers it per canvas', async () => {
      installServer({ version: 1 });
      await openCanvas();
      const picker = screen.getByRole('combobox', { name: '画布背景' }) as HTMLSelectElement;
      expect(picker.value).toBe('dots');
      fireEvent.change(picker, { target: { value: 'grid' } });
      expect(window.localStorage.getItem('canvas.background.main')).toBe('grid');
      expect(surface().querySelector<HTMLElement>('.cn-backdrop')!.style.backgroundImage).toContain('linear-gradient');
      fireEvent.change(picker, { target: { value: 'blank' } });
      expect(surface().querySelector<HTMLElement>('.cn-backdrop')!.style.backgroundImage).toBe('none');
    });
  });

  describe('other windows on the same canvas', () => {
    class FakeEventSource {
      static instances: FakeEventSource[] = [];
      url: string;
      private listeners = new Map<string, Set<(event: Event) => void>>();
      constructor(url: string) {
        this.url = url;
        FakeEventSource.instances.push(this);
      }
      addEventListener(type: string, listener: (event: Event) => void) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type)!.add(listener);
      }
      removeEventListener(type: string, listener: (event: Event) => void) { this.listeners.get(type)?.delete(listener); }
      close() { /* nothing to close */ }
      emit(type: string, data: unknown) {
        const event = new MessageEvent(type, { data: JSON.stringify(data) });
        act(() => { for (const listener of this.listeners.get(type) ?? []) listener(event); });
      }
    }

    const stream = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];
    const ownId = () => new URL(stream().url).searchParams.get('client_id')!;
    const canvasReads = () => server.calls.filter(call => call.method === 'GET' && call.path.endsWith('/canvas')).length;

    beforeEach(() => {
      FakeEventSource.instances = [];
      vi.stubGlobal('EventSource', FakeEventSource);
    });

    afterEach(() => {
      vi.stubGlobal('EventSource', undefined);
    });

    it('shows the other windows, and reloads at once when one of them saves while nothing here is pending', async () => {
      installServer({ version: 1, nodes: [node('a', 'note', { payload: { label: '甲', text: '旧' } }), node('b', 'note', { x: 400, payload: { label: '乙', text: '乙' } })] });
      await openCanvas();
      await screen.findByTestId('node-a');
      expect(stream().url).toContain('/api/studio/projects/p1/canvases/main/presence/stream?');
      stream().emit('peers', { peers: [{ client_id: ownId(), label: 'me', color: '#000' }, { client_id: 'w2', label: '另一个窗口 · Firefox', color: '#ff0000' }] });
      stream().emit('cursor', { client_id: 'w2', x: 50, y: 60 });
      expect(await screen.findByText('同时打开：1 个窗口')).toBeTruthy();
      await waitFor(() => expect(document.querySelector('.cpl-cursor')?.textContent).toBe('另一个窗口 · Firefox'));

      // Its own save coming back is not news.
      const before = canvasReads();
      stream().emit('saved', { version: 1, client_id: ownId() });
      server.version = 2;
      server.nodes = [node('a', 'note', { payload: { label: '甲', text: '另一个窗口改的' } }), server.nodes[1]];
      stream().emit('saved', { version: 2, client_id: ownId() });
      await act(async () => { await Promise.resolve(); });
      expect(canvasReads()).toBe(before);

      stream().emit('saved', { version: 2, client_id: 'w2' });
      await waitFor(() => expect((screen.getAllByLabelText('文本')[0] as HTMLTextAreaElement).value).toBe('另一个窗口改的'));
      expect(canvasReads()).toBe(before + 1);
      expect(await screen.findByText('画布已在别处更新，已载入最新版本。')).toBeTruthy();
      expect(screen.getByTestId('node-a').classList.contains('cn-flash')).toBe(true);
      expect(screen.getByTestId('node-b').classList.contains('cn-flash')).toBe(false);
      expect(server.puts).toEqual([]);
    });

    it('leaves a save from elsewhere to the conflict check while it has edits of its own, and names itself on its saves', async () => {
      installServer({ version: 1, nodes: [node('n', 'note', { payload: { text: '原文' } })] });
      await openCanvas();
      fireEvent.change(await screen.findByLabelText('文本'), { target: { value: '我的修改' } });
      const before = canvasReads();
      server.version = 2;
      server.nodes = [node('n', 'note', { payload: { text: '别的窗口' } })];
      server.conflict = true;
      stream().emit('saved', { version: 2, client_id: 'w2' });
      await act(async () => { await Promise.resolve(); });
      expect(canvasReads()).toBe(before);
      expect((screen.getByLabelText('文本') as HTMLTextAreaElement).value).toBe('我的修改');
      expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toContain('已在别处被修改');
      const put = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PUT');
      expect((put?.[1]?.headers as Record<string, string>)['X-Canvas-Client']).toBe(ownId());
    });
  });

  it('follows a light or dark choice on its own layer', async () => {
    installServer({ version: 0 });
    await openCanvas();
    const layer = screen.getByRole('dialog', { name: '节点画布' });
    expect(layer.dataset.theme).toBe('light');
    fireEvent.click(screen.getByRole('button', { name: '切换到深色' }));
    expect(layer.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem('canvas.theme')).toBe('dark');
  });
});
