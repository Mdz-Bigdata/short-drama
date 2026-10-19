import { useEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Download, X } from 'lucide-react';

import { PromptFoundationSections } from './PromptFoundationSections';
import { PromptTimelineSections } from './PromptTimelineSections';
import { storyboardPromptMarkdown } from './storyboardPromptMarkdown';
import { STORYBOARD_VISUAL_THEME } from './storyboardTheme';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';
import './StoryboardPromptDialog.css';
import { t } from '../../i18n';


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
        'a[href], button:not(:disabled), summary, [tabindex]:not([tabindex="-1"])',
      ) || []).filter(element => {
        if (element.closest('[hidden]')) return false;
        // Controls in closed details cannot receive focus, except their own summary.
        const closedDetails = element.closest('details:not([open])');
        return !closedDetails || closedDetails.querySelector(':scope > summary') === element;
      });
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

  return createPortal(
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
          <div className="prompt-dialog__title">
            <span>{t('STORYBOARD / 镜头创作')}</span>
            <h1 id="prompt-dialog-title">{detail?.shot_number ? `${detail.shot_number} · 宫格提示词` : '宫格提示词'}</h1>
          </div>
          <div className="prompt-dialog__actions">
            <a href={downloadHref} download={`${detail?.shot_number || 'storyboard'}-page-1.md`}>
              <Download aria-hidden="true" /><span>{t('下载 Markdown')}</span>
            </a>
            <button ref={closeRef} type="button" onClick={onClose} aria-label={t('关闭宫格提示词')}>
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
              <header className="prompt-detail__section-header"><h2>{t('原始宫格提示词')}</h2></header>
              <div className="prompt-detail__section-body"><pre className="prompt-dialog__fallback">{markdown}</pre></div>
            </section>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
