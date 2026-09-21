// @vitest-environment jsdom
import { Mesh, PerspectiveCamera, Scene, Vector2, type WebGLRenderer } from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HELPER_FLAG } from './capture';
import { ClipUnsupportedError, clipSize, exportClip, type ClipStage } from './clipExport';

// The encoder is the boundary: what matters here is what it is asked to do, frame by frame.
const media = vi.hoisted(() => ({
  canEncode: vi.fn(),
  added: [] as Array<[number, number]>,
  outputs: [] as Array<{ state: string; format: { kind: string; options?: unknown }; cancel: ReturnType<typeof vi.fn>; finalize: ReturnType<typeof vi.fn> }>,
  sources: [] as Array<{ config: Record<string, unknown>; canvas: HTMLCanvasElement; closed: boolean }>,
}));

vi.mock('mediabunny', () => {
  class BufferTarget { buffer: ArrayBuffer | null = null; }
  class Output {
    state = 'pending';
    format: { kind: string };
    target: BufferTarget;
    cancel = vi.fn(async () => { this.state = 'canceled'; });
    finalize = vi.fn(async () => { this.state = 'finalized'; this.target.buffer = new ArrayBuffer(64); });
    constructor(options: { format: { kind: string }; target: BufferTarget }) {
      this.format = options.format;
      this.target = options.target;
      media.outputs.push(this);
    }
    addVideoTrack = vi.fn();
    start = vi.fn(async () => { this.state = 'started'; });
  }
  class CanvasSource {
    closed = false;
    canvas: HTMLCanvasElement;
    config: Record<string, unknown>;
    constructor(canvas: HTMLCanvasElement, config: Record<string, unknown>) {
      this.canvas = canvas;
      this.config = config;
      media.sources.push(this);
    }
    add = vi.fn(async (timestamp: number, duration: number) => { media.added.push([timestamp, duration]); });
    close() { this.closed = true; }
  }
  return {
    BufferTarget, Output, CanvasSource, canEncodeVideo: media.canEncode,
    Quality: class {},
    Mp4OutputFormat: class { kind = 'mp4'; },
    WebMOutputFormat: class { kind = 'webm'; },
  };
});

function fakeStage() {
  const size = new Vector2(300, 533);
  let ratio = 1.5;
  const gl = {
    domElement: document.createElement('canvas'),
    getPixelRatio: () => ratio, setPixelRatio: vi.fn((next: number) => { ratio = next; }),
    getSize: (target: Vector2) => target.copy(size), setSize: vi.fn((width: number, height: number) => { size.set(width, height); }),
    render: vi.fn(),
  };
  const scene = new Scene();
  const helper = new Mesh();
  helper.userData[HELPER_FLAG] = true;
  scene.add(helper, new Mesh());
  const camera = new PerspectiveCamera(40, 300 / 533, 0.1, 100);
  const shown: number[] = [];
  const stage: ClipStage = {
    gl: gl as unknown as WebGLRenderer, scene, camera,
    showFrame: vi.fn(async (time: number) => { shown.push(time); return { labels: [{ text: '林夏', position: [0, 0.5, -3] as [number, number, number] }], figures: [] }; }),
    release: vi.fn(),
  };
  return { stage, gl, scene, helper, camera, shown, size, ratio: () => ratio };
}

describe('clipSize', () => {
  it('puts 720 on the short edge with even sides', () => {
    expect(clipSize(9 / 16)).toEqual({ width: 720, height: 1280 });
    expect(clipSize(16 / 9)).toEqual({ width: 1280, height: 720 });
    expect(clipSize(1)).toEqual({ width: 720, height: 720 });
    expect(clipSize(2.39)).toEqual({ width: 1720, height: 720 });   // 1720.8 → 1720
    expect(clipSize(Number.NaN)).toEqual({ width: 720, height: 1280 });
  });
});

