import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  BookOpenText,
  Check,
  Download,
  Film,
  LayoutDashboard,
  ListTree,
  Maximize2,
  Minimize2,
  Network,
  NotebookPen,
  PenLine,
  Pencil,
  RefreshCw,
  Sparkles,
  TableProperties,
  TimerReset,
  Upload,
  Users,
} from 'lucide-react';

import { CharacterRelationshipGraph } from './CharacterRelationshipGraph';
import { namedRelationships } from './relationshipCast';
import { ScriptVersionMenu } from './ScriptVersionMenu';
import { StoryEventTimeline } from './StoryEventTimeline';
import { EpisodeScenesDialog } from './EpisodeScenesDialog';
import { EpisodeTextDialog } from './EpisodeTextDialog';
import { ScreenplayReader } from './ScreenplayReader';
import { ScreenwritingPanel } from './ScreenwritingPanel';
import { ScriptLibrary } from './ScriptLibrary';
import { ScriptOutline } from './ScriptOutline';
import { groupEpisodeGaps, normalizeMissingEpisodes } from './episodeGaps';
import { WriterTimeline } from './WriterTimeline';
import { summarizeEpisodeTitle } from './textSummary';
import {
  CREATION_MODE_LABELS,
  normalizeWriterBreakdown,
  sceneEpisode,
  type WriterDashboardStats,
  type WriterEpisode,
  type WriterRelationship,
  type WriterScene,
  type WriterScriptVersion,
} from './types';
import './WriterAgentPage.css';
import { t } from '../../i18n';

export type WriterView = 'board' | 'outline' | 'characters' | 'planning' | 'library';

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

