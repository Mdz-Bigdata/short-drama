import { useMemo, useState } from 'react';
import { BookOpenText, Check, Download, Film, ListTree, Network, RefreshCw, TimerReset } from 'lucide-react';

import { CharacterRelationshipGraph } from './CharacterRelationshipGraph';
import { ScreenplayReader } from './ScreenplayReader';
import { WriterTimeline } from './WriterTimeline';
import {
  normalizeWriterBreakdown,
  relationshipsFromScenes,
  sceneEpisode,
  type WriterDashboardStats,
  type WriterEpisode,
  type WriterScene,
} from './types';
import './WriterAgentPage.css';

function assetToText(asset: unknown) {
  if (typeof asset === 'string') return asset.trim();
  if (asset && typeof asset === 'object') return JSON.stringify(asset, null, 2);
  return '';
}

function cleanOverviewText(value: unknown) {
  if (typeof value !== 'string') return '';
  return value
    .split('\u0000').join('')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(^|\s)#{1,6}(?=\s)/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/~~([^~\n]+)~~/g, '$1')
    .replace(/\*{2,3}(?=\s|$)/g, '')
    .replace(/^\s*[-+]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function cleanStorySynopsis(value: unknown) {
  if (typeof value !== 'string') return '';
  const source = value.split('\u0000').join('');
  const storyLabel = '(?:故事梗概|剧情梗概|核心梗概|核心剧情|故事大纲|导演策划大纲)';
  const markedStoryLabel = `(?:\\*{1,3}\\s*)?${storyLabel}(?:\\s*\\*{1,3})?`;
  const quotedSynopsis = source.match(new RegExp(`${markedStoryLabel}\\s*[：:]\\s*《([^》]+)》`, 'i'))?.[1];
  if (quotedSynopsis) return cleanOverviewText(quotedSynopsis);

  const labeledSynopsis = source.match(new RegExp(
    `${markedStoryLabel}\\s*[：:]\\s*([^\\n]+?)(?=\\s+(?:[-•]\\s*)?(?:\\*{1,3}\\s*)?(?:题材类型|平台与规格|硬性规则|关键假设|未解决风险|交付物)(?:\\s*\\*{1,3})?\\s*[：:]|$)`,
    'i',
  ))?.[1];
  if (labeledSynopsis) return cleanOverviewText(labeledSynopsis);

  const meaningfulLines = source
    .split(/\r?\n/)
    .map(line => cleanOverviewText(line))
    .filter(line => line
      && !/^(?:一[、.]\s*)?(?:输入来源与关键假设|关键假设|未解决风险|交付物)$/.test(line));
  const summary = meaningfulLines.join(' ');
  const cutoff = summary.search(/\s+(?:输入来源与关键假设|关键假设|未解决风险|交付物|平台与规格|硬性规则)\s*[：:]/);
  return cleanOverviewText(cutoff >= 0 ? summary.slice(0, cutoff) : summary);
}

function sceneDurationSeconds(scene: WriterScene) {
  if (Number.isFinite(scene.durationSeconds) && Number(scene.durationSeconds) > 0) {
    return Number(scene.durationSeconds);
  }
  const raw = String(scene.duration || scene.durationLabel || '').trim().toLowerCase();
  const clock = raw.match(/^(\d{1,3}):(\d{1,2})$/);
  if (clock) return Number(clock[1]) * 60 + Number(clock[2]);
  const minutes = raw.match(/(\d+(?:\.\d+)?)\s*(?:m|min|分钟|分)/);
  const seconds = raw.match(/(\d+(?:\.\d+)?)\s*(?:s|sec|秒)/);
  if (minutes || seconds) {
    return Number(minutes?.[1] || 0) * 60 + Number(seconds?.[1] || 0);
  }
  return Number(raw.match(/\d+(?:\.\d+)?/)?.[0] || 0);
}

function durationLabel(scenes: WriterScene[]) {
  const seconds = scenes.reduce((total, scene) => total + sceneDurationSeconds(scene), 0);
  if (!seconds) return '待估算';
  return seconds >= 60 ? `${Math.round(seconds / 60)} 分钟` : `${Math.round(seconds)} 秒`;
}

function durationSecondsLabel(seconds?: number) {
  if (!seconds) return '待估算';
  return seconds >= 60 ? `${Math.round(seconds / 60)} 分钟` : `${Math.round(seconds)} 秒`;
}

export function WriterAgentPage({
  title,
  breakdown: breakdownInput,
  script,
  requestedEpisodeCount = 0,
  episodes = [],
  episodesBusy = false,
  serverStats,
  onExport,
  onPlanEpisodes,
  onProduceEpisode,
}: {
  title?: string;
  breakdown?: unknown;
  script?: unknown;
  requestedEpisodeCount?: number;
  episodes?: WriterEpisode[];
  episodesBusy?: boolean;
  serverStats?: WriterDashboardStats;
  onExport?: () => void | Promise<void>;
  onPlanEpisodes?: () => void;
  onProduceEpisode?: (index: number) => void;
}) {
  const [timelineMode, setTimelineMode] = useState<'axis' | 'line'>('axis');
  const [readerOpen, setReaderOpen] = useState(false);
  const breakdown = useMemo(() => normalizeWriterBreakdown(breakdownInput), [breakdownInput]);
  const scenes = breakdown.scenes || [];
  const timeline = breakdown.timeline || [];
  const roles = breakdown.roles || [];
  const relationships = breakdown.relationships || [];
  const overview = breakdown.overview;
  const synopsis = cleanStorySynopsis(overview?.synopsis);
  const overviewDetails = [
    { label: '题材', value: cleanOverviewText(overview?.genre), className: 'is-genre' },
    { label: '核心主题', value: cleanOverviewText(overview?.theme), className: 'is-theme' },
    { label: '世界设定', value: cleanOverviewText(overview?.world_setting || overview?.worldSetting), className: 'is-world' },
  ].filter(item => item.value);
  const displayedRelationships = relationships.length ? relationships : relationshipsFromScenes(scenes);
  const source = assetToText(script);
  const sceneEpisodes = scenes.map(sceneEpisode);
  const episodeTotal = Math.max(requestedEpisodeCount, episodes.length, ...sceneEpisodes, source ? 1 : 0);
  const characterNames = new Set([
    ...roles.map(role => role.name).filter(Boolean),
    ...displayedRelationships.flatMap(edge => [edge.from, edge.to]).filter(Boolean),
  ]);
  const episodeCards = Array.from({ length: episodeTotal }, (_, index) => {
    const number = index + 1;
    const episode = episodes.find(item => item.index === number);
    const episodeScenes = scenes.filter(scene => sceneEpisode(scene) === number);
    return {
      number,
      episode,
      scenes: episodeScenes,
      title: episode?.title || episodeScenes[0]?.content || `第 ${number} 集剧本`,
    };
  });
  const stats = [
    { label: '总集数', value: serverStats?.totalEpisodes || episodeTotal || '—', note: source ? '完整剧本已载入' : '等待剧本' },
    { label: '场景', value: serverStats?.sceneCount || scenes.length || '—', note: `${serverStats?.mainEventCount ?? timeline.length} 个主线事件` },
    { label: '角色', value: serverStats?.characterCount || characterNames.size || '—', note: `${serverStats?.relationshipCount || displayedRelationships.length} 条人物关系` },
    { label: '预估时长', value: serverStats ? durationSecondsLabel(serverStats.totalDurationSeconds) : durationLabel(scenes), note: '依据场景时长汇总' },
    { label: '剧本基调', value: serverStats?.tone || breakdown.overview?.genre || '待分析', note: breakdown.overview?.theme || '主题提炼中' },
  ];

  const handleExport = () => {
    const blob = new Blob([JSON.stringify({ title, ...breakdown }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${title || 'writer-agent'}-breakdown.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className="writer-board" aria-labelledby="writer-page-title">
      <header className="writer-board__header">
        <div>
          <span className="writer-board__eyebrow">WRITER AGENT / 02</span>
          <h1 id="writer-page-title">{title || '未命名短剧'}</h1>
          <p>专业编剧看板 · 双轨节奏 · 时间线与人物关系分析</p>
        </div>
        <div className="writer-board__actions">
          <span className={`writer-board__state ${source ? 'is-ready' : ''}`}><Check aria-hidden="true" /> {source ? '剧本已载入' : '等待生成'}</span>
          <button type="button" onClick={() => { void (onExport || handleExport)(); }} disabled={!source && scenes.length === 0}><Download aria-hidden="true" /> 导出 JSON</button>
        </div>
      </header>

      <dl className="writer-stats">
        {stats.map(stat => <div key={stat.label}><dt>{stat.label}</dt><dd>{stat.value}</dd><small>{stat.note}</small></div>)}
      </dl>

      {(synopsis || overviewDetails.length > 0) && (
        <section className="writer-overview" aria-labelledby="writer-logline-title">
          <div className="writer-overview__label" aria-hidden="true">
            <span>STORY OVERVIEW</span>
            <strong>00</strong>
          </div>
          <div className="writer-overview__content">
            <header>
              <div>
                <small>NARRATIVE BRIEF</small>
                <h2 id="writer-logline-title">故事大纲</h2>
              </div>
              <span>编剧结构提要</span>
            </header>
            {synopsis && <p className="writer-overview__synopsis">{synopsis}</p>}
            {overviewDetails.length > 0 && (
              <dl className="writer-overview__details">
                {overviewDetails.map(item => (
                  <div className={item.className} key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </section>
      )}

      <section className="writer-section writer-pacing" aria-labelledby="writer-pacing-title">
        <div className="writer-section__heading">
          <div><span>01</span><div><small>BEAT MAP</small><h2 id="writer-pacing-title">爽点节奏</h2></div></div>
          <div className="writer-segmented" aria-label="时间线显示模式">
            <button type="button" className={timelineMode === 'axis' ? 'is-active' : ''} aria-pressed={timelineMode === 'axis'} onClick={() => setTimelineMode('axis')}><TimerReset aria-hidden="true" />时间轴</button>
            <button type="button" className={timelineMode === 'line' ? 'is-active' : ''} aria-pressed={timelineMode === 'line'} onClick={() => setTimelineMode('line')}><ListTree aria-hidden="true" />时间线</button>
          </div>
        </div>
        <WriterTimeline mode={timelineMode} scenes={scenes} timeline={timeline} />
      </section>

      <section className="writer-section" aria-labelledby="writer-episodes-title">
        <div className="writer-section__heading">
          <div><span>02</span><div><small>EPISODE MAP</small><h2 id="writer-episodes-title">分集概览</h2></div></div>
          {onPlanEpisodes && <button className="writer-outline-button" type="button" onClick={onPlanEpisodes} disabled={episodesBusy}><RefreshCw aria-hidden="true" /> {episodesBusy ? '分集中…' : episodes.length ? '重新分集' : '一键分集'}</button>}
        </div>
        {episodeCards.length > 0 ? (
          <div className="writer-episodes">
            {episodeCards.map(card => (
              <article key={card.number}>
                <div><span>第 {card.number} 集</span><strong>{String(card.title).replace(/\s+/g, ' ').slice(0, 34)}</strong></div>
                <dl><div><dt>场景</dt><dd>{card.episode?.sceneCount || card.scenes.length || '—'}</dd></div><div><dt>时长</dt><dd>{card.episode?.durationSeconds ? durationSecondsLabel(card.episode.durationSeconds) : durationLabel(card.scenes)}</dd></div></dl>
                <footer>
                  <span className={`is-${card.episode?.status || 'idle'}`}>{card.episode?.status === 'completed' ? '已完成' : card.episode?.status === 'running' ? '制作中' : card.episode?.status === 'failed' ? '失败' : '待制作'}</span>
                  {card.episode?.status === 'completed' && card.episode.videoUrl
                    ? <a href={card.episode.videoUrl} target="_blank" rel="noreferrer"><Film aria-hidden="true" />播放</a>
                    : onProduceEpisode && <button type="button" disabled={card.episode?.status === 'running'} onClick={() => onProduceEpisode(card.number)}><Film aria-hidden="true" />制作本集</button>}
                </footer>
              </article>
            ))}
          </div>
        ) : <div className="writer-empty">生成剧本后，分集概览将在这里按集展开。</div>}
      </section>

      <section className="writer-section" aria-labelledby="writer-relationships-title">
        <div className="writer-section__heading"><div><span>03</span><div><small>CHARACTER NETWORK</small><h2 id="writer-relationships-title">人物关系图谱</h2></div></div><Network aria-hidden="true" /></div>
        <CharacterRelationshipGraph roles={roles} relationships={displayedRelationships} />
      </section>

      <section className="writer-section writer-script" aria-labelledby="writer-script-title">
        <div className="writer-section__heading">
          <div><span>04</span><div><small>FULL SCREENPLAY</small><h2 id="writer-script-title">完整剧本原文</h2></div></div>
          <button
            className="writer-script__book-button"
            type="button"
            aria-label="分页阅读完整剧本"
            disabled={!source}
            onClick={() => setReaderOpen(true)}
          >
            <BookOpenText aria-hidden="true" />
          </button>
        </div>
        {source ? (
          <div className="writer-script__launch">
            <div><span>SCREENPLAY ARCHIVE</span><strong>{source.length.toLocaleString('zh-CN')} 字符</strong><small>支持页码、方向键翻页与 Markdown 多维表格</small></div>
            <button type="button" onClick={() => setReaderOpen(true)}><BookOpenText aria-hidden="true" /> 打开分页阅读器</button>
          </div>
        ) : <div className="writer-empty">编剧 Agent 完成创作后，完整剧本将在这里归档。</div>}
      </section>

      {readerOpen && source && (
        <ScreenplayReader title={title || '未命名短剧'} script={source} onClose={() => setReaderOpen(false)} />
      )}
    </main>
  );
}
