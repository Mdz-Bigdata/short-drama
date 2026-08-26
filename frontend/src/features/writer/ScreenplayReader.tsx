import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';

import { MarkdownBlocks } from './MarkdownDocument';
import { paginateMarkdown } from './markdownParser';

function paginationItems(total: number, current: number): Array<number | 'ellipsis-left' | 'ellipsis-right'> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index);
  const items: Array<number | 'ellipsis-left' | 'ellipsis-right'> = [0];
  if (current > 3) items.push('ellipsis-left');
  const start = Math.max(1, Math.min(current - 1, total - 4));
  const end = Math.min(total - 2, Math.max(current + 1, 3));
  for (let index = start; index <= end; index += 1) items.push(index);
  if (current < total - 4) items.push('ellipsis-right');
  items.push(total - 1);
  return items;
}

export function ScreenplayReader({
  title,
  script,
  onClose,
}: {
  title: string;
  script: string;
  onClose: () => void;
}) {
  const pages = useMemo(() => paginateMarkdown(script), [script]);
  const [pageSelection, setPageSelection] = useState({ script, index: 0 });
  const pageIndex = pageSelection.script === script ? pageSelection.index : 0;
  const activePageIndex = Math.min(pageIndex, pages.length - 1);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const pageRef = useRef<HTMLElement>(null);

  const goToPage = (nextPage: number) => {
    setPageSelection({ script, index: Math.max(0, Math.min(pages.length - 1, nextPage)) });
  };

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    pageRef.current?.scrollTo?.({ top: 0 });
  }, [activePageIndex]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault();
      goToPage(activePageIndex - 1);
      return;
    }
    if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      event.preventDefault();
      goToPage(activePageIndex + 1);
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
    ) || []);
    if (!focusable.length) return;
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

  return (
    <div
      className="writer-reader-backdrop"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        className="writer-reader"
        role="dialog"
        aria-modal="true"
        aria-labelledby="writer-reader-title"
      >
        <header className="writer-reader__header">
          <div>
            <span>FULL SCREENPLAY / PAGED READER</span>
            <h2 id="writer-reader-title">{title} · 完整剧本</h2>
          </div>
          <button ref={closeRef} type="button" aria-label="关闭剧本阅读器" onClick={onClose}><X aria-hidden="true" /></button>
        </header>

        <section
          ref={pageRef}
          className="writer-reader__page"
          aria-label={`剧本第 ${activePageIndex + 1} 页`}
          tabIndex={0}
        >
          <div className="writer-reader__paper">
            <MarkdownBlocks blocks={pages[activePageIndex] || []} />
          </div>
        </section>

        <footer className="writer-reader__footer">
          <button type="button" onClick={() => goToPage(activePageIndex - 1)} disabled={activePageIndex === 0} aria-label="上一页">
            <ChevronLeft aria-hidden="true" /> 上一页
          </button>
          <nav className="writer-reader__pagination" aria-label="剧本页码">
            {paginationItems(pages.length, activePageIndex).map(item => typeof item === 'number' ? (
              <button
                type="button"
                key={item}
                aria-label={`第 ${item + 1} 页`}
                aria-current={item === activePageIndex ? 'page' : undefined}
                onClick={() => goToPage(item)}
              >
                {item + 1}
              </button>
            ) : <span key={item} aria-hidden="true">…</span>)}
          </nav>
          <span className="writer-reader__counter" role="status" aria-live="polite">第 {activePageIndex + 1} / {pages.length} 页</span>
          <button type="button" onClick={() => goToPage(activePageIndex + 1)} disabled={activePageIndex === pages.length - 1} aria-label="下一页">
            下一页 <ChevronRight aria-hidden="true" />
          </button>
        </footer>
      </div>
    </div>
  );
}
