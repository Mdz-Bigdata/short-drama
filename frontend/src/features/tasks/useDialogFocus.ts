import { useEffect, useRef, type RefObject } from 'react';


const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])', 'select:not([disabled])',
  'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * What a modal panel owes the keyboard: focus moves into it when it opens, Tab and Shift+Tab stay
 * inside it, Escape closes it, and focus goes back to whatever opened it once it is gone.
 */
export function useDialogFocus(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(() => {
    if (!active) return undefined;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Escape that dismisses an input method's candidates, or that a control inside already
        // handled, must not close the dialog and throw away what was typed.
        if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return;
        closeRef.current();
        return;
      }
      const panel = ref.current;
      if (event.key !== 'Tab' || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      const outside = !panel.contains(current);
      if (event.shiftKey && (current === first || outside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || outside)) {
        event.preventDefault();
        first.focus();
      }
    };
    // On window, so a key pressed with nothing focused still reaches it.
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, [active, ref]);
}
