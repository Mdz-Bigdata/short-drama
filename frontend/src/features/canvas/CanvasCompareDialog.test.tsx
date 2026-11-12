// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasCompareDialog } from './CanvasCompareDialog';
import type { Medium, NodeOutput, NodeRun } from './canvasTypes';

function run(id: string, medium: Medium, output: Partial<NodeOutput>, extra: Partial<NodeRun> = {}): NodeRun {
  return {
    id, node_id: 'n', batch_id: 'b', medium, status: 'done', model: `model-${id}`, request: {},
    output: { medium, url: `/media/${id}`, ...output } as NodeOutput, error: null, created_at: '2026-11-01T10:00:00Z', ...extra,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function open(a: NodeRun, b: NodeRun, activeId?: string) {
  const onRestore = vi.fn();
  const onClose = vi.fn();
  render(<CanvasCompareDialog a={a} b={b} activeId={activeId} onRestore={onRestore} onClose={onClose} />);
  return { onRestore, onClose, dialog: screen.getByRole('dialog', { name: '对比生成结果' }) };
}

describe('CanvasCompareDialog · images', () => {
  const a = run('a', 'image', {});
  const b = run('b', 'image', {});

  it('zooms both sides together with the wheel', () => {
    const { dialog } = open(a, b);
    expect(document.activeElement).toBe(dialog);
    const [left, right] = screen.getAllByRole('img') as HTMLImageElement[];
    fireEvent.wheel(left, { deltaY: -400 });
    expect(left.style.transform).not.toBe('scale(1)');
    expect(right.style.transform).toBe(left.style.transform);
    fireEvent.click(screen.getByRole('button', { name: /还原缩放/ }));
    expect(right.style.transform).toBe('scale(1)');
  });

  it('switches to the slider and moves its divider 5% per arrow', () => {
    open(a, b);
    fireEvent.click(screen.getByRole('button', { name: '滑块' }));
    const slider = screen.getByRole('slider', { name: '对比分界线' });
    expect(slider.getAttribute('aria-valuenow')).toBe('50');
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(slider.getAttribute('aria-valuenow')).toBe('60');
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(slider.getAttribute('aria-valuenow')).toBe('55');
    const over = screen.getByRole('img', { name: 'A 结果' }) as HTMLImageElement;
    expect(over.style.clipPath).toBe('inset(0 45% 0 0)');
    fireEvent.keyDown(slider, { key: 'End' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(slider.getAttribute('aria-valuenow')).toBe('100');
    fireEvent.keyDown(slider, { key: 'Home' });
    expect(slider.getAttribute('aria-valuenow')).toBe('0');
  });

  it('shows the size once an image loads, and restores the chosen side', () => {
    const { onRestore } = open(a, b, 'a');
    const right = screen.getByRole('img', { name: 'B 结果' });
    Object.defineProperty(right, 'naturalWidth', { value: 1280 });
    Object.defineProperty(right, 'naturalHeight', { value: 720 });
    fireEvent.load(right);
    const sideB = document.querySelector('.ccd-meta[data-side="B"]') as HTMLElement;
    expect(sideB.textContent).toContain('model-b');
    expect(sideB.textContent).toContain('1280×720');
    // A is what the node shows now.
    const sideA = document.querySelector('.ccd-meta[data-side="A"]') as HTMLElement;
    expect(within(sideA).queryByRole('button')).toBeNull();
    expect(sideA.textContent).toContain('当前');
    fireEvent.click(within(sideB).getByRole('button', { name: '用 B 这一版' }));
    expect(onRestore).toHaveBeenCalledWith('b');
  });

  it('closes on Esc, the close button and the backdrop', () => {
    const { dialog, onClose } = open(a, b);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    fireEvent.mouseDown(document.querySelector('.ccd-backdrop')!);
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

describe('CanvasCompareDialog · video', () => {
  const times = new WeakMap<HTMLMediaElement, number>();
  const durations = new WeakMap<HTMLMediaElement, number>();
  let play: ReturnType<typeof vi.fn>;
  let pause: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    play = vi.fn(() => Promise.resolve());
    pause = vi.fn();
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play as never);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pause as never);
    vi.spyOn(HTMLMediaElement.prototype, 'currentTime', 'get').mockImplementation(function (this: HTMLMediaElement) { return times.get(this) ?? 0; });
    vi.spyOn(HTMLMediaElement.prototype, 'currentTime', 'set').mockImplementation(function (this: HTMLMediaElement, value: number) { times.set(this, value); });
    vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockImplementation(function (this: HTMLMediaElement) { return durations.get(this) ?? NaN; });
  });

  function videos() {
    open(run('a', 'video', {}, { request: { requested_seconds: 5 } }), run('b', 'video', {}));
    const [one, two] = document.querySelectorAll('video');
    durations.set(one, 8);
    durations.set(two, 6);
    fireEvent.loadedMetadata(one);
    fireEvent.loadedMetadata(two);
    return [one, two] as const;
  }

  it('plays and pauses both with one button, muted until a side asks for sound', () => {
    const [one, two] = videos();
    expect(one.muted).toBe(true);
    expect(two.muted).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '同时播放' }));
    expect(play).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: '同时暂停' }));
    expect(pause).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'B 的声音' }));
    expect(two.muted).toBe(false);
    expect(one.muted).toBe(true);
    expect(document.querySelector('.ccd-meta[data-side="A"]')!.textContent).toContain('8 秒');
  });

  it('pulls the second clip back when it drifts more than 0.15s, and scrubs both', () => {
    const [one, two] = videos();
    one.currentTime = 3;
    two.currentTime = 2.9;
    fireEvent.timeUpdate(one);
    expect(two.currentTime).toBe(2.9);
    two.currentTime = 2.5;
    fireEvent.timeUpdate(one);
    expect(two.currentTime).toBe(3);
    // Past the end of the shorter clip it is left alone.
    one.currentTime = 7;
    fireEvent.timeUpdate(one);
    expect(two.currentTime).toBe(3);

    const scrub = screen.getByRole('slider', { name: '同步进度' }) as HTMLInputElement;
    expect(scrub.max).toBe('8');
    fireEvent.change(scrub, { target: { value: '7.5' } });
    expect(one.currentTime).toBe(7.5);
    expect(two.currentTime).toBe(6);
  });
});

