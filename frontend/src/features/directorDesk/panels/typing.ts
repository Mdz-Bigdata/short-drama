/** A key pressed here is text being typed or a list being walked, never a desk shortcut. */
export function typing(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

/** Space on a focused button, link or toggle presses it; it is not the desk's play key then. */
export function pressable(target: EventTarget | null) {
  return target instanceof HTMLElement
    && Boolean(target.closest('button, a[href], summary, [role="button"], [role="tab"], [role="checkbox"], [role="switch"], [role="radio"], [role="menuitem"], [role="option"], [role="slider"]'));
}
