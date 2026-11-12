// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { SharedCanvas } from '../canvas/canvasShareApi';
import type { CanvasNode } from '../canvas/canvasTypes';
import { SharedCanvasEntry } from './SharedCanvasEntry';
import { SharedCanvasPage } from './SharedCanvasPage';

const TOKEN = 'abcdefghijklmnop';

const node = (id: string, kind: CanvasNode['kind'], patch: Partial<CanvasNode> = {}): CanvasNode => ({
  id, kind, track: 'freezone', x: 0, y: 0, width: 240, height: 180, artifact_id: null, payload: {}, ...patch,
});

const CANVAS: SharedCanvas = {
  title: '第一集分镜',
  canvas_id: 'main',
  version: 3,
  nodes: [
    node('img', 'image_gen', { payload: { title: '女主定妆', prompt: '雨夜街头' } }),
    node('vid', 'video_gen', { x: 300, payload: { label: '开场镜头' } }),
    node('tts', 'audio_gen', { x: 600, payload: { label: '旁白' } }),
    node('tool', 'tool', { y: 300, payload: { label: '剧本拆解' } }),
    node('todo', 'image_gen', { x: 300, y: 300, payload: { title: '还没生成', prompt: '城市天际线，黄昏' } }),
  ],
  edges: [{ id: 'e1', source: 'img', target: 'vid', kind: 'reference', payload: { role: 'first_frame' } }],
  outputs: {
    img: { medium: 'image', url: '/media/a.png', filename: 'a.png' },
    vid: { medium: 'video', url: 'https://cdn.example/v.mp4', filename: 'v.mp4' },
    tts: { medium: 'audio', url: '/media/t.mp3' },
    tool: { medium: 'text', url: '', text: '第一场：雨夜' },
  },
  expires_at: '2026-11-17T00:00:00Z',
};

class FakePointerEvent extends MouseEvent {
  pointerId: number;
  pointerType: string;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
    this.pointerType = init.pointerType ?? 'mouse';
  }
}

function respond(status: number, body: unknown = {}) {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: status < 400, status, json: async () => body } as Response);
}

function worldTransform() {
  return (document.querySelector('.cn-world') as HTMLElement).style.transform;
}

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
}

describe('SharedCanvasPage', () => {
  beforeEach(() => {
    vi.stubGlobal('PointerEvent', FakePointerEvent);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(0), 0) as unknown as number);
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('reads the public share without cookies and draws its nodes and outputs', async () => {
    respond(200, CANVAS);
    render(<SharedCanvasPage token={TOKEN} />);
    expect(screen.getByRole('status').textContent).toContain('正在加载');
    expect(await screen.findByRole('heading', { name: '第一集分镜' })).toBeTruthy();
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toMatch(new RegExp(`/api/public/canvas-shares/${TOKEN}$`));
    expect(init?.credentials).toBe('omit');

    expect(screen.getByText('只读')).toBeTruthy();
    expect(screen.getByText('由 Novara 分享')).toBeTruthy();
    expect(screen.getByText(/到期/)).toBeTruthy();

    const image = await screen.findByRole('img', { name: '女主定妆' }) as HTMLImageElement;
    expect(image.src).toMatch(/\/media\/a\.png$/);
    const video = document.querySelector('video') as HTMLVideoElement;
    expect(video.src).toBe('https://cdn.example/v.mp4');
    expect(video.controls).toBe(true);
    expect(video.getAttribute('preload')).toBe('metadata');
    expect((document.querySelector('audio') as HTMLAudioElement).src).toMatch(/\/media\/t\.mp3$/);
    expect(screen.getByText('第一场：雨夜')).toBeTruthy();
    // No output yet: what it was asked to make.
    expect(screen.getByText('城市天际线，黄昏')).toBeTruthy();
    expect(screen.getByText('还没生成')).toBeTruthy();
  });

  it('offers nothing to edit: no fields, ports, resize handles or node buttons', async () => {
    respond(200, CANVAS);
    render(<SharedCanvasPage token={TOKEN} />);
    await screen.findByRole('img', { name: '女主定妆' });
    const surface = screen.getByRole('application');
    expect(surface.querySelectorAll('input, textarea, select, button, [contenteditable="true"]')).toHaveLength(0);
    expect(surface.querySelectorAll('[data-port], [data-resize]')).toHaveLength(0);
    // The only buttons on the page are the zoom controls.
    const toolbar = screen.getByRole('toolbar', { name: '画布缩放' });
    for (const button of screen.getAllByRole('button')) expect(toolbar.contains(button)).toBe(true);
  });

  it('pans with a left-drag, on empty canvas or on a node, and never moves a node', async () => {
    respond(200, CANVAS);
    render(<SharedCanvasPage token={TOKEN} />);
    await screen.findByRole('img', { name: '女主定妆' });
    await settle();
    const surface = screen.getByRole('application');
    const frame = screen.getByTestId('node-img');
    const placed = frame.style.transform;
    const before = worldTransform();

    fireEvent.pointerDown(frame.querySelector('.cn-node__head')!, { clientX: 100, clientY: 100, button: 0, pointerId: 1 });
    fireEvent.pointerMove(surface, { clientX: 160, clientY: 130, button: 0, pointerId: 1 });
    fireEvent.pointerUp(surface, { clientX: 160, clientY: 130, button: 0, pointerId: 1 });
    await settle();
    expect(frame.style.transform).toBe(placed);
    expect(worldTransform()).not.toBe(before);
    expect(document.querySelector('.cn-marquee')).toBeNull();

    const panned = worldTransform();
    fireEvent.pointerDown(surface, { clientX: 400, clientY: 400, button: 0, pointerId: 2 });
    fireEvent.pointerMove(surface, { clientX: 380, clientY: 420, button: 0, pointerId: 2 });
    await settle();
    expect(document.querySelector('.cn-marquee')).toBeNull();
    fireEvent.pointerUp(surface, { clientX: 380, clientY: 420, button: 0, pointerId: 2 });
    expect(worldTransform()).not.toBe(panned);
  });

  it('zooms with the controls', async () => {
    respond(200, CANVAS);
    render(<SharedCanvasPage token={TOKEN} />);
    await screen.findByRole('img', { name: '女主定妆' });
    await settle();
    const before = worldTransform();
    fireEvent.click(screen.getByRole('button', { name: '放大' }));
    await waitFor(() => expect(worldTransform()).not.toBe(before));
  });

  it('says a link is gone on 404', async () => {
    respond(404, { detail: 'not found' });
    render(<SharedCanvasPage token={TOKEN} />);
    expect((await screen.findByRole('alert')).textContent).toContain('这个分享链接已失效或不存在');
    expect(screen.queryByRole('application')).toBeNull();
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull();
  });

  it('asks to wait on 429', async () => {
    respond(429);
    render(<SharedCanvasPage token={TOKEN} />);
    expect((await screen.findByRole('alert')).textContent).toContain('访问太频繁，请稍后再试');
  });

  it('says loading failed when the network is down, and retries', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
    render(<SharedCanvasPage token={TOKEN} />);
    expect((await screen.findByRole('alert')).textContent).toContain('加载失败');
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, status: 200, json: async () => CANVAS } as Response);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByRole('heading', { name: '第一集分镜' })).toBeTruthy();
  });

  it('loads the page on its own from the entry point', async () => {
    respond(200, CANVAS);
    render(<SharedCanvasEntry token={TOKEN} />);
    expect(await screen.findByRole('heading', { name: '第一集分镜' })).toBeTruthy();
  });
});
