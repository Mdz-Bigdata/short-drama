// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  bindVideoHoverPreview, cancelVideoPreview, videoPreviewActive, VIDEO_HOVER_DELAY_MS, VIDEO_PREVIEW_MS, VIDEO_PREVIEW_TIMEOUT_MS,
} from './canvasVideoPreview';

const enter = (element: Element, init: { pointerType?: string; buttons?: number } = {}) => {
  const event = new Event('pointerenter') as Event & { pointerType: string; buttons: number };
  Object.assign(event, { pointerType: init.pointerType ?? 'mouse', buttons: init.buttons ?? 0 });
  element.dispatchEvent(event);
};
const preview = (element: Element) => element.querySelector<HTMLVideoElement>('video[data-canvas-hover-preview]');

describe('video hover preview', () => {
  let surface: HTMLDivElement;
  let card: HTMLDivElement;
  let play: ReturnType<typeof vi.fn>;
  let unbind: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    play = vi.fn(() => Promise.resolve());
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play as never);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
    surface = document.createElement('div');
    surface.className = 'cn-surface';
    card = document.createElement('div');
    surface.appendChild(card);
    document.body.appendChild(surface);
    unbind = bindVideoHoverPreview(card, () => '/clip.mp4');
  });
  afterEach(() => {
    unbind();
    cancelVideoPreview();
    surface.remove();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('starts a muted clip only after the hover delay, and stops it after 3 seconds of playback', async () => {
    enter(card);
    expect(videoPreviewActive()).toBe(true);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS - 1);
    expect(preview(card)).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    const video = preview(card)!;
    expect(video).not.toBeNull();
    expect(video.muted).toBe(true);
    expect(video.getAttribute('src')).toBe('/clip.mp4');
    expect(play).toHaveBeenCalledTimes(1);
    video.dispatchEvent(new Event('playing'));
    await vi.advanceTimersByTimeAsync(VIDEO_PREVIEW_MS - 1);
    expect(preview(card)).not.toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(preview(card)).toBeNull();
    expect(videoPreviewActive()).toBe(false);
  });

  it('drops a stalled preview at the 8-second deadline', async () => {
    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).not.toBeNull();
    await vi.advanceTimersByTimeAsync(VIDEO_PREVIEW_TIMEOUT_MS - VIDEO_HOVER_DELAY_MS - 1);
    expect(preview(card)).not.toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(preview(card)).toBeNull();
  });

  it('stops when the clip reaches 3 seconds of time', async () => {
    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    const video = preview(card)!;
    Object.defineProperty(video, 'currentTime', { value: 3, configurable: true });
    video.dispatchEvent(new Event('timeupdate'));
    expect(preview(card)).toBeNull();
  });

  it.each([
    ['pointerdown', () => window.dispatchEvent(new Event('pointerdown'))],
    ['wheel', () => window.dispatchEvent(new Event('wheel'))],
    ['keydown', () => window.dispatchEvent(new Event('keydown'))],
    ['visibilitychange', () => document.dispatchEvent(new Event('visibilitychange'))],
    ['pointerleave', () => card.dispatchEvent(new Event('pointerleave'))],
    ['cancelVideoPreview', () => cancelVideoPreview()],
  ])('is cancelled by %s, before or after it starts', async (_name, interrupt) => {
    enter(card);
    interrupt();
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).toBeNull();
    expect(videoPreviewActive()).toBe(false);

    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).not.toBeNull();
    interrupt();
    expect(preview(card)).toBeNull();
  });

  it('is cancelled when the surface starts panning', async () => {
    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).not.toBeNull();
    surface.classList.add('is-panning');
    await vi.advanceTimersByTimeAsync(0);
    expect(preview(card)).toBeNull();
    enter(card);
    expect(videoPreviewActive()).toBe(false);
  });

  it('keeps a single preview across the canvas: hovering another card ends the first', async () => {
    const other = document.createElement('div');
    surface.appendChild(other);
    const unbindOther = bindVideoHoverPreview(other, () => Promise.resolve('/other.mp4'));
    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).not.toBeNull();
    enter(other);
    expect(preview(card)).toBeNull();
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(other)?.getAttribute('src')).toBe('/other.mp4');
    expect(document.querySelectorAll('video[data-canvas-hover-preview]')).toHaveLength(1);
    unbindOther();
    expect(preview(other)).toBeNull();
  });

  it('ignores touch, pressed buttons, and a source that resolves to nothing', async () => {
    enter(card, { pointerType: 'touch' });
    enter(card, { buttons: 1 });
    expect(videoPreviewActive()).toBe(false);
    unbind();
    unbind = bindVideoHoverPreview(card, () => Promise.resolve(''));
    enter(card);
    await vi.advanceTimersByTimeAsync(VIDEO_HOVER_DELAY_MS);
    expect(preview(card)).toBeNull();
    expect(videoPreviewActive()).toBe(false);
  });
});
