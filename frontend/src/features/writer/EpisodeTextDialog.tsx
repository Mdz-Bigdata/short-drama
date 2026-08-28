import { useEffect, useMemo, useState } from 'react';
import { ScrollText, X } from 'lucide-react';

import { splitScriptEpisodes } from './scriptOutlineUtils';

export function EpisodeTextDialog({
  title,
  script,
  initialEpisode,
  onClose,
}: {
  title: string;
  script: string;
  initialEpisode?: number;
  onClose: () => void;
}) {
  const episodes = useMemo(() => splitScriptEpisodes(script), [script]);
  const [activeNumber, setActiveNumber] = useState(() => (
    episodes.some(episode => episode.number === initialEpisode)
      ? initialEpisode as number
      : episodes[0]?.number ?? 1
  ));
  const active = episodes.find(episode => episode.number === activeNumber) || episodes[0];

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="writer-episode-dialog__backdrop" role="presentation" onClick={onClose}>
      <section
        className="writer-episode-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`${title} 分集剧本文本`}
        onClick={event => event.stopPropagation()}
      >
        <header className="writer-episode-dialog__header">
          <div>
            <small>EPISODE SCRIPTS</small>
            <h2><ScrollText aria-hidden="true" /> 分集剧本 · {title}</h2>
          </div>
          <button type="button" aria-label="关闭分集剧本" onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        {episodes.length ? (
          <div className="writer-episode-dialog__body">
            <nav className="writer-episode-dialog__nav" aria-label="选择剧集">
              {episodes.map(episode => (
                <button
                  key={episode.number}
                  type="button"
                  className={episode.number === active?.number ? 'is-active' : ''}
                  aria-pressed={episode.number === active?.number}
                  onClick={() => setActiveNumber(episode.number)}
                >
                  <strong>第 {episode.number} 集</strong>
                  <span>{episode.title}</span>
                </button>
              ))}
            </nav>
            <pre
              className="writer-episode-dialog__text"
              tabIndex={0}
              aria-label={active ? `第 ${active.number} 集剧本文本` : '剧本文本'}
            >
              {active?.text || ''}
            </pre>
          </div>
        ) : (
          <p className="writer-episode-dialog__empty">尚未载入剧本，生成或导入剧本后即可按集查看。</p>
        )}
      </section>
    </div>
  );
}
