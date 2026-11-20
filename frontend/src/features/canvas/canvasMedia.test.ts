// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SIZES } from './canvasGraph';
import { fitMediaNode, fittedSize, MEDIA_CHROME, MEDIA_LONG_SIDE, MEDIA_SHORT_SIDE_MIN, measureMedia, pauseMedia } from './canvasMedia';

const [defaultWidth, defaultHeight] = DEFAULT_SIZES.media;

describe('a media card takes the shape of what it holds', () => {
  it('gives a wide picture its long side across and a tall one its long side down', () => {
    expect(fittedSize({ width: 1920, height: 1080 })).toEqual({ width: MEDIA_LONG_SIDE + MEDIA_CHROME.width, height: 180 + MEDIA_CHROME.height });
    expect(fittedSize({ width: 1080, height: 1920 })).toEqual({ width: 180 + MEDIA_CHROME.width, height: MEDIA_LONG_SIDE + MEDIA_CHROME.height });
    expect(fittedSize({ width: 800, height: 800 })).toEqual({ width: MEDIA_LONG_SIDE + MEDIA_CHROME.width, height: MEDIA_LONG_SIDE + MEDIA_CHROME.height });
  });

  it('does not squeeze a banner flat', () => {
    expect(fittedSize({ width: 4000, height: 400 })?.height).toBe(MEDIA_SHORT_SIDE_MIN + MEDIA_CHROME.height);
    expect(fittedSize({ width: 300, height: 3000 })?.width).toBe(MEDIA_SHORT_SIDE_MIN + MEDIA_CHROME.width);
  });

  it('has no size for dimensions that are not', () => {
    expect(fittedSize({ width: 0, height: 100 })).toBeNull();
    expect(fittedSize({ width: Number.NaN, height: 100 })).toBeNull();
  });

  it('fits only a media card nobody has resized', () => {
    const natural = { width: 1600, height: 900 };
    expect(fitMediaNode({ kind: 'media', width: defaultWidth, height: defaultHeight }, natural)).toEqual(fittedSize(natural));
    expect(fitMediaNode({ kind: 'media', width: defaultWidth + 40, height: defaultHeight }, natural)).toBeNull();
    expect(fitMediaNode({ kind: 'style_ref', width: defaultWidth, height: defaultHeight }, natural)).toBeNull();
    expect(fitMediaNode({ kind: 'media', width: defaultWidth, height: defaultHeight }, null)).toBeNull();
  });
});

describe('measuring a file', () => {
  it('has nothing to measure in a sound', async () => {
    await expect(measureMedia(new File(['x'], 'a.mp3', { type: 'audio/mpeg' }))).resolves.toBeNull();
  });

  it('gives up after the time allowed when the file never decodes', async () => {
    const create = vi.fn(() => 'blob:probe');
    const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    vi.useFakeTimers();
    try {
      const pending = measureMedia(new File(['x'], 'a.png', { type: 'image/png' }), 500);
      await vi.advanceTimersByTimeAsync(500);
      await expect(pending).resolves.toBeNull();
      expect(revoke).toHaveBeenCalledWith('blob:probe');
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });
});

describe('pausing what plays', () => {
  it('stops the players that are running and leaves the others', () => {
    const root = document.createElement('div');
    const playing = document.createElement('video');
    const idle = document.createElement('audio');
    Object.defineProperty(playing, 'paused', { value: false });
    Object.defineProperty(idle, 'paused', { value: true });
    playing.pause = vi.fn();
    idle.pause = vi.fn();
    root.append(playing, idle);
    expect(pauseMedia(root)).toBe(1);
    expect(playing.pause).toHaveBeenCalledTimes(1);
    expect(idle.pause).not.toHaveBeenCalled();
    expect(pauseMedia(null)).toBe(0);
  });
});
