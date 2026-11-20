// Idea from AID Studio's workflow canvas (MIT, © 光子讯息(杭州)科技有限公司): a picture on a card opens large on
// a click, a video opens in a player on a double click, and a card tied to the project opens its place there.
// Written for this canvas, where a drag captures the pointer on the surface and the click lands there.
import { useMemo, useRef, type MouseEvent, type PointerEvent } from 'react';

export type OpenTarget =
  | { kind: 'image'; nodeId: string; url: string }
  | { kind: 'video'; nodeId: string; url: string; player: HTMLVideoElement }
  | { kind: 'node'; nodeId: string };

/** A press that travels further than this is a drag, not a click. */
export const CLICK_SLOP_PX = 4;

const MEDIA = '.cn-media';
// Controls keep their own double click (select a word, step a number); a group header folds on it.
const OWN_DOUBLE_CLICK = 'input,textarea,select,button,a,audio,label,[data-no-drag],.cn-group';

function nodeIdOf(element: Element) {
  return element.closest<HTMLElement>('[data-node-id]')?.dataset.nodeId ?? null;
}

/** What a plain click on this element opens: a card's picture, and nothing else. */
export function clickTarget(element: Element | null): OpenTarget | null {
  const image = element?.closest<HTMLImageElement>(`img${MEDIA}`);
  if (!image) return null;
  const nodeId = nodeIdOf(image);
  const url = image.currentSrc || image.src;
  return nodeId && url ? { kind: 'image', nodeId, url } : null;
}

/** What a double click on this element opens: a card's video in a player, otherwise the card itself. */
export function doubleClickTarget(element: Element | null): OpenTarget | null {
  if (!element) return null;
  const nodeId = nodeIdOf(element);
  if (!nodeId) return null;
  const video = element.closest<HTMLVideoElement>(`video${MEDIA}`);
  if (video) {
    const url = video.currentSrc || video.src;
    return url ? { kind: 'video', nodeId, url, player: video } : null;
  }
  // The first click of the pair already opened the picture.
  if (element.closest(`img${MEDIA}`) || element.closest(OWN_DOUBLE_CLICK)) return null;
  return { kind: 'node', nodeId };
}

/** The element a mouse event is about: its target inside a card, or whatever lies under the pointer. */
function elementUnder(event: MouseEvent): Element | null {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest('[data-node-id]')) return target;
  return typeof document.elementFromPoint === 'function' ? document.elementFromPoint(event.clientX, event.clientY) : null;
}

interface Press { x: number; y: number; plain: boolean }

/**
 * Handlers for the element around the canvas surface. They only watch: selection, dragging and
 * panning stay with the surface, and a press that moved, carried a modifier or panned opens nothing.
 */
export function useOpenGestures(onOpen: (target: OpenTarget) => void) {
  const press = useRef<Press | null>(null);
  const open = useRef(onOpen);
  open.current = onOpen;
  return useMemo(() => {
    const steady = (event: MouseEvent) => {
      const down = press.current;
      if (!down?.plain) return false;
      return Math.hypot(event.clientX - down.x, event.clientY - down.y) <= CLICK_SLOP_PX;
    };
    return {
      onPointerDownCapture: (event: PointerEvent) => {
        const target = event.target instanceof Element ? event.target : null;
        press.current = {
          x: event.clientX, y: event.clientY,
          plain: event.button === 0 && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey && !target?.closest('.cn-surface.is-panning'),
        };
      },
      onClick: (event: MouseEvent) => {
        if (event.detail > 1 || !steady(event)) return;
        const target = clickTarget(elementUnder(event));
        if (target) open.current(target);
      },
      onDoubleClick: (event: MouseEvent) => {
        if (!steady(event)) return;
        const target = doubleClickTarget(elementUnder(event));
        if (!target) return;
        // A video would otherwise go full screen behind the player that opens.
        if (target.kind === 'video') event.preventDefault();
        open.current(target);
      },
    };
  }, []);
}
