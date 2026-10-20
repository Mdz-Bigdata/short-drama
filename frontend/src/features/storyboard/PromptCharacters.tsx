import { useEffect, useId, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, UsersRound } from 'lucide-react';

import { PromptFields } from './PromptPrimitives';
import type { PromptValue } from './storyboardPromptTypes';
import { t } from '../../i18n';

export function PromptCharacters({ characters }: { characters: Array<Record<string, PromptValue>> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const [pageSize, setPageSize] = useState(1);
  const [anchorIndex, setAnchorIndex] = useState(0);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      // Measure the available content width, including browser zoom and modal resizing.
      const width = entry.contentRect.width;
      setPageSize(width >= 1056 ? 3 : width >= 688 ? 2 : 1);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const pageCount = Math.max(1, Math.ceil(characters.length / pageSize));
  const page = Math.min(Math.floor(anchorIndex / pageSize), pageCount - 1);
  const start = page * pageSize;
  const visibleCharacters = characters.slice(start, start + pageSize);

  return (
    <div className="prompt-detail__subgroup prompt-characters" ref={containerRef}>
      <div className="prompt-characters__heading">
        <h3><UsersRound aria-hidden="true" />{t('出场角色')}</h3>
        <span>{characters.length} 位角色</span>
      </div>
      {characters.length === 0 ? (
        <p className="prompt-detail__muted">{t('当前镜头未注明出场角色。')}</p>
      ) : (
        <>
          <div id={listId} className="prompt-characters__grid" data-columns={Math.min(pageSize, visibleCharacters.length)}>
            {visibleCharacters.map((character, index) => {
              const name = typeof character.name === 'string' ? character.name : `角色 ${start + index + 1}`;
              return (
                <article className="prompt-characters__card" aria-label={name} key={start + index}>
                  <header><span>{String(start + index + 1).padStart(2, '0')}</span><h4>{name}</h4></header>
                  <PromptFields value={character} omit={['name']} />
                </article>
              );
            })}
          </div>
          {pageCount > 1 && (
            <nav className="prompt-characters__pagination" aria-label={t('出场角色分页')}>
              <button type="button" disabled={page === 0} aria-controls={listId} onClick={() => setAnchorIndex((page - 1) * pageSize)}>
                <ChevronLeft aria-hidden="true" />{t('上一页')}
              </button>
              <span role="status" aria-live="polite">第 {page + 1} / {pageCount} 页 · 角色 {start + 1}–{Math.min(start + pageSize, characters.length)}</span>
              <button type="button" disabled={page === pageCount - 1} aria-controls={listId} onClick={() => setAnchorIndex((page + 1) * pageSize)}>
                {t('下一页')}<ChevronRight aria-hidden="true" />
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