describe('exportClip', () => {
  const context = { drawImage: vi.fn(), strokeText: vi.fn(), fillText: vi.fn() };

  beforeEach(() => {
    media.canEncode.mockReset().mockResolvedValue(true);
    media.added.length = 0;
    media.outputs.length = 0;
    media.sources.length = 0;
    [context.drawImage, context.strokeText, context.fillText].forEach(mock => mock.mockClear());
    vi.stubGlobal('VideoEncoder', class {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders ceil(duration · fps) frames, each at exactly i / fps, then puts the renderer back', async () => {
    const { stage, gl, helper, camera, shown, size, ratio } = fakeStage();
    const progress: number[] = [];
    const clip = await exportClip({ stage, aspect: 9 / 16, durationS: 3.5, fps: 25, monochrome: true, labels: true, onProgress: value => progress.push(value) });

    expect(clip).toMatchObject({ format: 'mp4', width: 720, height: 1280, fps: 25, frames: 88, showsLimbs: false });
    expect(clip.durationS).toBeCloseTo(88 / 25);
    expect(clip.blob.type).toBe('video/mp4');
    expect(shown).toHaveLength(88);
    expect(shown[87]).toBeCloseTo(87 / 25);
    expect(media.added).toHaveLength(88);
    expect(media.added[10]).toEqual([10 / 25, 1 / 25]);
    // One render per frame at delivery size, plus the one that repaints the viewport afterwards.
    expect(gl.render).toHaveBeenCalledTimes(89);
    expect(gl.setSize).toHaveBeenNthCalledWith(1, 720, 1280, false);
    expect(context.drawImage).toHaveBeenCalledTimes(88);
    expect(context.fillText).toHaveBeenCalledWith('林夏', expect.any(Number), expect.any(Number));
    expect(media.sources[0].config).toMatchObject({ codec: 'avc', keyFrameInterval: 1 });
    expect(media.sources[0].closed).toBe(true);
    expect(media.outputs[0].finalize).toHaveBeenCalled();
    expect(progress[progress.length - 1]).toBe(1);

    expect([size.x, size.y, ratio()]).toEqual([300, 533, 1.5]);
    expect(camera.aspect).toBeCloseTo(300 / 533);
    expect(helper.visible).toBe(true);
    expect(stage.scene.overrideMaterial).toBeNull();
    expect(stage.release).toHaveBeenCalledTimes(1);
  });

  it('hides helpers and paints everything one grey while it films', async () => {
    const { stage, helper, scene } = fakeStage();
    const seen: Array<[boolean, boolean]> = [];
    (stage.gl.render as ReturnType<typeof vi.fn>).mockImplementation(() => { seen.push([helper.visible, scene.overrideMaterial !== null]); });
    await exportClip({ stage, aspect: 1, durationS: 1, fps: 24, monochrome: true, labels: false });
    expect(seen.slice(0, 24).every(([visible, clay]) => !visible && clay)).toBe(true);
    expect(seen[24]).toEqual([true, false]);
    expect(context.fillText).not.toHaveBeenCalled();
  });

  it('falls back to WebM when the browser cannot encode H.264', async () => {
    media.canEncode.mockImplementation(async (codec: string) => codec === 'vp9');
    const { stage } = fakeStage();
    const clip = await exportClip({ stage, aspect: 16 / 9, durationS: 1, fps: 24, monochrome: false, labels: false });
    expect(clip.format).toBe('webm');
    expect(clip.blob.type).toBe('video/webm');
    expect(media.sources[0].config.codec).toBe('vp9');
  });

  it('cancels mid-way: the output is cancelled and the renderer restored', async () => {
    const { stage, gl, size, helper } = fakeStage();
    const controller = new AbortController();
    (stage.showFrame as ReturnType<typeof vi.fn>).mockImplementation(async (time: number) => {
      if (time >= 10 / 24) controller.abort();
      return { labels: [], figures: [] };
    });
    await expect(exportClip({ stage, aspect: 9 / 16, durationS: 4, fps: 24, monochrome: true, labels: false, signal: controller.signal }))
      .rejects.toMatchObject({ name: 'AbortError' });
    expect(media.added.length).toBeLessThan(15);
    expect(media.outputs[0].cancel).toHaveBeenCalled();
    expect(media.outputs[0].finalize).not.toHaveBeenCalled();
    expect([size.x, size.y]).toEqual([300, 533]);
    expect(helper.visible).toBe(true);
    expect(stage.scene.overrideMaterial).toBeNull();
    expect(stage.release).toHaveBeenCalledTimes(1);
    expect(gl.setSize).toHaveBeenLastCalledWith(300, 533, false);
  });

  it('restores the renderer when a frame never shows up', async () => {
    const { stage, size } = fakeStage();
    (stage.showFrame as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('机位画面没有响应'));
    await expect(exportClip({ stage, aspect: 9 / 16, durationS: 2, fps: 24, monochrome: false, labels: false })).rejects.toThrow('机位画面没有响应');
    expect([size.x, size.y]).toEqual([300, 533]);
    expect(media.outputs[0].cancel).toHaveBeenCalled();
  });

  it('says so, and touches nothing, when WebCodecs is missing or no codec can be encoded', async () => {
    const { stage, gl } = fakeStage();
    vi.stubGlobal('VideoEncoder', undefined);
    await expect(exportClip({ stage, aspect: 9 / 16, durationS: 2, fps: 24, monochrome: false, labels: false })).rejects.toBeInstanceOf(ClipUnsupportedError);
    vi.stubGlobal('VideoEncoder', class {});
    media.canEncode.mockResolvedValue(false);
    await expect(exportClip({ stage, aspect: 9 / 16, durationS: 2, fps: 24, monochrome: false, labels: false })).rejects.toThrow('静帧截图不受影响');
    expect(gl.setSize).not.toHaveBeenCalled();
    expect(gl.render).not.toHaveBeenCalled();
    expect(stage.showFrame).not.toHaveBeenCalled();
    expect(media.outputs).toHaveLength(0);
  });

  it('refuses what the server would refuse', async () => {
    const { stage } = fakeStage();
    await expect(exportClip({ stage, aspect: 1, durationS: 31, fps: 24, monochrome: false, labels: false })).rejects.toThrow('30 秒');
    await expect(exportClip({ stage, aspect: 1, durationS: 5, fps: 60, monochrome: false, labels: false })).rejects.toThrow('24 / 25 / 30');
  });
});
