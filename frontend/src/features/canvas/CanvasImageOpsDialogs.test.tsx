// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasCropDialog, CanvasGridSplitDialog } from './CanvasImageOpsDialogs';

const BASE = '/api/studio/projects/p1/canvas/nodes/pic';

interface Call { method: string; path: string; query: URLSearchParams; body: Record<string, number> }

function installServer(options: { status?: number; detail?: string } = {}) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = new URL(String(input), 'http://localhost:8000');
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {};
    calls.push({ method: init?.method ?? 'GET', path: url.pathname, query: url.searchParams, body });
    if (options.status) return { ok: false, status: options.status, json: async () => ({ detail: options.detail }) } as Response;
    if (url.pathname === `${BASE}/crop`) {
      return { ok: true, status: 200, json: async () => ({ version: 8, node_ids: ['piece'], source_node_id: 'pic', connected: false, width: 20, height: 10 }) } as Response;
    }
    if (url.pathname === `${BASE}/grid-split`) {
      const node_ids = Array.from({ length: body.rows * body.columns }, (_, index) => `cell${index + 1}`);
      return { ok: true, status: 200, json: async () => ({ version: 8, node_ids, source_node_id: 'pic', connected: false, rows: body.rows, columns: body.columns }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) } as Response;
  });
  return calls;
}

function props(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 'p1', canvasId: 'main', nodeId: 'pic', nodeLabel: '雨街', imageUrl: '/media/board.png',
    prepare: vi.fn(async () => 7), onApplied: vi.fn(), onClose: vi.fn(), ...overrides,
  };
}

// jsdom has no PointerEvent, and without it fireEvent drops the coordinates.
class FakePointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}

/** The picture "loads" at this pixel size, and its stage measures 400 × 200 on screen. */
function loadPicture(width = 400, height = 200) {
  const picture = screen.getByRole('img') as HTMLImageElement;
  Object.defineProperty(picture, 'naturalWidth', { configurable: true, value: width });
  Object.defineProperty(picture, 'naturalHeight', { configurable: true, value: height });
  picture.parentElement!.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 200, width: 400, height: 200, toJSON: () => ({}) });
  fireEvent.load(picture);
}

const rectOf = () => screen.getByRole('group', { name: '裁剪范围' }).getAttribute('data-rect')!.split(',').map(Number);

function drag(element: Element, from: [number, number], to: [number, number]) {
  fireEvent.pointerDown(element, { clientX: from[0], clientY: from[1], button: 0, pointerId: 1 });
  fireEvent(window, new FakePointerEvent('pointermove', { clientX: to[0], clientY: to[1], pointerId: 1 }));
  fireEvent(window, new FakePointerEvent('pointerup', { clientX: to[0], clientY: to[1], pointerId: 1 }));
}

