// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/components/canvas/canvas-context-menu.tsx.
import { ChevronRight } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';

import { t } from '../../i18n';
import { clampMenuPosition, isSubmenu, submenuPosition, type MenuItem } from './canvasMenus';
import './CanvasContextMenu.css';

export interface CanvasContextMenuProps {
  /** Where it was opened, in viewport (client) coordinates. */
  x: number;
  y: number;
  items: readonly MenuItem[];
  onClose: () => void;
  /** Accessible name of the menu. */
  label?: string;
}

type Anchor = { left: number; right: number; top: number };

function enabled(item: MenuItem): boolean {
  return item !== 'separator' && !item.disabled;
}

function step(items: readonly MenuItem[], from: number, direction: 1 | -1): number {
  const count = items.length;
  for (let offset = 1; offset <= count; offset += 1) {
    const index = (from + direction * offset + count * 2) % count;
    if (enabled(items[index])) return index;
  }
  return from;
}

interface MenuListProps {
  items: readonly MenuItem[];
  place: (width: number, height: number) => { x: number; y: number };
  closeAll: () => void;
  /** Close just this submenu and hand focus back to its item. */
  onBack?: () => void;
  label?: string;
  depth: number;
  /** Opened from the keyboard: focus its first item. Opened by hover: leave focus on the parent item. */
  takeFocus: boolean;
}

function MenuList({ items, place, closeAll, onBack, label, depth, takeFocus }: MenuListProps) {
  const root = useRef<HTMLDivElement>(null);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const engaged = useRef(takeFocus);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [active, setActive] = useState(() => (takeFocus ? step(items, -1, 1) : -1));
  const [open, setOpen] = useState<{ index: number; anchor: Anchor; focus: boolean } | null>(null);

  useLayoutEffect(() => {
    const box = root.current?.getBoundingClientRect();
    setPosition(place(box?.width ?? 0, box?.height ?? 0));
    // Placed once, when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!engaged.current || open?.focus) return;
    if (active >= 0) buttons.current[active]?.focus();
    else root.current?.focus();
  }, [active, open]);

  const openSubmenu = (index: number, focus: boolean) => {
    const box = buttons.current[index]?.getBoundingClientRect();
    engaged.current = true;
    setActive(index);
    setOpen({ index, anchor: { left: box?.left ?? 0, right: box?.right ?? 0, top: box?.top ?? 0 }, focus });
  };

  const activate = (index: number) => {
    const item = items[index];
    if (!item || item === 'separator' || item.disabled) return;
    if (isSubmenu(item)) {
      openSubmenu(index, true);
      return;
    }
    item.onSelect();
    closeAll();
  };

  const move = (next: (index: number) => number) => {
    engaged.current = true;
    setOpen(null);
    setActive(next);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    // A submenu sits inside its parent's element: its keys must not reach the parent too.
    event.stopPropagation();
    switch (event.key) {
      case 'ArrowDown': event.preventDefault(); move(index => step(items, index, 1)); break;
      case 'ArrowUp': event.preventDefault(); move(index => step(items, index < 0 ? items.length : index, -1)); break;
      case 'Home': event.preventDefault(); move(() => step(items, -1, 1)); break;
      case 'End': event.preventDefault(); move(() => step(items, items.length, -1)); break;
      case 'Enter': case ' ': event.preventDefault(); activate(active); break;
      case 'ArrowRight': {
        event.preventDefault();
        const item = items[active];
        if (item && item !== 'separator' && isSubmenu(item) && !item.disabled) openSubmenu(active, true);
        break;
      }
      case 'ArrowLeft': event.preventDefault(); onBack?.(); break;
      case 'Escape': event.preventDefault(); if (onBack) onBack(); else closeAll(); break;
      case 'Tab': event.preventDefault(); closeAll(); break;
      default: break;
    }
  };

  const submenu = open ? items[open.index] : null;
  return (
    <div
      ref={root}
      className={`ccm-menu${depth ? ' is-submenu' : ''}`}
      role="menu"
      aria-label={label}
      tabIndex={-1}
      style={{ left: position?.x ?? 0, top: position?.y ?? 0, visibility: position ? 'visible' : 'hidden' }}
      onKeyDown={onKeyDown}
      onContextMenu={event => event.preventDefault()}
    >
      {items.map((item, index) => {
        if (item === 'separator') return <div key={`sep-${index}`} className="ccm-separator" role="separator" />;
        const nested = isSubmenu(item);
        return (
          <button
            key={item.id ?? `${item.label}-${index}`}
            ref={element => { buttons.current[index] = element; }}
            type="button"
            role="menuitem"
            tabIndex={index === active ? 0 : -1}
            className={`ccm-item${!nested && item.danger ? ' is-danger' : ''}${index === active ? ' is-active' : ''}`}
            disabled={item.disabled}
            aria-haspopup={nested ? 'menu' : undefined}
            aria-expanded={nested ? open?.index === index : undefined}
            data-item={item.id}
            onPointerEnter={() => {
              if (item.disabled || (open?.index === index)) return;
              if (nested) openSubmenu(index, false);
              else move(() => index);
            }}
            onClick={() => activate(index)}
          >
            <span className="ccm-label">{item.label}</span>
            {!nested && item.shortcut && <kbd className="ccm-shortcut">{item.shortcut}</kbd>}
            {nested && <ChevronRight className="ccm-chevron" size={14} aria-hidden="true" />}
          </button>
        );
      })}
      {open && submenu && submenu !== 'separator' && isSubmenu(submenu) && (
        <MenuList
          key={`${open.index}-${open.focus}`}
          items={submenu.submenu}
          label={submenu.label}
          depth={depth + 1}
          takeFocus={open.focus}
          closeAll={closeAll}
          onBack={() => { setOpen(null); buttons.current[open.index]?.focus(); }}
          place={(width, height) => submenuPosition(open.anchor, width, height, window.innerWidth, window.innerHeight)}
        />
      )}
    </div>
  );
}

/**
 * A positioned menu: arrows, Home/End, Enter and Esc work, a press outside closes it, and it stays inside
 * the viewport. Items are actions, separators or submenus.
 */
export function CanvasContextMenu({ x, y, items, onClose, label }: CanvasContextMenuProps) {
  const host = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useLayoutEffect(() => { close.current = onClose; });

  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (host.current && event.target instanceof Node && host.current.contains(event.target)) return;
      close.current();
    };
    const blur = () => close.current();
    window.addEventListener('pointerdown', outside, true);
    window.addEventListener('blur', blur);
    window.addEventListener('resize', blur);
    return () => {
      window.removeEventListener('pointerdown', outside, true);
      window.removeEventListener('blur', blur);
      window.removeEventListener('resize', blur);
    };
  }, []);

  return (
    <div ref={host} className="ccm-host" onPointerDown={event => event.stopPropagation()}>
      <MenuList
        items={items}
        label={label ?? t('右键菜单')}
        depth={0}
        closeAll={() => close.current()}
        takeFocus
        place={(width, height) => clampMenuPosition(x, y, width, height, window.innerWidth, window.innerHeight)}
      />
    </div>
  );
}
