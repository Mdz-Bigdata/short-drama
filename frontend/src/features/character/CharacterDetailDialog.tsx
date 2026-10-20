import { X } from 'lucide-react';
import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function CharacterDetailDialog({
  title,
  children,
  onClose,
  className = '',
  closeLabel = '关闭详情',
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  closeLabel?: string;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const closeHandlerRef = useRef(onClose);

  useEffect(() => {
    closeHandlerRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    closeRef.current?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
      const returnTarget = returnFocusRef.current;
      if (returnTarget?.isConnected) returnTarget.focus();
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeHandlerRef.current();
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) || [])];
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className="character-dialog-backdrop"
      onClick={event => {
        if (event.target === event.currentTarget) closeHandlerRef.current();
      }}
    >
      <section
        ref={dialogRef}
        className={`character-dialog ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="character-dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button ref={closeRef} type="button" onClick={() => closeHandlerRef.current()} aria-label={closeLabel}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <div className="character-dialog__body">{children}</div>
      </section>
    </div>,
    document.body,
  );
}
