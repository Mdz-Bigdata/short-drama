import { Fragment, useMemo } from 'react';
import { TableProperties } from 'lucide-react';

import { extractSceneDialogues, type SceneDialogueLine } from './scriptOutlineUtils';
import { groupEpisodeGaps } from './episodeGaps';
import { sceneEpisode, type WriterScene } from './types';
import { t } from '../../i18n';

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

const TAG_VARIANT: Record<SceneDialogueLine['kind'], string> = {
  台词: '',
  旁白: ' is-narration',
  内心独白: ' is-monologue',
};

function buildRows(scenes: WriterScene[]): OutlineRow[] {
  const shotCounters = new Map<number, number>();
  // 单场景 characters 常有缺漏，用全剧角色并集做说话人识别更稳。
  const allSpeakers = new Set<string>();
  scenes.forEach(scene => {
    (scene.characters || []).forEach(name => {
      const trimmed = String(name).trim();
      if (trimmed) allSpeakers.add(trimmed);
    });
  });
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
      dialogues: extractSceneDialogues(scene, allSpeakers),
      characters: (scene.characters || []).map(name => String(name).trim()).filter(Boolean),
    };
  });
}

/**
 * 表格自己看得见的断层：渲染出来的集号从 15 跳到 25，中间那几集就是缺的。
 * 服务端统计还没到（看板首屏用 fallback 渲染）或请求失败时，这一条仍然成立，
 * 所以剧本大纲永远不会不声不响地跳集。末尾缺的集数看不出来，仍由服务端统计给出。
 */
function gapsBetweenRenderedEpisodes(rows: OutlineRow[]): number[] {
  const present = new Set(rows.map(row => row.episode).filter(episode => episode > 0));
  if (!present.size) return [];
  const missing: number[] = [];
  const last = Math.max(...present);
  for (let episode = Math.min(...present); episode <= last; episode += 1) {
    if (!present.has(episode)) missing.push(episode);
  }
  return missing;
}

export function ScriptOutline({ scenes, missingEpisodes = [] }: { scenes: WriterScene[]; missingEpisodes?: number[] }) {
  const rows = useMemo(() => buildRows(scenes), [scenes]);
  const gaps = groupEpisodeGaps([...missingEpisodes, ...gapsBetweenRenderedEpisodes(rows)]);
  // These are status rows, never invented shots or rewritten scene identifiers.
  const gapPositions = new Map<number, typeof gaps>();
  for (const gap of gaps) {
    const next = rows.findIndex(row => row.episode >= gap.first);
    const position = next < 0 ? rows.length : next;
    gapPositions.set(position, [...(gapPositions.get(position) || []), gap]);
  }
  const renderGaps = (position: number) => gapPositions.get(position)?.map(gap => (
    <tr className="writer-outline__gap" key={`gap-${gap.first}`}>
      <td colSpan={5}>
        <strong>第 {gap.label} 集正文缺失</strong>
        <span>{t('待补写；现有镜头编号与内容保持不变。')}</span>
      </td>
    </tr>
  ));

  if (!rows.length && !gaps.length) {
    return <div className="writer-empty">{t('生成剧本后，剧本大纲会按场景在这里展开。')}</div>;
  }

  return (
    <div className="writer-outline">
      <header className="writer-outline__header">
        <TableProperties aria-hidden="true" />
        <h3>{t('剧本明细')}</h3>
        <span>{rows.length} 条</span>
      </header>
      <div className="writer-outline__scroll" role="region" aria-label={t('剧本明细表，可横向滚动')} tabIndex={0}>
        <table className="writer-outline__table">
          <thead>
            <tr>
              <th scope="col">{t('场景')}</th>
              <th scope="col">{t('时长')}</th>
              <th scope="col">{t('内容')}</th>
              <th scope="col">{t('对话')}</th>
              <th scope="col">{t('角色')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <Fragment key={row.key}>
              {renderGaps(index)}
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
                      <span className={`writer-outline__tag${TAG_VARIANT[line.kind]}`}>
                        {line.kind}
                      </span>
                      {line.speaker && <strong>{line.speaker}</strong>}
                      {line.cue && <span className="writer-outline__cue">（{line.cue}）</span>}
                      <span className="writer-outline__line">{line.text}</span>
                    </p>
                  )) : '—'}
                </td>
                <td className="writer-outline__roles">
                  {row.characters.length ? row.characters.join('、') : '—'}
                </td>
              </tr>
              </Fragment>
            ))}
            {renderGaps(rows.length)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
