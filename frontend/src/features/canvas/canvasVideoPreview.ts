// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-video-hover-preview.ts.

/** Hover this long before a preview starts. */
export const VIDEO_HOVER_DELAY_MS = 350;
/** A preview plays this long at most. */
export const VIDEO_PREVIEW_MS = 3000;
/** A preview that has not finished this long after the hover began (a stalled load) is dropped. */
export const VIDEO_PREVIEW_TIMEOUT_MS = 8000;

/** The canvas surface sets this class while it is panned; a preview stops when it appears. */
const PANNING_CLASS = 'is-panning';
const SURFACE_SELECTOR = '.cn-surface';

export interface VideoPreviewOptions {
  /** Where the preview video is appended; the hovered element by default. */
  host?: () => HTMLElement | null;
}

type Source = string | null | undefined;

// Only one preview exists at a time across the whole canvas: one decoder, one network stream.
let stopCurrent: (() => void) | null = null;

/** Stop whatever preview is pending or playing (call it when the viewport moves). */
export function cancelVideoPreview() {
  stopCurrent?.();
}

/** Whether a preview is pending or playing. */
export function videoPreviewActive() {
  return stopCurrent !== null;
}

function reducedMotion() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function mediaPlaying(except?: HTMLMediaElement) {
  return Array.from(document.querySelectorAll<HTMLMediaElement>('video, audio')).some(media => media !== except && !media.paused && !media.ended);
}

/**
 * Play a muted few seconds of a video node's clip while a mouse rests on it. Any viewport
 * interaction (pointer down, wheel, a key, panning, the tab going hidden) ends it, and so does
 * the person starting a player of their own. Returns the unbind function.
 */
export function bindVideoHoverPreview(element: HTMLElement, resolveSource: () => Source | Promise<Source>, options: VideoPreviewOptions = {}) {
  let stopOwn: (() => void) | null = null;

  const enter = (event: PointerEvent) => {
    if ((event.pointerType && event.pointerType !== 'mouse') || event.buttons || document.hidden || reducedMotion()) return;
    const surface = element.closest(SURFACE_SELECTOR);
    if (surface?.classList.contains(PANNING_CLASS)) return;
    stopCurrent?.();

    let disposed = false;
    let video: HTMLVideoElement | null = null;
    let playback: ReturnType<typeof setTimeout> | undefined;
    const listeners = new AbortController();
    const observer = typeof MutationObserver === 'function' && surface
      ? new MutationObserver(() => { if (surface.classList.contains(PANNING_CLASS)) cancel(); })
      : null;

    const cancel = () => {
      if (disposed) return;
      disposed = true;
      clearTimeout(delay);
      clearTimeout(deadline);
      clearTimeout(playback);
      listeners.abort();
      observer?.disconnect();
      if (video) {
        video.pause();
        video.removeAttribute('src');
        video.load();
        video.remove();
        video = null;
      }
      if (stopCurrent === cancel) stopCurrent = null;
      if (stopOwn === cancel) stopOwn = null;
    };

    const start = (src: Source) => {
      if (disposed) return;
      const host = options.host?.() ?? element;
      if (!src || !element.isConnected || !host.isConnected || document.hidden) {
        cancel();
        return;
      }
      const clip = document.createElement('video');
      video = clip;
      clip.muted = true;
      clip.defaultMuted = true;
      clip.playsInline = true;
      clip.preload = 'metadata';
      clip.setAttribute('aria-hidden', 'true');
      clip.dataset.canvasHoverPreview = 'true';
      Object.assign(clip.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%', objectFit: 'contain', background: '#000', pointerEvents: 'none', borderRadius: 'inherit',
      });
      const signal = listeners.signal;
      clip.addEventListener('ended', cancel, { signal });
      clip.addEventListener('error', cancel, { signal });
      clip.addEventListener('timeupdate', () => { if (clip.currentTime >= VIDEO_PREVIEW_MS / 1000) cancel(); }, { signal });
      clip.addEventListener('playing', () => { if (!playback) playback = setTimeout(cancel, VIDEO_PREVIEW_MS); }, { signal });
      clip.src = src;
      host.appendChild(clip);
      try {
        const played = clip.play() as Promise<void> | undefined;
        if (played && typeof played.catch === 'function') played.catch(cancel);
      } catch {
        cancel();
      }
    };

    const delay = setTimeout(() => {
      // A player the person started wins over an incidental hover.
      if (mediaPlaying()) {
        cancel();
        return;
      }
      let source: Source | Promise<Source>;
      try {
        source = resolveSource();
      } catch {
        cancel();
        return;
      }
      if (source && typeof (source as Promise<Source>).then === 'function') (source as Promise<Source>).then(start, cancel);
      else start(source as Source);
    }, VIDEO_HOVER_DELAY_MS);
    const deadline = setTimeout(cancel, VIDEO_PREVIEW_TIMEOUT_MS);

    stopOwn = cancel;
    stopCurrent = cancel;
    if (observer && surface) observer.observe(surface, { attributes: true, attributeFilter: ['class'] });
    for (const type of ['pointerdown', 'wheel', 'keydown', 'blur'] as const) {
      window.addEventListener(type, cancel, { capture: true, passive: true, signal: listeners.signal });
    }
    document.addEventListener('visibilitychange', cancel, { signal: listeners.signal });
    document.addEventListener('play', event => { if (event.target !== video) cancel(); }, { capture: true, signal: listeners.signal });
  };

  const leave = () => stopOwn?.();
  element.addEventListener('pointerenter', enter);
  element.addEventListener('pointerleave', leave);
  element.addEventListener('pointercancel', leave);
  return () => {
    leave();
    element.removeEventListener('pointerenter', enter);
    element.removeEventListener('pointerleave', leave);
    element.removeEventListener('pointercancel', leave);
  };
}
