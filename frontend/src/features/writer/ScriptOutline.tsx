import { useMemo } from 'react';
import { TableProperties } from 'lucide-react';

import { extractSceneDialogues, type SceneDialogueLine } from './scriptOutlineUtils';
import { sceneEpisode, type WriterScene } from './types';

interface OutlineRow {
  key: string;
  sceneId: string;
  episode: number;
  shotIndex: number;
  duration: string;
  content: string;
  dialogues: SceneDialogueLine[];
  characters: string[];
}

function sceneDuration(scene: WriterScene): string {
  const label = String(scene.duration || scene.durationLabel || '').trim();
  if (label) return label;
  const seconds = Number(scene.durationSeconds);
  if (Number.isFinite(seconds) && seconds > 0) return `${Math.round(seconds)}s`;
  return '—';
}

function buildRows(scenes: WriterScene[]): OutlineRow[] {
  const shotCounters = new Map<number, number>();
  return scenes.map((scene, index) => {
    const episode = sceneEpisode(scene);
    const shotIndex = (shotCounters.get(episode) || 0) + 1;
    shotCounters.set(episode, shotIndex);
    return {
      key: `${scene.scene_id || scene.sceneId || 'scene'}-${index}`,
      sceneId: String(scene.scene_id || scene.sceneId || `S${index + 1}`),
      episode,
      shotIndex,
      duration: sceneDuration(scene),
      content: String(scene.content || '').replace(/\*\*/g, '').trim() || '—',
      dialogues: extractSceneDialogues(scene),
      characters: (scene.characters || []).map(name => String(name).trim()).filter(Boolean),
    };
  });
}

export function ScriptOutline({ scenes }: { scenes: WriterScene[] }) {
  const rows = useMemo(() => buildRows(scenes), [scenes]);

  if (!rows.length) {
    return <div className="writer-empty">生成剧本后，剧本大纲会按场景在这里展开。</div>;
  }

  return (
    <div className="writer-outline">
      <header className="writer-outline__header">
        <TableProperties aria-hidden="true" />
        <h3>剧本明细</h3>
        <span>{rows.length} 条</span>
      </header>
      <div className="writer-outline__scroll" role="region" aria-label="剧本明细表，可横向滚动" tabIndex={0}>
        <table className="writer-outline__table">
          <thead>
            <tr>
              <th scope="col">场景</th>
              <th scope="col">时长</th>
              <th scope="col">内容</th>
              <th scope="col">对话</th>
              <th scope="col">角色</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.key}>
                <td className="writer-outline__scene">
                  <strong>{row.sceneId}</strong>
                  <small>第 {row.episode} 集第 {row.shotIndex} 镜</small>
                </td>
                <td className="writer-outline__duration">{row.duration}</td>
                <td className="writer-outline__content">{row.content}</td>
                <td className="writer-outline__dialogue">
                  {row.dialogues.length ? row.dialogues.map((line, lineIndex) => (
                    <p key={lineIndex}>
                      <span className={`writer-outline__tag ${line.kind === '旁白' ? 'is-narration' : ''}`}>
                        {line.kind}
                      </span>
                      {line.speaker && <strong>{line.speaker}</strong>}
                      <span className="writer-outline__line">{line.text}</span>
                    </p>
                  )) : '—'}
                </td>
                <td className="writer-outline__roles">
                  {row.characters.length ? row.characters.join('、') : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
