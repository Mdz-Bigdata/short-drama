// A shot's blockout clip, rendered frame by frame through the lens and encoded in the browser.
//
// The export loop (probe the encoder first, render frame i at exactly i / fps, hand the encoder
// that timestamp, yield every few frames, cancel the output on any failure, give the renderer
// back in `finally`) is ported from
//   mangfufu/director-desk (MIT) src/export.ts
// What changed: the stage is a React Three Fiber scene rather than an imperative engine, so a
// frame is "shown" by asking the desk to sample the timeline at t and waiting for the lens scene
// to hold it (ClipStage.showFrame); frames go through a 2D canvas so character names can be
// burned in; MP4 falls back to WebM instead of failing; the result is always an in-memory blob.

import type { Camera, Scene, WebGLRenderer } from 'three';

import { CAPTURE_LIMITS } from '../directorDeskApi';
import type { LensFrameInfo } from '../deskTypes';
import { captureShowsLimbs, drawLabels, enterDeliveryRender } from './capture';
import { frameCount } from './sampling';

export const CLIP_SHORT_EDGE = 720;
const YIELD_EVERY = 3;

export type ClipFrameInfo = LensFrameInfo;

/** The small bridge between the lens canvas and this module. */
export interface ClipStage {
  gl: WebGLRenderer;
  scene: Scene;
  camera: Camera;
  /** Put the stage at `time` seconds; resolves once the lens scene holds exactly that instant. */
  showFrame: (time: number) => Promise<ClipFrameInfo>;
  /** Hand the stage back to the playhead. */
  release: () => void;
}

export interface ClipRequest {
  stage: ClipStage;
  aspect: number;
  durationS: number;
  fps: number;
  monochrome: boolean;
  labels: boolean;
  signal?: AbortSignal;
  onProgress?: (fraction: number) => void;
}

export interface ClipResult {
  blob: Blob;
  format: 'mp4' | 'webm';
  width: number;
  height: number;
  durationS: number;
  fps: number;
  frames: number;
  showsLimbs: boolean;
}

/** The browser cannot encode video at all (no WebCodecs, or no codec we can mux). Stills are unaffected. */
export class ClipUnsupportedError extends Error {
  constructor() {
    super('当前浏览器不支持 WebCodecs 视频编码，无法导出白模视频；静帧截图不受影响。请换用新版 Chrome、Edge 或 Safari。');
    this.name = 'ClipUnsupportedError';
  }
}

/** Short edge 720, both sides even: enough for a motion reference, small enough to upload. */
export function clipSize(aspect: number, shortEdge = CLIP_SHORT_EDGE): { width: number; height: number } {
  const ratio = aspect > 0 && Number.isFinite(aspect) ? aspect : 9 / 16;
  const even = (value: number) => Math.max(2, Math.round(value / 2) * 2);
  return ratio >= 1 ? { width: even(shortEdge * ratio), height: even(shortEdge) } : { width: even(shortEdge), height: even(shortEdge / ratio) };
}

function aborted(): DOMException {
  return new DOMException('已取消导出', 'AbortError');
}

export async function exportClip({ stage, aspect, durationS, fps, monochrome, labels, signal, onProgress }: ClipRequest): Promise<ClipResult> {
  if (!CAPTURE_LIMITS.clipFrameRates.includes(fps)) throw new Error('帧率只能是 24 / 25 / 30');
  if (!(durationS > 0) || durationS > CAPTURE_LIMITS.clipSeconds) throw new Error(`白模视频时长必须在 0 到 ${CAPTURE_LIMITS.clipSeconds} 秒之间`);
  const { width, height } = clipSize(aspect);
  if (signal?.aborted) throw aborted();

  // Everything that can say "no" is asked before the renderer is touched.
  if (typeof VideoEncoder === 'undefined') throw new ClipUnsupportedError();
  const media = await import('mediabunny');
  const quality = new media.Quality({ bitrate: Math.max(2_000_000, Math.round(width * height * fps * 0.13)) });
  let format: 'mp4' | 'webm' | null = null;
  for (const [candidate, codec] of [['mp4', 'avc'], ['webm', 'vp9']] as const) {
    if (await media.canEncodeVideo(codec, { width, height, quality, latencyMode: 'quality' })) { format = candidate; break; }
  }
  if (!format) throw new ClipUnsupportedError();
  if (signal?.aborted) throw aborted();

  const frame = document.createElement('canvas');
  frame.width = width;
  frame.height = height;
  const context = frame.getContext('2d');
  if (!context) throw new Error('浏览器无法创建画布，导出失败。');

  const { gl, scene, camera } = stage;
  const total = frameCount(durationS, fps);
  let showsLimbs = false;
  let output: InstanceType<typeof media.Output> | null = null;
  const delivery = enterDeliveryRender({ gl, scene, camera, width, height, monochrome });
  try {
    const target = new media.BufferTarget();
    output = new media.Output({ format: format === 'mp4' ? new media.Mp4OutputFormat({ fastStart: 'in-memory' }) : new media.WebMOutputFormat(), target });
    const source = new media.CanvasSource(frame, { codec: format === 'mp4' ? 'avc' : 'vp9', quality, latencyMode: 'quality', keyFrameInterval: 1 });
    output.addVideoTrack(source, { frameRate: fps });
    await output.start();

    for (let index = 0; index < total; index += 1) {
      if (signal?.aborted) throw aborted();
      const info = await stage.showFrame(index / fps);
      // A figure that loads or changes kind mid-export brings new helpers with it.
      delivery.hideHelpers();
      gl.render(scene, camera);
      context.drawImage(gl.domElement, 0, 0, width, height);
      if (labels && info.labels.length) drawLabels(context, info.labels, camera, width, height);
      showsLimbs = showsLimbs || captureShowsLimbs(info.figures, camera, width, height);
      await source.add(index / fps, 1 / fps);
      if (index % YIELD_EVERY === 0 || index === total - 1) {
        onProgress?.((index + 1) / total);
        await new Promise<void>(resolve => { setTimeout(resolve, 0); });
      }
    }
    source.close();
    if (signal?.aborted) throw aborted();
    await output.finalize();
    if (!target.buffer) throw new Error('视频编码没有产生数据，请重试。');
    const blob = new Blob([target.buffer], { type: format === 'mp4' ? 'video/mp4' : 'video/webm' });
    if (blob.size > CAPTURE_LIMITS.clipBytes) throw new Error(`导出的视频有 ${(blob.size / 1024 / 1024).toFixed(1)} MB，超过 60 MB 的上传上限；请缩短时长后重试。`);
    return { blob, format, width, height, durationS: total / fps, fps, frames: total, showsLimbs };
  } catch (error) {
    try {
      if (output && output.state !== 'finalized' && output.state !== 'canceled') await output.cancel();
    } catch { /* the first error is the one worth reporting */ }
    throw error;
  } finally {
    delivery.restore();
    stage.release();
  }
}
