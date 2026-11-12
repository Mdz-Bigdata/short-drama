import { useEffect, useRef } from 'react';

// The overlays that are open, in the order they opened: the last one is on top.
const open: Array<{ current: () => void }> = [];

/**
 * Escape closes the overlay on top and nothing under it. The listener runs in the capture phase and stops
 * the event there, so the desk's own Escape (clear the selection, then leave the desk) never sees the key.
 */
export function useEscapeToClose(active: boolean, onClose: () => void) {
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  useEffect(() => {
    if (!active) return undefined;
    open.push(close);
    const onKey = (event: KeyboardEvent) => {
      // An overlay opened later (a dialog over the move settings) has its own listener, and the key is its.
      if (event.key !== 'Escape' || open[open.length - 1] !== close) return;
      // Escape that dismisses an input method's candidates is not about the overlay.
      if (event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      close.current();
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      open.splice(open.indexOf(close), 1);
    };
  }, [active]);
}
