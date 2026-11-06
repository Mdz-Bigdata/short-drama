import { AlertTriangle, CircleX, Route as RouteIcon } from 'lucide-react';
import { useMemo } from 'react';

import { t } from '../../i18n';
import { issueText } from './issueText';
import type { PlaytestStats, StoryAnalysis, StoryGraph, StoryIssue } from './storyTypes';

const percent = (ratio: number) => `${Math.round(ratio * 1000) / 10}%`;
const minutes = (value: number | null) => (value === null ? '–' : t('{0} 分钟', [value]));

/** A single series, so one hue and no legend; the number beside it is what is read, in the text colour. */
function Meter({ ratio, label }: { ratio: number; label: string }) {
  return (
    <span className="istory-meter" title={label}>
      <i style={{ width: `${Math.min(100, ratio * 100)}%` }} />
    </span>
  );
}

function Tile({ value, label, note }: { value: string | number; label: string; note?: string }) {
  return (
    <div className="istory-tile">
      <strong>{value}</strong>
      <span>{label}</span>
      {note && <small>{note}</small>}
    </div>
  );
}

export function StoryAnalysisPanel({ graph, analysis, stats, stale, onPickIssue, onResetStats }: {
  graph: StoryGraph;
  analysis: StoryAnalysis | null;
  stats: PlaytestStats | null;
  stale: boolean;
  onPickIssue: (issue: StoryIssue) => void;
  onResetStats: () => void;
}) {
  const titles = useMemo(() => new Map(graph.segments.map(item => [item.id, item.title || item.id])), [graph.segments]);
  const choiceTexts = useMemo(() => new Map(graph.segments.flatMap(item => item.choices.map(choice => [choice.id, choice.text || choice.id] as const))), [graph.segments]);
  if (!analysis) return <p className="istory-hint istory-pad">{t('正在分析…')}</p>;
  const { paths, issues } = analysis;
  const worstFirst = [...issues].sort((a, b) => Number(a.severity !== 'error') - Number(b.severity !== 'error'));
  return (
    <div className="istory-report">
      {stale && <p className="istory-hint" role="status">{t('正在根据最新修改重新分析…')}</p>}
      <div className="istory-tiles">
        <Tile value={analysis.errors} label={t('错误')} note={analysis.errors ? t('修好才能导出') : t('可以导出')} />
        <Tile value={analysis.warnings} label={t('提醒')} />
        <Tile value={paths.complete_paths + (paths.truncated ? '+' : '')} label={t('完整路线')} note={paths.truncated ? t('路线太多，只枚举了前 {0} 条', [paths.max_paths]) : undefined} />
        <Tile value={percent(paths.coverage.segments_ratio)} label={t('片段覆盖')} note={`${paths.coverage.segments_covered}/${paths.coverage.segments_total}`} />
        <Tile value={percent(paths.coverage.choices_ratio)} label={t('选项覆盖')} note={`${paths.coverage.choices_covered}/${paths.coverage.choices_total}`} />
        <Tile value={paths.minutes.avg === null ? '–' : t('{0} 分钟', [paths.minutes.avg])} label={t('平均观看时长')} note={paths.minutes.min === null ? undefined : `${paths.minutes.min} ~ ${paths.minutes.max}`} />
      </div>

      <section className="istory-section">
        <h3>{t('问题')}（{issues.length}）</h3>
        {!issues.length && <p className="istory-hint">{t('没有发现问题。')}</p>}
        <ul className="istory-issues">
          {worstFirst.map((issue, index) => (
            <li key={`${issue.code}-${issue.segment_id ?? ''}-${issue.choice_id ?? issue.route_id ?? index}`} className={`is-${issue.severity}`}>
              <button type="button" disabled={!issue.segment_id} onClick={() => onPickIssue(issue)}>
                {issue.severity === 'error' ? <CircleX aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
                <span>{issueText(issue)}</span>
                <small>{issue.severity === 'error' ? t('错误') : t('提醒')}</small>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="istory-section">
        <h3>{t('结局到达率')}</h3>
        <p className="istory-hint">
          {paths.rate_method === 'enumeration' ? t('按每个可选项被选中的机会相同，逐条路线算出。') : t('故事有回环或路线太多，这是随机模拟的估算值。')}
        </p>
        <div className="istory-table-wrap">
          <table className="istory-table">
            <thead><tr><th>{t('结局')}</th><th>{t('到达率')}</th><th>{t('路线数')}</th><th>{t('时长')}</th></tr></thead>
            <tbody>
              {paths.endings.map(row => (
                <tr key={row.id}>
                  <td>{row.label ? `${row.title} · ${row.label}` : row.title}</td>
                  <td><Meter ratio={row.reach_rate} label={percent(row.reach_rate)} /><span className="istory-num">{percent(row.reach_rate)}</span></td>
                  <td className="istory-num">{row.paths}</td>
                  <td className="istory-num">{row.min_minutes === null ? '–' : `${row.min_minutes} ~ ${row.max_minutes}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {paths.unfinished_rate > 0 && <p className="istory-warning">{t('还有 {0} 的走法到不了结局。', [percent(paths.unfinished_rate)])}</p>}
      </section>

      <section className="istory-section">
        <h3><RouteIcon aria-hidden="true" /> {t('路线与观看时长')}</h3>
        {paths.routes.length === 0 && <p className="istory-hint">{t('还没有能走到结局的路线。')}</p>}
        <ol className="istory-routes">
          {paths.routes.slice(0, 20).map(route => (
            <li key={route.key}>
              <span>{route.segments.map(id => titles.get(id) ?? id).join(' → ')}</span>
              {/* Two routes can pass the same segments; the choices are what tell them apart. */}
              <small>{route.choices.map(id => choiceTexts.get(id) ?? id).join(' / ')}{route.choices.length ? ' · ' : ''}{minutes(route.minutes)} · {percent(route.probability)}</small>
            </li>
          ))}
        </ol>
        {paths.routes.length > 20 && <p className="istory-hint">{t('这里只列最常见的 20 条。')}</p>}
      </section>

      <section className="istory-section" aria-label={t('试玩统计')}>
        <header className="istory-inspector__head">
          <h3>{t('试玩统计')}</h3>
          <button type="button" className="istory-link" disabled={!stats?.runs} onClick={onResetStats}>{t('清空统计')}</button>
        </header>
        {!stats?.runs && <p className="istory-hint">{t('还没有试玩记录。保存后到「试玩」走一遍就会出现在这里。')}</p>}
        {Boolean(stats?.runs) && stats && (
          <>
            <div className="istory-tiles">
              <Tile value={stats.runs} label={t('试玩次数')} note={t('{0} 次走到结局', [stats.completed])} />
              <Tile value={`${stats.endings_reached}/${stats.endings_total}`} label={t('已到达结局')} />
              <Tile value={`${stats.segments_played}/${stats.segments_total}`} label={t('已玩片段')} />
              <Tile value={percent(stats.route_coverage)} label={t('路线覆盖')} note={`${stats.routes_played}/${stats.routes_total}`} />
              <Tile value={stats.timeouts} label={t('超时自动选择')} />
            </div>
            <div className="istory-table-wrap">
              <table className="istory-table">
                <thead><tr><th>{t('结局')}</th><th>{t('到达次数')}</th></tr></thead>
                <tbody>{stats.endings.map(row => <tr key={row.id}><td>{row.title}</td><td className="istory-num">{row.count}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="istory-table-wrap">
              <table className="istory-table">
                <thead><tr><th>{t('片段')}</th><th>{t('选项')}</th><th>{t('被选次数')}</th><th>{t('占比')}</th></tr></thead>
                <tbody>
                  {stats.choices.map(row => (
                    <tr key={row.choice_id}>
                      <td>{row.segment}</td>
                      <td>{row.text}</td>
                      <td className="istory-num">{row.count}</td>
                      <td><Meter ratio={row.share} label={percent(row.share)} /><span className="istory-num">{percent(row.share)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