beforeEach(() => {
  vi.stubGlobal('PointerEvent', FakePointerEvent);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('cropping a node\'s picture', () => {
  it('shows the picture with a rectangle once it has loaded, and sends that rectangle on the saved version', async () => {
    const calls = installServer();
    const given = props();
    render(<CanvasCropDialog {...given} />);
    expect(screen.getByRole('dialog', { name: '裁剪：雨街' })).toBeTruthy();
    expect((screen.getByRole('img') as HTMLImageElement).src).toBe('http://localhost:8000/media/board.png');
    // Nothing to crop until the picture is there.
    expect(screen.queryByRole('group', { name: '裁剪范围' })).toBeNull();
    expect((screen.getByRole('button', { name: '裁剪' }) as HTMLButtonElement).disabled).toBe(true);

    loadPicture();
    expect(rectOf()).toEqual([0.1, 0.1, 0.8, 0.8]);
    expect(screen.getByText('裁出 320 × 160 像素')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '裁剪' }));

    await waitFor(() => expect(given.onApplied).toHaveBeenCalledWith(expect.objectContaining({ node_ids: ['piece'], connected: false })));
    expect(given.prepare).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    expect([calls[0].method, calls[0].path, calls[0].query.get('canvas_id')]).toEqual(['POST', `${BASE}/crop`, 'main']);
    expect(calls[0].body).toEqual({ x: 0.1, y: 0.1, w: 0.8, h: 0.8, expected_version: 7 });
    await waitFor(() => expect(given.onClose).toHaveBeenCalled());
  });

  it('the rectangle is dragged, and resized from its handles, in units of the picture', () => {
    installServer();
    render(<CanvasCropDialog {...props()} />);
    loadPicture();
    const box = screen.getByRole('group', { name: '裁剪范围' });
    // 40 px of a 400 px stage is a tenth of the picture.
    drag(box, [200, 100], [240, 80]);
    expect(rectOf()).toEqual([0.2, 0, 0.8, 0.8]);
    // It stops at the picture's edge.
    drag(box, [200, 100], [900, 900]);
    expect(rectOf()).toEqual([0.2, 0.2, 0.8, 0.8]);
    // The bottom-right handle pulls that corner in; the top-left corner stays.
    drag(box.querySelector('[data-handle="se"]')!, [400, 200], [200, 100]);
    expect(rectOf()).toEqual([0.2, 0.2, 0.3, 0.3]);
    expect(screen.getByText('裁出 120 × 60 像素')).toBeTruthy();
    // Pinched past the smallest crop, it stops there.
    drag(box.querySelector('[data-handle="se"]')!, [200, 100], [0, 0]);
    expect(rectOf()).toEqual([0.2, 0.2, 0.06, 0.06]);
  });

  it('arrow keys nudge the rectangle', () => {
    installServer();
    render(<CanvasCropDialog {...props()} />);
    loadPicture();
    const box = screen.getByRole('group', { name: '裁剪范围' });
    fireEvent.keyDown(box, { key: 'ArrowRight' });
    fireEvent.keyDown(box, { key: 'ArrowUp', shiftKey: true });
    expect(rectOf()).toEqual([0.11, 0.05, 0.8, 0.8]);
  });

  it('a shape preset reshapes the rectangle and holds it through a resize', async () => {
    const calls = installServer();
    const given = props();
    render(<CanvasCropDialog {...given} />);
    const ratios = () => screen.getAllByRole('button').filter(button => button.hasAttribute('aria-pressed'));
    expect(ratios().map(button => button.textContent)).toEqual(['自由', '1:1', '9:16', '16:9', '4:3', '3:4']);
    // Shapes need the picture's size: only 自由 before it loads.
    expect(ratios().map(button => (button as HTMLButtonElement).disabled)).toEqual([false, true, true, true, true, true]);

    loadPicture(400, 200);
    expect(ratios().every(button => !(button as HTMLButtonElement).disabled)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '1:1' }));
    expect(screen.getByRole('button', { name: '1:1' }).getAttribute('aria-pressed')).toBe('true');
    // A square in pixels: on a 2:1 picture, half as wide in units as it is tall.
    let [x, y, w, h] = rectOf();
    expect([x, y, w, h]).toEqual([0.3, 0.1, 0.4, 0.8]);
    expect(screen.getByText('裁出 160 × 160 像素')).toBeTruthy();

    drag(screen.getByRole('group', { name: '裁剪范围' }).querySelector('[data-handle="se"]')!, [280, 180], [240, 180]);
    [x, y, w, h] = rectOf();
    expect([x, y]).toEqual([0.3, 0.1]);
    expect(w).toBeCloseTo(0.3);
    expect(w * 400).toBeCloseTo(h * 200);

    fireEvent.click(screen.getByRole('button', { name: '裁剪' }));
    await waitFor(() => expect(given.onApplied).toHaveBeenCalled());
    expect(calls[0].body.w * 400).toBeCloseTo(calls[0].body.h * 200);
  });

  it('a shape this picture is too thin for is not offered', () => {
    installServer();
    render(<CanvasCropDialog {...props()} />);
    loadPicture(4000, 200);
    expect((screen.getByRole('button', { name: '9:16' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '16:9' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('says why when the canvas cannot be saved first or the server refuses, and stays open', async () => {
    const calls = installServer();
    const blocked = props({ prepare: vi.fn(async () => { throw new Error('画布还没保存成功，先解决保存问题。'); }) });
    const view = render(<CanvasCropDialog {...blocked} />);
    loadPicture();
    fireEvent.click(screen.getByRole('button', { name: '裁剪' }));
    expect((await screen.findByRole('alert')).textContent).toContain('画布还没保存成功');
    expect(calls).toHaveLength(0);
    expect(blocked.onApplied).not.toHaveBeenCalled();
    expect(blocked.onClose).not.toHaveBeenCalled();
    view.unmount();
    vi.restoreAllMocks();

    installServer({ status: 422, detail: '这个节点还没有图片，先上传或生成一张' });
    const refused = props();
    render(<CanvasCropDialog {...refused} />);
    loadPicture();
    fireEvent.click(screen.getByRole('button', { name: '裁剪' }));
    expect((await screen.findByRole('alert')).textContent).toBe('这个节点还没有图片，先上传或生成一张');
    expect(refused.onClose).not.toHaveBeenCalled();
    // And it can be tried again.
    expect((screen.getByRole('button', { name: '裁剪' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('a picture that will not load cannot be cropped; Escape and 取消 close', () => {
    installServer();
    const given = props();
    render(<CanvasCropDialog {...given} />);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByRole('alert').textContent).toBe('图片加载失败，裁不了。');
    expect((screen.getByRole('button', { name: '裁剪' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(given.onClose).toHaveBeenCalledTimes(2);
  });
});

describe('cutting a node\'s picture into a grid', () => {
  const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;
  const submit = () => screen.getByRole('button', { name: '拆分' }) as HTMLButtonElement;

  it('starts at 2 × 2 and sends the rows and columns on the saved version', async () => {
    const calls = installServer();
    const given = props();
    const { container } = render(<CanvasGridSplitDialog {...given} />);
    expect(screen.getByRole('dialog', { name: '宫格拆分：雨街' })).toBeTruthy();
    expect([field('行数').value, field('列数').value]).toEqual(['2', '2']);
    expect(screen.getByText('将拆成 4 张图片')).toBeTruthy();
    expect(container.querySelectorAll('.cio-grid span')).toHaveLength(4);

    fireEvent.change(field('行数'), { target: { value: '3' } });
    fireEvent.change(field('列数'), { target: { value: '4' } });
    expect(screen.getByText('将拆成 12 张图片')).toBeTruthy();
    expect(container.querySelectorAll('.cio-grid span')).toHaveLength(12);
    expect((container.querySelector('.cio-grid') as HTMLElement).style.gridTemplateColumns).toBe('repeat(4, 1fr)');
    fireEvent.click(submit());

    await waitFor(() => expect(given.onApplied).toHaveBeenCalledWith(expect.objectContaining({ rows: 3, columns: 4 })));
    expect([calls[0].method, calls[0].path, calls[0].query.get('canvas_id')]).toEqual(['POST', `${BASE}/grid-split`, 'main']);
    expect(calls[0].body).toEqual({ rows: 3, columns: 4, expected_version: 7 });
    expect(given.onApplied.mock.calls[0][0].node_ids).toHaveLength(12);
    await waitFor(() => expect(given.onClose).toHaveBeenCalled());
  });

  it('will not split 1 × 1, or outside 1 to 12, or by something that is not a whole number', () => {
    const calls = installServer();
    render(<CanvasGridSplitDialog {...props()} />);
    const set = (rows: string, columns: string) => {
      fireEvent.change(field('行数'), { target: { value: rows } });
      fireEvent.change(field('列数'), { target: { value: columns } });
    };
    set('1', '1');
    expect(submit().disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toBe('1 × 1 就是原图本身，不用拆分。');
    for (const [rows, columns] of [['13', '2'], ['0', '2'], ['2', ''], ['2.5', '2'], ['-1', '3']]) {
      set(rows, columns);
      expect(submit().disabled, `${rows} × ${columns}`).toBe(true);
      expect(screen.getByRole('alert').textContent, `${rows} × ${columns}`).toBe('行数和列数都要是 1 到 12 之间的整数。');
    }
    fireEvent.submit(screen.getByRole('dialog'));
    expect(calls).toHaveLength(0);
    // A single row or column is a split, and so is the largest grid.
    set('1', '12');
    expect(submit().disabled).toBe(false);
    set('12', '12');
    expect(screen.getByText('将拆成 144 张图片')).toBeTruthy();
  });

  it('presets fill both numbers', () => {
    installServer();
    render(<CanvasGridSplitDialog {...props()} />);
    expect(screen.getByRole('button', { name: '2 × 2' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: '3 × 3' }));
    expect([field('行数').value, field('列数').value]).toEqual(['3', '3']);
    expect(screen.getByText('将拆成 9 张图片')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '1 × 3' }));
    expect([field('行数').value, field('列数').value]).toEqual(['1', '3']);
  });

  it('says why when the server refuses, and stays open', async () => {
    installServer({ status: 409, detail: 'canvas version conflict: expected 7, latest is 8' });
    const given = props();
    render(<CanvasGridSplitDialog {...given} />);
    fireEvent.click(submit());
    expect((await screen.findByRole('alert')).textContent).toContain('canvas version conflict');
    expect(given.onApplied).not.toHaveBeenCalled();
    expect(given.onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(given.onClose).toHaveBeenCalledTimes(1);
  });
});
