import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ChevronDown, type LucideIcon } from 'lucide-react';

export interface StoryboardMenuItem {
  key: string;
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
  onSelect: () => void;
}

/** The toolbar's overflow: secondary tools stay one click away without squeezing the scene title. */
export function StoryboardMoreMenu({ label, items }: { label: string; items: StoryboardMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const entries = () => Array.from(rootRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') || []);

  useEffect(() => {
    if (!open) return;
    entries()[0]?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  // On the root, not the menu: with every entry disabled focus never leaves the trigger.
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (!open) return;
    if (event.key === 'Escape') {
      close();
      return;
    }
    if (event.key === 'Tab') {
      setOpen(false);
      return;
    }
    const list = entries();
    if (list.length === 0) return;
    const index = list.indexOf(document.activeElement as HTMLElement);
    const next = event.key === 'ArrowDown' ? list[(index + 1) % list.length]
      : event.key === 'ArrowUp' ? list[(Math.max(index, 0) - 1 + list.length) % list.length]
        : event.key === 'Home' ? list[0]
          : event.key === 'End' ? list[list.length - 1]
            : null;
    if (!next) return;
    event.preventDefault();
    next.focus();
  };

  return (
    <div ref={rootRef} className="storyboard-more" onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className="storyboard-action"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(value => !value)}
      >
        {label} <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} className="storyboard-more__menu" role="menu" aria-label={label}>
          {items.map(item => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                // Focus goes back to the trigger first: the item is about to unmount, and a dialog
                // opened from it returns focus to whatever had it.
                onClick={() => { close(); item.onSelect(); }}
              >
                <Icon aria-hidden="true" /> {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
