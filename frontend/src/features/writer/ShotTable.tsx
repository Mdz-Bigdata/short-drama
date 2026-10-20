import { ImageOff } from 'lucide-react';
import { useState } from 'react';

import { sceneEpisode, type WriterScene } from './types';
import { t } from '../../i18n';

const PAGE_SIZE = 30;

function shotIndex(scene: WriterScene) {
  if (scene.sceneIndex && scene.sceneIndex > 0) return scene.sceneIndex;
  const match = String(scene.scene_id || scene.sceneId || '').match(/S(\d+)/i);
  return match ? Number(match[1]) : 0;
}

function durationText(scene: WriterScene) {
  if (scene.durationSeconds && scene.durationSeconds > 0) return `${scene.durationSeconds}s`;
  return String(scene.duration || scene.durationLabel || '—');
}

/** Every shot of the screenplay as one table: id and tag, the storyboard frame, length, the picture text, the lines. */
export function ShotTable({ scenes }: { scenes: WriterScene[] }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(scenes.length / PAGE_SIZE));
  const activePage = Math.min(page, pageCount - 1);
  const visible = scenes.slice(activePage * PAGE_SIZE, (activePage + 1) * PAGE_SIZE);
  // Shots within one episode are numbered from the first shot of that episode.
  const episodeStarts = new Map<number, number>();
  scenes.forEach((scene, index) => {
    const episode = sceneEpisode(scene);
    if (!episodeStarts.has(episode)) episodeStarts.set(episode, index);
  });

  if (scenes.length === 0) {
    return <div className="writer-empty">{t('生成剧本后，每一镜的画面、时长、内容与台词会在这里列出。')}</div>;
  }

  return (
    <div className="writer-shots">
      <table className="writer-shots__table">
        <thead>
          <tr>
            <th>{t('场景')}</th>
            <th>{t('画面')}</th>
            <th>{t('时长')}</th>
            <th>{t('内容')}</th>
            <th>{t('对话')}</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((scene, offset) => {
            const id = String(scene.scene_id || scene.sceneId || '');
            const episode = sceneEpisode(scene);
            const absolute = activePage * PAGE_SIZE + offset;
            const shot = shotIndex(scene) || absolute - (episodeStarts.get(episode) ?? 0) + 1;
            const lines = Array.isArray(scene.dialogue) ? scene.dialogue : [];
            const verbatim = lines.some(line => line.verbatim);
            return (
              <tr key={`${id}-${absolute}`}>
                <td className="writer-shots__scene">
                  <code>{id || `#${absolute + 1}`}</code>
                  <small>{`第 ${episode} 集第 ${shot} 镜`}</small>
                  {scene.label && <em>{scene.label}</em>}
                </td>
                <td className="writer-shots__frame">
                  {scene.imageUrl
                    ? <img src={scene.imageUrl} alt={`${id} ${t('分镜画面')}`} loading="lazy" />
                    : <span className="writer-shots__placeholder" title={t('分镜画面在第 4 阶段生成后显示')}><ImageOff aria-hidden="true" /></span>}
                </td>
                <td className="writer-shots__duration">{durationText(scene)}</td>
                <td className="writer-shots__content">{scene.description || scene.content || ''}</td>
                <td className="writer-shots__lines">
                  {lines.length === 0 ? <span className="writer-shots__silent">{t('无口播')}</span> : lines.map((line, lineIndex) => (
                    <p key={`${line.text}-${lineIndex}`}>
                      {line.verbatim && <span className="writer-shots__tag">{t('原文')}</span>}
                      {line.kind === 'dialogue' && line.speaker ? <strong>{line.speaker}：</strong> : null}
                      {line.text}
                    </p>
                  ))}
                  {verbatim && <small>{t('说书旁白为原文逐字，改词请在剧本文库里改原文后重新生成')}</small>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {pageCount > 1 && (
        <nav className="writer-shots__pagination" aria-label={t('剧本明细分页')}>
          <button type="button" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>{t('上一页')}</button>
          <span>{activePage + 1} / {pageCount}</span>
          <button type="button" disabled={activePage >= pageCount - 1} onClick={() => setPage(activePage + 1)}>{t('下一页')}</button>
        </nav>
      )}
    </div>
  );
}
