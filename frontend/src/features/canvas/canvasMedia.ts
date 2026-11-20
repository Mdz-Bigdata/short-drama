// Ideas from AID Studio's workflow canvas (MIT, © 光子讯息(杭州)科技有限公司): a media card takes the shape of
// what it holds, and nothing on a card plays or takes a click while the canvas is being panned.
import { DEFAULT_SIZES } from './canvasGraph';
import type { CanvasNode } from './canvasTypes';

export interface MediaSize { width: number; height: number }

/** The picture area's longer side on a fitted card, in world pixels. */
export const MEDIA_LONG_SIDE = 320;
/** The shorter side never goes below this: a banner is letterboxed rather than squeezed flat. */
export const MEDIA_SHORT_SIDE_MIN = 140;
/** What a media card needs around its picture: padding across, and the title, file name and upload button down. */
export const MEDIA_CHROME: MediaSize = { width: 18, height: 95 };

/** The card size that shows a picture or clip of these pixel dimensions without bars. */
export function fittedSize(natural: MediaSize, chrome: MediaSize = MEDIA_CHROME): MediaSize | null {
  if (!(natural.width > 0) || !(natural.height > 0)) return null;
  const aspect = natural.width / natural.height;
  const width = aspect >= 1 ? MEDIA_LONG_SIDE : Math.max(MEDIA_SHORT_SIDE_MIN, MEDIA_LONG_SIDE * aspect);
  const height = aspect >= 1 ? Math.max(MEDIA_SHORT_SIDE_MIN, MEDIA_LONG_SIDE / aspect) : MEDIA_LONG_SIDE;
  return { width: Math.round(width + chrome.width), height: Math.round(height + chrome.height) };
}

/**
 * The size an upload gives its media card, or null to leave the card alone: only a media card
 * still at the size it was made with is fitted, never one somebody has resized.
 */
export function fitMediaNode(node: Pick<CanvasNode, 'kind' | 'width' | 'height'>, natural: MediaSize | null): MediaSize | null {
  if (!natural || node.kind !== 'media') return null;
  const [width, height] = DEFAULT_SIZES.media;
  if (node.width !== width || node.height !== height) return null;
  return fittedSize(natural);
}

/** A file's pixel dimensions, read locally; null for sound, for what cannot be decoded, or after `timeoutMs`. */
export function measureMedia(file: File, timeoutMs = 4000): Promise<MediaSize | null> {
  const image = file.type.startsWith('image/');
  if (!image && !file.type.startsWith('video/')) return Promise.resolve(null);
  if (typeof URL.createObjectURL !== 'function') return Promise.resolve(null);
  return new Promise(resolve => {
    const url = URL.createObjectURL(file);
    let settled = false;
    const finish = (size: MediaSize | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      resolve(size && size.width > 0 && size.height > 0 ? size : null);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);
    if (image) {
      const probe = new Image();
      probe.onload = () => finish({ width: probe.naturalWidth, height: probe.naturalHeight });
      probe.onerror = () => finish(null);
      probe.src = url;
    } else {
      const probe = document.createElement('video');
      probe.preload = 'metadata';
      probe.muted = true;
      probe.onloadedmetadata = () => finish({ width: probe.videoWidth, height: probe.videoHeight });
      probe.onerror = () => finish(null);
      probe.src = url;
    }
  });
}

/** Stop every clip and sound under `root` that is playing. Returns how many were stopped. */
export function pauseMedia(root: ParentNode | null): number {
  if (!root) return 0;
  let stopped = 0;
  root.querySelectorAll<HTMLMediaElement>('video, audio').forEach(media => {
    if (media.paused || media.ended) return;
    media.pause();
    stopped += 1;
  });
  return stopped;
}
