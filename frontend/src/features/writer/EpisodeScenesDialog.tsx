import { useEffect, useMemo } from 'react';
import { Clapperboard, X } from 'lucide-react';

import { ScriptOutline } from './ScriptOutline';
import { sceneEpisode, type WriterScene } from './types';

export function EpisodeScenesDialog({
  episodeNumber,
  scenes,
  onClose,
}: {
  episodeNumber: number;
  scenes: WriterScene[];
  onClose: () => void;
}) {
  const episodeScenes = useMemo(
    () => scenes.filter(scene => sceneEpisode(scene) === episodeNumber),
    [episodeNumber, scenes],
  );

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
        className="writer-episode-dialog writer-episode-dialog--scenes"
        role="dialog"
        aria-modal="true"
        aria-label={`第 ${episodeNumber} 集场景明细`}
        onClick={event => event.stopPropagation()}
      >
        <header className="writer-episode-dialog__header">
          <div>
            <small>EPISODE SCENES</small>
            <h2><Clapperboard aria-hidden="true" /> 第 {episodeNumber} 集 · {episodeScenes.length} 个场景</h2>
          </div>
          <button type="button" aria-label="关闭场景明细" onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <div className="writer-episode-dialog__scenes">
          {episodeScenes.length ? (
            <ScriptOutline scenes={episodeScenes} />
          ) : (
            <p className="writer-episode-dialog__empty">该集尚未拆分出场景，完成剧本结构化后即可查看。</p>
          )}
        </div>
      </section>
    </div>
  );
}
