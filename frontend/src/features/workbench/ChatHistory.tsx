import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowDown } from 'lucide-react';
import './ChatHistory.css';
import { t } from '../../i18n';

export function ChatHistory({ children }: { children: ReactNode }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);
  const [showLatest, setShowLatest] = useState(false);

  // Only the history viewport moves. Polling must never scroll the page or pull
  // a reader away from older messages they are currently reviewing.
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (viewport && followingRef.current) viewport.scrollTop = viewport.scrollHeight;
  }, [children]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (followingRef.current) viewport.scrollTop = viewport.scrollHeight;
    });
    observer.observe(content);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="chat-history">
      <div ref={viewportRef} className="chat-history__viewport" role="log" aria-label={t('对话历史')}
        aria-live="polite" aria-relevant="additions text" tabIndex={0}
        onScroll={event => {
          const viewport = event.currentTarget;
          const nearBottom = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 64;
          followingRef.current = nearBottom;
          setShowLatest(!nearBottom);
        }}>
        <div ref={contentRef} className="chat-history__content">{children}</div>
      </div>
      {showLatest && (
        <button className="chat-history__latest capsule-btn" type="button" onClick={() => {
          followingRef.current = true;
          if (viewportRef.current) viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
          setShowLatest(false);
        }}><ArrowDown size={13} aria-hidden="true" />{t('回到最新消息')}</button>
      )}
    </div>
  );
}