function splitSynopsis(value: string, sentencesPerParagraph = 2, maxParagraphs = 5) {
  if (!value) return [];
  // Keep the slices verbatim: joined back together they must equal the input.
  const sentences = value.match(/[^。！？!?]+[。！？!?]*/g) || [value];
  const paragraphs: string[] = [];
  for (let index = 0; index < sentences.length; index += sentencesPerParagraph) {
    paragraphs.push(sentences.slice(index, index + sentencesPerParagraph).join(''));
  }
  if (paragraphs.length <= maxParagraphs) return paragraphs;
  // Never drop prose - fold the overflow into the last visible paragraph.
  return [
    ...paragraphs.slice(0, maxParagraphs - 1),
    paragraphs.slice(maxParagraphs - 1).join(''),
  ];
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
  taskId,
  breakdown: breakdownInput,
  script,
  scriptFileName,
  scriptSourceHash,
  requestedEpisodeCount = 0,
  episodes = [],
  episodesBusy = false,
  serverStats,
  onExport,
  onPlanEpisodes,
  onProduceEpisode,
  onSaveScript,
  onAnalyzeRelationships,
  onContinueScript,
  timelineAuthored = false,
  creationMode,
  versions = [],
  avatars = {},
  onSaveOverview,
  onRegenerateOverview,
  onSaveTimeline,
  onSaveVersion,
  onRestoreVersion,
  onOpenScenes,
  onOpenActors,
  defaultView = 'board',
}: {
  title?: string;
  taskId?: string;
  breakdown?: unknown;
  script?: unknown;
  scriptFileName?: string;
  scriptSourceHash?: string;
  requestedEpisodeCount?: number;
  episodes?: WriterEpisode[];
  episodesBusy?: boolean;
  serverStats?: WriterDashboardStats;
  onExport?: () => void | Promise<void>;
  onPlanEpisodes?: () => void;
  onProduceEpisode?: (index: number) => void;
  onSaveScript?: (
    content: string,
    fileName: string,
    baseSourceHash: string,
  ) => string | void | Promise<string | void>;
  onSaveRelationships?: (relationships: WriterRelationship[]) => Promise<void>;
  onAnalyzeRelationships?: () => Promise<void>;
  onContinueScript?: () => Promise<void>;
  relationshipsInferred?: boolean;
  timelineAuthored?: boolean;
  creationMode?: string;
  versions?: WriterScriptVersion[];
  /** name → portrait url, when stage 3 drew the character. */
  avatars?: Record<string, string>;
  onSaveOverview?: (fields: { title?: string; synopsis?: string; genre?: string; theme?: string; world_setting?: string }) => Promise<void>;
  onRegenerateOverview?: () => Promise<void>;
  onSaveTimeline?: (events: Array<{ phase: string; title: string; desc: string; points: string[] }>) => Promise<void>;
  onSaveVersion?: (label: string) => Promise<void>;
  onRestoreVersion?: (versionId: string) => Promise<void>;
  onOpenScenes?: () => void;
  onOpenActors?: () => void;
  /** Which tab opens first: the board, or the character network page. */
  defaultView?: WriterView;
}) {
  // One block for the story: its events (editable nodes) and, on the other tab, the same events laid along the scenes as a beat map.
  const [storyView, setStoryView] = useState<'events' | 'beats'>('events');
  const [networkExpanded, setNetworkExpanded] = useState(false);
  const [overviewEditing, setOverviewEditing] = useState(false);
  const [overviewDraft, setOverviewDraft] = useState({ synopsis: '', genre: '', theme: '', world_setting: '' });
  const [overviewBusy, setOverviewBusy] = useState('');
  const [overviewError, setOverviewError] = useState('');
  const [readerOpen, setReaderOpen] = useState(false);
  const [view, setView] = useState<WriterView>(defaultView);
  const [episodeTextTarget, setEpisodeTextTarget] = useState<{ episode?: number } | null>(null);
  const [sceneDialogEpisode, setSceneDialogEpisode] = useState<number | null>(null);
  const [episodePage, setEpisodePage] = useState(0);
  const [relationshipsAnalyzing, setRelationshipsAnalyzing] = useState(false);
  const [scriptContinuing, setScriptContinuing] = useState(false);
  const breakdown = useMemo(() => normalizeWriterBreakdown(breakdownInput), [breakdownInput]);
  const scenes = breakdown.scenes || [];
  const timeline = breakdown.timeline || [];
  const roles = breakdown.roles || [];
  const relationships = breakdown.relationships || [];
  const overview = breakdown.overview;
  const synopsis = cleanStorySynopsis(overview?.synopsis);
  const synopsisParagraphs = splitSynopsis(synopsis);
  const overviewDetails = [
    { label: t('题材'), value: cleanOverviewText(overview?.genre), className: 'is-genre' },
    { label: t('核心主题'), value: cleanOverviewText(overview?.theme), className: 'is-theme' },
    { label: t('世界设定'), value: cleanOverviewText(overview?.world_setting || overview?.worldSetting), className: 'is-world' },
  ].filter(item => item.value);
  // Only named relations (君臣、父子、宿敌 …) are shown or counted; a pairing counted from shared
  // scenes is not one. Until the story has named relations the page asks for an analysis.
  const displayedRelationships = namedRelationships(relationships);
  const graphIsInferred = displayedRelationships.length === 0;
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
  const EPISODES_PER_PAGE = 9;
  const episodePageCount = Math.max(1, Math.ceil(episodeCards.length / EPISODES_PER_PAGE));
  const activeEpisodePage = Math.min(episodePage, episodePageCount - 1);
  const visibleEpisodeCards = episodeCards.slice(
    activeEpisodePage * EPISODES_PER_PAGE,
    (activeEpisodePage + 1) * EPISODES_PER_PAGE,
  );
  const scriptedEpisodes = serverStats?.scriptedEpisodes || 0;
  const plannedEpisodes = serverStats?.totalEpisodes || episodeTotal;
  const missingEpisodes = normalizeMissingEpisodes(serverStats?.missingEpisodes || []);
  const missingEpisodeLabel = groupEpisodeGaps(missingEpisodes).map(group => group.label).join('、');
  // Episodes the plan calls for that the screenplay never got to.
  const missingEpisodeCount = serverStats?.missingEpisodes !== undefined
    ? missingEpisodes.length
    : scriptedEpisodes && plannedEpisodes > scriptedEpisodes
      ? plannedEpisodes - scriptedEpisodes
      : 0;
  const continueButton = missingEpisodeCount > 0 && onContinueScript ? (
    <button
      className="writer-outline-button is-primary"
      type="button"
      disabled={scriptContinuing}
      onClick={() => {
        setScriptContinuing(true);
        void onContinueScript()
          .catch(() => undefined)
          .finally(() => setScriptContinuing(false));
      }}
    >
      <PenLine aria-hidden="true" /> {scriptContinuing ? '补写中…' : `补写缺失的 ${missingEpisodeCount} 集`}
    </button>
  ) : null;
  const stats: Array<{
    label: string;
    value: string | number;
    note: string;
    onOpen?: () => void;
    hint?: string;
  }> = [
    {
      label: '总集数',
      value: serverStats?.totalEpisodes || episodeTotal || '—',
      // A short script used to hide behind the requested count: the card said 30
      // while the screenplay only carried 15 episodes of text.
      note: !source
        ? '等待剧本'
        : missingEpisodeCount
          ? `剧本正文仅 ${scriptedEpisodes} 集，尚缺 ${missingEpisodeCount} 集`
          : '完整剧本已载入',
      onOpen: source ? () => setEpisodeTextTarget({}) : undefined,
      hint: '按集查看剧本文本',
    },
    {
      label: '场景',
      value: serverStats?.sceneCount || scenes.length || '—',
      note: `${serverStats?.mainEventCount ?? timeline.length} 个主线事件`,
      onOpen: onOpenScenes,
      hint: '查看拍摄场地资产',
    },
    {
      label: '角色',
      value: serverStats?.characterCount || characterNames.size || '—',
      note: `${serverStats?.relationshipCount || displayedRelationships.length} 条人物关系`,
      onOpen: onOpenActors,
      hint: '查看数字演员',
    },
    { label: t('预估时长'), value: serverStats ? durationSecondsLabel(serverStats.totalDurationSeconds) : durationLabel(scenes), note: t('依据场景时长汇总') },
    { label: t('剧本基调'), value: serverStats?.tone || breakdown.overview?.genre || '待分析', note: breakdown.overview?.theme || '主题提炼中' },
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

  // The character network has its own page under the 人物关系 tab.
  const autoAnalyzed = useRef<string | null>(null);
  const hasScript = Boolean(source);
  useEffect(() => {
    if (view !== 'characters' || !graphIsInferred || !onAnalyzeRelationships || !hasScript || roles.length < 2) return;
    const key = taskId || title || 'writer';
    if (autoAnalyzed.current === key) return;
    autoAnalyzed.current = key;
    let active = true;
    void Promise.resolve()
      .then(() => {
        if (active) setRelationshipsAnalyzing(true);
        return onAnalyzeRelationships();
      })
      .catch(() => undefined)
      .finally(() => { if (active) setRelationshipsAnalyzing(false); });
    return () => { active = false; };
  }, [view, graphIsInferred, onAnalyzeRelationships, hasScript, roles.length, taskId, title]);

  const characterSection = (
  <section className="writer-section writer-network" aria-labelledby="writer-relationships-title">
    <div className="writer-network__title">
      <Network aria-hidden="true" />
      <h2 id="writer-relationships-title">{t('人物关系星图')} <small className="writer-section__count">{roles.length} {t('角色')} · {displayedRelationships.length} {t('关系')}</small></h2>
      <button type="button" className="writer-network__expand" aria-label={networkExpanded ? t('还原星图') : t('放大星图')} aria-pressed={networkExpanded} onClick={() => setNetworkExpanded(value => !value)}>
        {networkExpanded ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
      </button>
    </div>
    {graphIsInferred && (
      <div className="writer-network__notice" role="status">
        <p>
          {relationshipsAnalyzing
            ? t('正在按剧本识别人物关系（君臣、父子、母子、主仆、兄弟、宿敌……），完成后直接显示在星图上。')
            : onAnalyzeRelationships
              ? t('人物关系尚未识别：点击「AI 分析人物关系」，按剧本识别君臣、父子、母子、主仆、兄弟、兄妹、宿敌等具体关系。')
              : t('人物关系尚未识别。')}
        </p>
        {onAnalyzeRelationships && (
          <button
            type="button"
            disabled={relationshipsAnalyzing}
            onClick={() => {
              setRelationshipsAnalyzing(true);
              void onAnalyzeRelationships()
                .catch(() => undefined)
                .finally(() => setRelationshipsAnalyzing(false));
            }}
          >
            <Sparkles aria-hidden="true" /> {relationshipsAnalyzing ? t('分析中…') : t('AI 分析人物关系')}
          </button>
        )}
      </div>
    )}
    <div className="writer-network__card writer-network__field">
      <header>
        <span><Network aria-hidden="true" /> {t('关系星域')}</span>
        <span>{roles.length} {t('角色')} · {displayedRelationships.length} {t('关系')}</span>
      </header>
      <CharacterRelationshipGraph roles={roles} relationships={displayedRelationships} avatars={avatars} expanded={networkExpanded} />
    </div>
  </section>
  );

  return (
    <main className="writer-board" aria-labelledby="writer-page-title">
      <header className="writer-board__header">
        <div>
          <span className="writer-board__eyebrow">WRITER AGENT / 02</span>
          <h1 id="writer-page-title">{title || '未命名短剧'}</h1>
          <p>{creationMode ? t(CREATION_MODE_LABELS[creationMode] || creationMode) : t('专业编剧看板 · 双轨节奏 · 时间线与人物关系分析')}</p>
        </div>
        <div className="writer-board__actions">
          <span className={`writer-board__state ${source ? 'is-ready' : ''}`}><Check aria-hidden="true" /> {source ? t('剧本已载入') : t('等待生成')}</span>
          {(onSaveVersion || versions.length > 0) && <ScriptVersionMenu versions={versions} onSave={onSaveVersion} onRestore={onRestoreVersion} />}
          {taskId && <button type="button" className="is-primary" onClick={() => setView('library')}><Upload aria-hidden="true" /> {t('上传映视界文件')}</button>}
          <button type="button" onClick={() => { void (onExport || handleExport)(); }} disabled={!source && scenes.length === 0}><Download aria-hidden="true" /> {t('导出 JSON')}</button>
        </div>
      </header>

      <nav className="writer-view-tabs" aria-label={t('编剧页面视图')}>
        <button
          type="button"
          className={view === 'board' ? 'is-active' : ''}
          aria-pressed={view === 'board'}
          onClick={() => setView('board')}
        >
          <LayoutDashboard aria-hidden="true" /> {t('创作看板')}
        </button>
        <button
          type="button"
          className={view === 'outline' ? 'is-active' : ''}
          aria-pressed={view === 'outline'}
          onClick={() => setView('outline')}
        >
          <TableProperties aria-hidden="true" /> {t('剧本大纲')}
        </button>
        <button
          type="button"
          className={view === 'characters' ? 'is-active' : ''}
          aria-pressed={view === 'characters'}
          onClick={() => setView('characters')}
        >
          <Users aria-hidden="true" /> {t('人物关系')}
        </button>
        {taskId && (
          <button
            type="button"
            className={view === 'planning' ? 'is-active' : ''}
            aria-pressed={view === 'planning'}
            onClick={() => setView('planning')}
          >
            <NotebookPen aria-hidden="true" /> {t('分集规划')}
          </button>
        )}
        {taskId && (
          <button
            type="button"
            className={view === 'library' ? 'is-active' : ''}
            aria-pressed={view === 'library'}
            onClick={() => setView('library')}
          >
            <BookOpen aria-hidden="true" /> {t('剧本文库')}
          </button>
        )}
      </nav>

      <dl className="writer-stats">
        {stats.map(stat => (
          <div key={stat.label}>
            <dt>{stat.label}</dt>
            <dd>
              {stat.onOpen ? (
                <button
                  type="button"
                  className="writer-stat-link"
                  onClick={stat.onOpen}
                  title={stat.hint}
                  aria-label={`${stat.label} ${stat.value}，${stat.hint || '查看详情'}`}
                >
                  {stat.value}
                </button>
              ) : stat.value}
            </dd>
            <small>{stat.note}</small>
          </div>
        ))}
      </dl>

      {view === 'planning' && taskId ? (
        <section className="writer-section" aria-labelledby="writer-planning-title">
          <div className="writer-section__heading">
            <div><span>PLANNING</span><h2 id="writer-planning-title">{t('分集规划与分镜内容')}</h2></div>
          </div>
          <div className="writer-section__body">
            <ScreenwritingPanel taskId={taskId} onOpenEpisodeText={episode => setEpisodeTextTarget({ episode })} />
          </div>
        </section>
      ) : view === 'library' && taskId ? (
        <section className="writer-section" aria-labelledby="writer-library-title">
          <div className="writer-section__heading">
            <div><span>01</span><div><small>SCRIPT LIBRARY</small><h2 id="writer-library-title">{t('剧本文库')}</h2></div></div>
          </div>
          <ScriptLibrary taskId={taskId} />
        </section>
      ) : view === 'characters' ? (
        characterSection
      ) : view === 'outline' ? (
        <section className="writer-section writer-outline-section" aria-labelledby="writer-outline-title">
          <div className="writer-section__heading">
            <div><span>01</span><div><small>SCRIPT BREAKDOWN</small><h2 id="writer-outline-title">{t('剧本大纲')}</h2></div></div>
            <div className="writer-section__actions">{continueButton}</div>
          </div>
          {missingEpisodeCount > 0 && (
            <p className="writer-outline-warning" role="status">
              {missingEpisodeLabel ? `剧本缺少第 ${missingEpisodeLabel} 集正文。` : `剧本尚缺 ${missingEpisodeCount} 集正文。`}
              已有内容已保留，补齐后再继续制作。
            </p>
          )}
          <ScriptOutline scenes={scenes} missingEpisodes={missingEpisodes} />
        </section>
      ) : (
      <>
      {(synopsisParagraphs.length > 0 || overviewDetails.length > 0 || onSaveOverview) && (
        <section className="writer-overview" aria-labelledby="writer-logline-title">
          <div className="writer-overview__content">
            <header>
              <div>
                <small>NARRATIVE BRIEF</small>
                <h2 id="writer-logline-title">{t('项目概述')}</h2>
              </div>
              {(onSaveOverview || onRegenerateOverview) ? (
                <span className="writer-overview__tools">
                  {onSaveOverview && !overviewEditing && (
                    <button type="button" disabled={Boolean(overviewBusy)} onClick={() => {
                      setOverviewDraft({
                        synopsis: String(overview?.synopsis || ''), genre: String(overview?.genre || ''),
                        theme: String(overview?.theme || ''), world_setting: String(overview?.world_setting || overview?.worldSetting || ''),
                      });
                      setOverviewError('');
                      setOverviewEditing(true);
                    }}><Pencil aria-hidden="true" /> {t('编辑')}</button>
                  )}
                  {onRegenerateOverview && (
                    <button type="button" disabled={Boolean(overviewBusy)} onClick={() => {
                      setOverviewBusy('regenerate');
                      setOverviewError('');
                      void onRegenerateOverview()
                        .catch(reason => setOverviewError(reason instanceof Error ? reason.message : t('概述重新创作失败，请稍后重试。')))
                        .finally(() => setOverviewBusy(''));
                    }}><RefreshCw aria-hidden="true" className={overviewBusy === 'regenerate' ? 'spin' : undefined} /> {overviewBusy === 'regenerate' ? t('重新创作中…') : t('重新创作')}</button>
                  )}
                </span>
              ) : <span>{t('编剧结构提要')}</span>}
            </header>
            {overviewError && <p className="writer-overview__error" role="alert">{overviewError}</p>}
            {overviewEditing && onSaveOverview ? (
              <form className="writer-overview__form" aria-label={t('编辑项目概述')} onSubmit={event => {
                event.preventDefault();
                setOverviewBusy('save');
                setOverviewError('');
                void onSaveOverview(overviewDraft)
                  .then(() => setOverviewEditing(false))
                  .catch(reason => setOverviewError(reason instanceof Error ? reason.message : t('概述保存失败，请稍后重试。')))
                  .finally(() => setOverviewBusy(''));
              }}>
                <label><span>{t('故事梗概')}</span><textarea rows={5} value={overviewDraft.synopsis} maxLength={4000} onChange={event => setOverviewDraft(current => ({ ...current, synopsis: event.target.value }))} /></label>
                <div className="writer-overview__form-row">
                  <label><span>{t('题材')}</span><input value={overviewDraft.genre} maxLength={120} onChange={event => setOverviewDraft(current => ({ ...current, genre: event.target.value }))} /></label>
                  <label><span>{t('主题')}</span><input value={overviewDraft.theme} maxLength={500} onChange={event => setOverviewDraft(current => ({ ...current, theme: event.target.value }))} /></label>
                </div>
                <label><span>{t('世界观设定')}</span><textarea rows={3} value={overviewDraft.world_setting} maxLength={4000} onChange={event => setOverviewDraft(current => ({ ...current, world_setting: event.target.value }))} /></label>
                <div className="writer-overview__form-actions">
                  <button type="submit" disabled={overviewBusy === 'save'}>{overviewBusy === 'save' ? t('保存中…') : t('保存概述')}</button>
                  <button type="button" disabled={overviewBusy === 'save'} onClick={() => { setOverviewEditing(false); setOverviewError(''); }}>{t('取消')}</button>
                </div>
              </form>
            ) : null}
            {!overviewEditing && synopsisParagraphs.length === 0 && overviewDetails.length === 0 && (
              <p className="writer-overview__empty">{t('还没有项目概述：生成剧本后自动提炼，也可以点「编辑」手写或「重新创作」。')}</p>
            )}
            {!overviewEditing && synopsisParagraphs.length > 0 && (
              <div className="writer-overview__synopsis">
                {synopsisParagraphs.map((paragraph, index) => (
                  <p className={index === 0 ? 'writer-overview__lead' : undefined} key={index}>
                    {paragraph}
                  </p>
                ))}
              </div>
            )}
            {!overviewEditing && overviewDetails.length > 0 && (
              <dl className="writer-overview__details">
                {overviewDetails.map((item, index) => (
                  <div className={item.className} key={item.label}>
                    <dt><span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </section>
      )}

      <section className="writer-section writer-pacing" aria-labelledby="writer-events-title">
        <div className="writer-section__heading">
          <div><span>01</span><div><small>STORY EVENTS · BEAT MAP</small><h2 id="writer-events-title">{t('剧情事件与爽点节奏')} ({timeline.length})</h2></div></div>
          <div className="writer-segmented" aria-label={t('剧情视图')}>
            <button type="button" className={storyView === 'events' ? 'is-active' : ''} aria-pressed={storyView === 'events'} onClick={() => setStoryView('events')}><ListTree aria-hidden="true" />{t('事件节点')}</button>
            <button type="button" className={storyView === 'beats' ? 'is-active' : ''} aria-pressed={storyView === 'beats'} onClick={() => setStoryView('beats')}><TimerReset aria-hidden="true" />{t('爽点节奏')}</button>
          </div>
        </div>
        {storyView === 'events' ? (
          <div className="writer-section__body">
            <StoryEventTimeline events={timeline} authored={timelineAuthored} onSave={onSaveTimeline} />
          </div>
        ) : (
          <WriterTimeline scenes={scenes} timeline={timeline} />
        )}
      </section>

      <section className="writer-section" aria-labelledby="writer-episodes-title">
        <div className="writer-section__heading">
          <div><span>02</span><div><small>EPISODE MAP</small><h2 id="writer-episodes-title">{t('分集概览')}</h2></div></div>
          <div className="writer-section__actions">
            {continueButton}
            {onPlanEpisodes && <button className="writer-outline-button" type="button" onClick={onPlanEpisodes} disabled={episodesBusy}><RefreshCw aria-hidden="true" /> {episodesBusy ? t('分集中…') : episodes.length ? t('重新分集') : t('一键分集')}</button>}
          </div>
        </div>
        {episodeCards.length > 0 ? (
          <>
            <div className="writer-episodes">
              {visibleEpisodeCards.map(card => {
                const sceneCount = card.episode?.sceneCount || card.scenes.length || 0;
                const issues = card.episode?.issues ?? [];
                const blocking = issues.some(issue => issue.severity === 'error');
                return (
                  <article key={card.number} className={blocking ? 'has-issue' : undefined}>
                    <div>
                      <span>第 {card.number} 集</span>
                      <button
                        type="button"
                        className="writer-episodes__title"
                        disabled={!source}
                        title={source ? t('查看本集剧本文本') : undefined}
                        onClick={() => setEpisodeTextTarget({ episode: card.number })}
                      >
                        {summarizeEpisodeTitle(card.title) || `第 ${card.number} 集剧本`}
                      </button>
                    </div>
                    <dl>
                      <div>
                        <dt>{t('场景')}</dt>
                        <dd>
                          {sceneCount > 0 ? (
                            <button
                              type="button"
                              className="writer-stat-link"
                              title={t('查看本集全部场景信息')}
                              aria-label={`查看第 ${card.number} 集的 ${sceneCount} 个场景`}
                              onClick={() => setSceneDialogEpisode(card.number)}
                            >
                              {sceneCount}
                            </button>
                          ) : '—'}
                        </dd>
                      </div>
                      <div><dt>{t('时长')}</dt><dd>{card.episode?.durationSeconds ? durationSecondsLabel(card.episode.durationSeconds) : durationLabel(card.scenes)}</dd></div>
                    </dl>
                    {issues.length > 0 && (
                      <ul className="writer-episodes__issues" aria-label={`第 ${card.number} 集待处理问题`}>
                        {issues.map(issue => (
                          <li key={issue.code} className={`is-${issue.severity}`}>{issue.message}</li>
                        ))}
                      </ul>
                    )}
                    <footer>
                      <span className={`is-${card.episode?.status || 'idle'}`}>{card.episode?.status === 'completed' ? t('已完成') : card.episode?.status === 'running' ? t('制作中') : card.episode?.status === 'failed' ? t('失败') : t('待制作')}</span>
                      {card.episode?.status === 'completed' && card.episode.videoUrl
                        ? <a href={card.episode.videoUrl} target="_blank" rel="noreferrer"><Film aria-hidden="true" />{t('播放')}</a>
                        : onProduceEpisode && <button type="button" disabled={card.episode?.status === 'running'} onClick={() => onProduceEpisode(card.number)}><Film aria-hidden="true" />{t('制作本集')}</button>}
                    </footer>
                  </article>
                );
              })}
            </div>
            {episodePageCount > 1 && (
              <nav className="writer-episodes__pagination" aria-label={t('分集概览分页')}>
                <button
                  type="button"
                  disabled={activeEpisodePage === 0}
                  onClick={() => setEpisodePage(activeEpisodePage - 1)}
                >
                  {t('上一页')}
                </button>
                <span>{activeEpisodePage + 1} / {episodePageCount} 页 · 共 {episodeCards.length} 集</span>
                <button
                  type="button"
                  disabled={activeEpisodePage >= episodePageCount - 1}
                  onClick={() => setEpisodePage(activeEpisodePage + 1)}
                >
                  {t('下一页')}
                </button>
              </nav>
            )}
          </>
        ) : <div className="writer-empty">{t('生成剧本后，分集概览将在这里按集展开。')}</div>}
      </section>

      <section className="writer-section writer-script" aria-labelledby="writer-script-title">
        <div className="writer-section__heading">
          <div><span>04</span><div><small>FULL SCREENPLAY</small><h2 id="writer-script-title">{t('完整剧本原文')}</h2></div></div>
          <button
            className="writer-script__book-button"
            type="button"
            aria-label={t('分页阅读完整剧本')}
            onClick={() => setReaderOpen(true)}
          >
            <BookOpenText aria-hidden="true" />
          </button>
        </div>
        <div className="writer-script__launch">
          <div><span>SCREENPLAY ARCHIVE</span><strong>{source.length.toLocaleString('zh-CN')} 字符</strong><small>{t('支持 .md / .txt 导入、项目内编辑、分页阅读与 Markdown 多维表格')}</small></div>
          <button type="button" onClick={() => setReaderOpen(true)}><BookOpenText aria-hidden="true" /> {source ? t('打开剧本工作台') : t('导入或编辑剧本')}</button>
        </div>
      </section>
      </>
      )}

      {episodeTextTarget && (
        <EpisodeTextDialog
          title={title || '未命名短剧'}
          script={source}
          initialEpisode={episodeTextTarget.episode}
          onClose={() => setEpisodeTextTarget(null)}
        />
      )}

      {sceneDialogEpisode !== null && (
        <EpisodeScenesDialog
          episodeNumber={sceneDialogEpisode}
          scenes={scenes}
          onClose={() => setSceneDialogEpisode(null)}
        />
      )}

      {readerOpen && (
        <ScreenplayReader
          title={title || '未命名短剧'}
          script={source}
          initialFileName={scriptFileName}
          sourceHash={scriptSourceHash}
          onClose={() => setReaderOpen(false)}
          onSave={onSaveScript}
        />
      )}
    </main>
  );
}