describe('CanvasCompareDialog · audio, text and mixed', () => {
  it('plays both audio players together', () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
    open(run('a', 'audio', {}), run('b', 'audio', {}));
    expect(document.querySelectorAll('audio')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: '同时播放' }));
    expect(play).toHaveBeenCalledTimes(2);
  });

  it('marks the lines that differ', () => {
    const a = run('a', 'image', { medium: 'text', url: '', text: '第一行\n第二行\n第三行' });
    const b = run('b', 'image', { medium: 'text', url: '', text: '第一行\n改过的第二行\n第三行\n新增一行' });
    open(a, b);
    const left = screen.getByRole('list', { name: 'A 结果' });
    const right = screen.getByRole('list', { name: 'B 结果' });
    const changed = (list: HTMLElement) => [...list.querySelectorAll('li')].filter(li => li.classList.contains('is-changed')).map(li => li.textContent);
    expect(changed(left)).toEqual(['第二行']);
    expect(changed(right)).toEqual(['改过的第二行', '新增一行']);
    expect(screen.getByText('有 3 行不同')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '滑块' })).toBeNull();
  });

  it('shows different kinds side by side without the slider', () => {
    open(run('a', 'image', {}), run('b', 'video', {}));
    expect(screen.queryByRole('button', { name: '滑块' })).toBeNull();
    expect(screen.getByRole('img', { name: 'A 结果' })).toBeTruthy();
    expect(document.querySelectorAll('video')).toHaveLength(1);
  });
});
