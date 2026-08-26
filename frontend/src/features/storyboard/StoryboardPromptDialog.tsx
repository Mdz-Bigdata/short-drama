import { useEffect, useMemo, useRef } from 'react';
import { Download, X } from 'lucide-react';

import { PromptFoundationSections } from './PromptFoundationSections';
import { PromptTimelineSections } from './PromptTimelineSections';
import { storyboardPromptMarkdown } from './storyboardPromptMarkdown';
import { STORYBOARD_VISUAL_THEME } from './storyboardTheme';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';
import './StoryboardPromptDialog.css';


export function StoryboardPromptDialog({ detail, fallbackPrompt, onClose }: {
  detail?: StoryboardPromptDetail;
  fallbackPrompt?: string;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const markdown = useMemo(() => detail ? storyboardPromptMarkdown(detail) : (fallbackPrompt || '暂无提示词'), [detail, fallbackPrompt]);
  const downloadHref = `data:text/markdown;charset=utf-8,${encodeURIComponent(markdown)}`;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ) || []);
      if (focusable.length === 0) return;
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
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="prompt-dialog__backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div
        ref={dialogRef}
        className="prompt-dialog"
        data-visual-theme={STORYBOARD_VISUAL_THEME.id}
        role="dialog"
        aria-modal="true"
        aria-labelledby="prompt-dialog-title"
      >
        <header className="prompt-dialog__header">
          <h1 id="prompt-dialog-title">宫格提示词 · 第 1 页</h1>
          <div>
            <a href={downloadHref} download={`${detail?.shot_number || 'storyboard'}-page-1.md`}>
              <Download aria-hidden="true" /> 下载 Markdown
            </a>
            <button ref={closeRef} type="button" onClick={onClose} aria-label="关闭宫格提示词">
              <X aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className="prompt-dialog__body">
          {detail ? (
            <>
              <PromptFoundationSections detail={detail} />
              <PromptTimelineSections detail={detail} />
            </>
          ) : (
            <section className="prompt-detail__section">
              <header className="prompt-detail__section-header"><h2>原始宫格提示词</h2></header>
              <div className="prompt-detail__section-body"><pre className="prompt-dialog__fallback">{markdown}</pre></div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
