import { Flag, Lock, RotateCcw, SkipForward } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { followRoute, mapStatus, nextStep, reconcileRun, replayFrom, runToRecord, startRun, takeChoice, timedChoice, type Playthrough } from './storyEngine';
import { StoryGraphCanvas } from './StoryGraphCanvas';
import type { PlaytestRun, Selection, StoryChoice, StoryGraph, StoryRoute, StorySegment } from './storyTypes';

/** One segment on screen. Remounted for every step, so its media and timer state cannot leak into the next. */
function SegmentStage({ graph, segment, run, textOnly, onChoose, onRoute, onRestart }: {
  graph: StoryGraph;
  segment: StorySegment;
  run: Playthrough;
  textOnly: boolean;
  onChoose: (choice: StoryChoice, timedOut: boolean) => void;
  onRoute: (route: StoryRoute) => void;
  onRestart: () => void;
}) {
  const media = textOnly ? null : segment.media;
  const [videoDone, setVideoDone] = useState(false);
  // Derived rather than stored: switching to text cards mid-video has to bring the choices up.
  const revealed = videoDone || media?.kind !== 'video';
  const [mediaFailed, setMediaFailed] = useState(false);
  const outcome = useMemo(
    () => nextStep(segment, run.values, id => graph.segments.some(item => item.id === id)),
    [graph.segments, run.values, segment],
  );
  const seconds = revealed && outcome.kind === 'choices' ? segment.timer?.seconds ?? 0 : 0;
  const [ticked, setTicked] = useState<number | null>(null);
  const remaining = ticked ?? seconds;
  // The parent re-renders for unrelated reasons (statistics arriving, say); none of them may restart the clock.
  const choose = useRef(onChoose);
  useEffect(() => { choose.current = onChoose; });

  useEffect(() => {
    if (!seconds) return undefined;
    const deadline = Date.now() + seconds * 1000;
    const handle = window.setInterval(() => {
      const left = (deadline - Date.now()) / 1000;
      setTicked(Math.max(0, left));
      if (left <= 0) {
        window.clearInterval(handle);
        const picked = timedChoice(segment, outcome.options);
        if (picked) choose.current(picked, true);
      }
    }, 100);
    return () => window.clearInterval(handle);
  }, [seconds, segment, outcome]);

  return (
    <div className="istory-stage">
      <article className="istory-card" data-testid="playtest-card">
        {media && !mediaFailed && (media.kind === 'video' ? (
          <video
            className="istory-card__media"
            src={apiUrl(media.url)}
            controls
            playsInline
            onEnded={() => {
              setVideoDone(true);
              if (outcome.kind === 'route') onRoute(outcome.route);
            }}
            onError={() => {
              setMediaFailed(true);
              setVideoDone(true);
            }}
          />
        ) : <img className="istory-card__media" src={apiUrl(media.url)} alt={segment.title} onError={() => setMediaFailed(true)} />)}
        {(!media || mediaFailed) && <span className="istory-card__tag">{mediaFailed ? t('媒体加载失败，改用文字卡') : t('文字卡')}</span>}
        {segment.kind === 'ending' && <p className="istory-card__ending"><Flag aria-hidden="true" /> {t('结局')}{segment.ending_label ? ` · ${segment.ending_label}` : ''}</p>}
        <h2>{segment.title || segment.id}</h2>
        {segment.narration && <p className="istory-card__text">{segment.narration}</p>}
        {segment.dialogue.map((line, index) => (
          <p className="istory-card__line" key={index}>{line.speaker && <strong>{line.speaker}</strong>}{line.text}</p>
        ))}
      </article>
      <div className="istory-actions">
        {!revealed && (
          <button type="button" className="secondary-action" onClick={() => setVideoDone(true)}><SkipForward aria-hidden="true" /> {t('跳过')}</button>
        )}
        {revealed && seconds > 0 && (
          <div className="istory-timer" role="timer" aria-label={t('剩余 {0} 秒', [Math.ceil(remaining)])}>
            <i style={{ width: `${(remaining / seconds) * 100}%` }} />
            <span>{Math.ceil(remaining)}s</span>
          </div>
        )}
        {revealed && outcome.kind === 'route' && (
          <button type="button" className="primary-action" onClick={() => onRoute(outcome.route)}>{t('继续')}</button>
        )}
        {revealed && (outcome.kind === 'choices' || outcome.kind === 'stuck') && outcome.options.map(({ choice, locked, unconnected }) => (
          <button
            key={choice.id}
            type="button"
            className={`istory-choice ${locked ? 'is-locked' : ''}`}
            disabled={locked || unconnected}
            onClick={() => onChoose(choice, false)}
          >
            {locked && <Lock aria-hidden="true" />}
            <span>{choice.text || t('（未命名选项）')}</span>
            {locked && <small>{choice.locked_hint || t('未解锁')}</small>}
            {unconnected && <small>{t('还没有连到片段')}</small>}
          </button>
        ))}
        {revealed && outcome.kind === 'stuck' && <p className="istory-warning" role="status">{t('这里走不下去了：没有可选的出口。')}</p>}
        {(outcome.kind === 'ending' || outcome.kind === 'stuck') && (
          <button type="button" className="primary-action" onClick={onRestart}><RotateCcw aria-hidden="true" /> {t('重新开始')}</button>
        )}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  return typeof value === 'boolean' ? (value ? t('是') : t('否')) : String(value);
}

/** Plays the current draft with text cards or real media. Statistics only count a story that is saved as played. */
export function StoryPlaytest({ graph, dirty, run, onRunChange, onRecord }: {
  graph: StoryGraph;
  dirty: boolean;
  run: Playthrough | null;
  onRunChange: (run: Playthrough) => void;
  onRecord: (run: PlaytestRun) => void;
}) {
  const [textOnly, setTextOnly] = useState(false);
  const [firstRun] = useState(() => startRun(graph));
  const active = useMemo(() => (run ? reconcileRun(graph, run) : firstRun), [firstRun, graph, run]);
  const segment = graph.segments.find(item => item.id === active.current);

  const record = (finished: Playthrough) => {
    if (!dirty && finished.steps.length > 0) onRecord(runToRecord(graph, finished));
  };

  const advance = (next: Playthrough) => {
    onRunChange(next);
    if (graph.segments.find(item => item.id === next.current)?.kind === 'ending' && next !== active) record(next);
  };

  // A run left before its ending is still a run: what was reached, and that it stopped there.
  const leaveUnfinished = () => {
    if (segment?.kind !== 'ending' && active.steps.length > 1) record(active);
  };

  const restart = () => {
    leaveUnfinished();
    advance(startRun(graph, active));
  };

  const onMapSelect = (selection: Selection) => {
    if (selection?.kind !== 'segment' || selection.id === active.current) return;
    if (!active.played.has(selection.id) && !active.unlocked.has(selection.id)) return;
    leaveUnfinished();
    advance(replayFrom(graph, active, selection.id));
  };

  const endings = graph.segments.filter(item => item.kind === 'ending');
  const counts = { played: active.played.size, unlocked: active.unlocked.size, unexplored: graph.segments.length - active.played.size - active.unlocked.size };

  return (
    <div className="istory-play">
      <section className="istory-play__stage">
        <div className="istory-inline istory-play__bar">
          <label className="istory-check">
            <input type="checkbox" checked={textOnly} onChange={event => setTextOnly(event.target.checked)} />
            {t('只用文字卡')}
          </label>
          <button type="button" className="secondary-action" onClick={restart}><RotateCcw aria-hidden="true" /> {t('从头开始')}</button>
        </div>
        {dirty && <p className="istory-hint" role="note">{t('有未保存的修改：可以试玩，但这一轮不计入统计。')}</p>}
        {segment ? (
          <SegmentStage
            key={`${active.steps.length}-${active.current}-${active.fromStart}`}
            graph={graph}
            segment={segment}
            run={active}
            textOnly={textOnly}
            onChoose={(choice, timedOut) => advance(takeChoice(graph, active, choice, timedOut))}
            onRoute={route => advance(followRoute(graph, active, route))}
            onRestart={restart}
          />
        ) : (
          <div className="istory-card">
            <p>{t('当前片段已不存在，或还没有指定开场。')}</p>
            <button type="button" className="primary-action" onClick={restart}>{t('重新开始')}</button>
          </div>
        )}
      </section>
      <aside className="istory-play__side">
        <div className="istory-play__stats" aria-label={t('探索进度')}>
          <span className="is-played"><i />{t('已玩')} <strong data-testid="map-played">{counts.played}</strong></span>
          <span className="is-unlocked"><i />{t('已解锁')} <strong data-testid="map-unlocked">{counts.unlocked}</strong></span>
          <span className="is-unexplored"><i />{t('未探索')} <strong data-testid="map-unexplored">{counts.unexplored}</strong></span>
          <span><Flag aria-hidden="true" />{t('结局')} <strong data-testid="map-endings">{active.endings.size}/{endings.length}</strong></span>
        </div>
        <div className="istory-play__map">
          <StoryGraphCanvas graph={graph} status={id => mapStatus(active, id)} onSelect={onMapSelect} />
        </div>
        <p className="istory-hint">{t('点已玩或已解锁的片段，可以带着当时的数值从那里重玩。')}</p>
        {graph.variables.length > 0 && (
          <section className="istory-section">
            <h3>{t('当前变量')}</h3>
            <dl className="istory-values">
              {graph.variables.map(variable => (
                <div key={variable.id}>
                  <dt>{variable.label || variable.id}</dt>
                  <dd data-testid={`value-${variable.id}`}>{formatValue(active.values.get(variable.id))}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </aside>
    </div>
  );
}


