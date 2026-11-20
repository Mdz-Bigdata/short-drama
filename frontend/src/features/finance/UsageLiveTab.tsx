// 实时用量: what the models were asked to do in the last while, counted as it happens. Calls reach
// the server's table a few seconds after they end, and this tab asks again every five seconds, so a
// running project shows up here while it runs. Every figure is at the official price, with the
// outward quote (official plus the markup) beside it. All money is in yuan: the server converts a
// model priced in dollars before it gets here.

import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { amounts, count, fine, mediaLabel, when } from './financeFormat';
import { Problem, Stat, Waiting } from './financeParts';
import { percent } from './quoteSheet';
import './UsageLive.css';


export interface UsageFigures {
  calls: number; failed: number; unpriced_calls: number;
  input_tokens: number; output_tokens: number; reasoning_tokens: number; cached_tokens: number; tokens: number;
  images: number; seconds: number; characters: number;
  cost: Record<string, number>; quote: Record<string, number>;
}
interface RecentCall {
  at: string; media_type: string; provider: string; model: string; purpose: string; status: string; user_id: string; user_name?: string; task_id: string;
  input_tokens: number; output_tokens: number; cost: number | null; quote: number | null; currency: string;
}
export interface LiveUsage {
  generated_at: string; since: string; window_minutes: number; bucket_seconds: number; markup: number;
  /** What one dollar was converted at, and whether this window had any dollar-priced call. */
  usd_cny?: number; converted_from_usd?: boolean;
  total: UsageFigures;
  by_model: Array<UsageFigures & { media_type: string; provider: string; model: string }>;
  by_user: Array<UsageFigures & { user_id: string; user_name?: string }>;
  by_task: Array<UsageFigures & { task_id: string; user_id: string; title?: string; user_name?: string }>;
  series: Array<UsageFigures & { at: string }>;
  recent: RecentCall[];
  unpriced_models: Array<{ model: string; calls: number }>;
}

const REFRESH_MS = 5000;
const WINDOWS: ReadonlyArray<{ minutes: number; label: string }> = [
  { minutes: 15, label: '最近 15 分钟' }, { minutes: 60, label: '最近 1 小时' }, { minutes: 180, label: '最近 3 小时' },
  { minutes: 1440, label: '最近 24 小时' }, { minutes: 10080, label: '最近 7 天' }, { minutes: 43200, label: '最近 30 天' },
];
type Measure = 'tokens' | 'calls' | 'quote';
const MEASURES: ReadonlyArray<{ id: Measure; label: string }> = [
  { id: 'tokens', label: 'Token' }, { id: 'calls', label: '调用次数' }, { id: 'quote', label: '对外报价' },
];

/** Images, seconds and characters of one row, only the ones it has. */
function otherUnits(row: UsageFigures): string {
  const parts = [
    row.images ? t('{0} 张', [count(row.images)]) : '',
    row.seconds ? t('{0} 秒', [Number(row.seconds).toLocaleString('zh-CN', { maximumFractionDigits: 1 })]) : '',
    row.characters ? t('{0} 字符', [count(row.characters)]) : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '—';
}

/** The latest figures for one window, asked for again every `REFRESH_MS` while `live`. */
function useLiveUsage(minutes: number, live: boolean) {
  const [data, setData] = useState<LiveUsage | null>(null);
  const [error, setError] = useState('');
  const busy = useRef(false);
  const pull = useRef<() => Promise<void>>(async () => undefined);
  useEffect(() => {
    let current = true;
    pull.current = async () => {
      // One request at a time: a slow answer must not be overtaken by the next one's older figures.
      if (busy.current) return;
      busy.current = true;
      try {
        const next = await apiRequest<LiveUsage>(`/api/admin/finance/usage/live?minutes=${minutes}`);
        if (current) {
          setData(next);
          setError('');
        }
      } catch (err) {
        if (current) setError(err instanceof Error ? err.message : t('加载失败'));
      } finally {
        busy.current = false;
      }
    };
    const first = window.setTimeout(() => { void pull.current(); }, 0);
    return () => {
      current = false;
      window.clearTimeout(first);
    };
  }, [minutes]);
  useEffect(() => {
    if (!live) return undefined;
    // A tab nobody is looking at does not keep asking; it catches up the moment it is shown again.
    const timer = window.setInterval(() => { if (!document.hidden) void pull.current(); }, REFRESH_MS);
    const shown = () => { if (!document.hidden) void pull.current(); };
    document.addEventListener('visibilitychange', shown);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', shown);
    };
  }, [live, minutes]);
  return { data, error };
}

/** The currency the chart's money is in: yuan where there is any, else the first one there is. */
function chartCurrency(data: LiveUsage): string {
  const used = Object.keys(data.total.quote);
  return used.includes('CNY') || used.length === 0 ? 'CNY' : used[0];
}

function stepLabel(seconds: number): string {
  if (seconds >= 86400) return t('每天');
  if (seconds >= 3600) return t('每小时');
  return seconds >= 300 ? t('每 5 分钟') : t('每分钟');
}

/** One column per step of the window, one measure at a time (never two scales on one chart). */
function UsageChart({ data }: { data: LiveUsage }) {
  const [measure, setMeasure] = useState<Measure>('tokens');
  const [pointed, setPointed] = useState<number | null>(null);
  const currency = chartCurrency(data);
  const valueOf = (row: UsageFigures) => (measure === 'quote' ? row.quote[currency] ?? 0 : row[measure]);
  const show = (value: number) => (measure === 'quote' ? fine(value, currency) : count(value));
  const values = data.series.map(valueOf);
  const top = Math.max(...values, 0);
  const index = pointed !== null && pointed < data.series.length ? pointed : null;
  const moment = (at: string) => {
    const date = new Date(at);
    return data.bucket_seconds >= 86400
      ? date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
      : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  };
  const name = t(MEASURES.find(item => item.id === measure)?.label ?? '');
  return (
    <div className="usage-chart">
      <div className="finance-heading-row">
        <h3 className="finance-heading">{t('{0} · {1}', [name, stepLabel(data.bucket_seconds)])}</h3>
        <div className="usage-chart__measures" role="group" aria-label={t('图表显示')}>
          {MEASURES.map(item => (
            <button type="button" key={item.id} aria-pressed={measure === item.id} className={measure === item.id ? 'is-active' : ''} onClick={() => setMeasure(item.id)}>{t(item.label)}</button>
          ))}
        </div>
      </div>
      <p className="usage-chart__readout" aria-live="off">
        {index === null
          ? (top > 0 ? t('最高一格 {0}，指到柱子上看那一格', [show(top)]) : t('这段时间没有调用'))
          : t('{0}：{1}，{2} 次调用', [moment(data.series[index].at), show(values[index]), count(data.series[index].calls)])}
      </p>
      <div className="usage-chart__plot" onMouseLeave={() => setPointed(null)}>
        {data.series.map((point, at) => (
          <div
            key={point.at}
            className={`usage-chart__slot${index === at ? ' is-pointed' : ''}`}
            role="img"
            tabIndex={0}
            aria-label={t('{0}：{1}，{2} 次调用', [moment(point.at), show(values[at]), count(point.calls)])}
            onMouseEnter={() => setPointed(at)}
            onFocus={() => setPointed(at)}
            onBlur={() => setPointed(null)}
          >
            {values[at] > 0 && <i style={{ height: `${Math.max(2, (values[at] / top) * 100)}%` }} />}
          </div>
        ))}
      </div>
      <div className="usage-chart__axis"><span>{data.series.length ? moment(data.series[0].at) : ''}</span><span>{t('现在')}</span></div>
    </div>
  );
}

function MoneyCells({ row }: { row: UsageFigures }) {
  return <><td>{amounts(row.cost)}</td><td><strong>{amounts(row.quote)}</strong></td></>;
}

export function UsageLiveTab() {
  const [minutes, setMinutes] = useState(60);
  const [live, setLive] = useState(true);
  const { data, error } = useLiveUsage(minutes, live);
  if (!data) return error ? <Problem text={error} /> : <Waiting />;
  const total = data.total;
  const quoteName = t('对外报价（+{0}）', [percent(data.markup)]);
  return (
    <>
      <div className="finance-filters usage-live__bar">
        <select aria-label={t('时间范围')} value={minutes} onChange={event => setMinutes(Number(event.target.value))}>
          {WINDOWS.map(option => <option key={option.minutes} value={option.minutes}>{t(option.label)}</option>)}
        </select>
        <button type="button" className="secondary-action" aria-pressed={live} onClick={() => setLive(!live)}>
          {live ? <Pause size={15} /> : <Play size={15} />} {live ? t('暂停刷新') : t('继续刷新')}
        </button>
        <span className={`usage-live__state${live ? ' is-live' : ''}`} role="status">
          <i aria-hidden="true" />{live ? t('每 5 秒刷新 · 更新于 {0}', [when(data.generated_at)]) : t('已暂停 · 停在 {0}', [when(data.generated_at)])}
        </span>
      </div>
      <Problem text={error} />
      <div className="finance-stats">
        <Stat name={t('调用次数')} value={count(total.calls)} hint={total.failed ? t('其中失败 {0} 次，不计成本', [count(total.failed)]) : undefined} />
        <Stat name={t('Token 消耗')} value={count(total.tokens)} hint={t('输入 {0} · 输出 {1}', [count(total.input_tokens), count(total.output_tokens)])} />
        <Stat name={t('图片 · 时长 · 字符')} value={otherUnits(total)} />
        <Stat name={t('官方价成本')} value={amounts(total.cost)} hint={data.converted_from_usd && data.usd_cny ? t('美元计价的模型按 1 美元 = ¥{0} 折算', [String(data.usd_cny)]) : undefined} />
        <Stat name={quoteName} value={amounts(total.quote)} hint={t('官方价 × {0}', [String(Math.round((1 + data.markup) * 1000) / 1000)])} />
      </div>
      {data.unpriced_models.length > 0 && (
        <p className="finance-warning" role="status">{t('这些模型没有官方价，成本和报价都没有算进去：{0}。在价目文件里补上后才会计入。', [
          data.unpriced_models.map(item => t('{0}（{1} 次）', [item.model, count(item.calls)])).join('、'),
        ])}</p>
      )}

      <UsageChart data={data} />

      <h3 className="finance-heading">{t('按模型')}</h3>
      {data.by_model.length === 0 ? <p className="finance-empty">{t('这段时间没有调用')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table usage-table">
          <thead><tr><th>{t('类型')}</th><th>{t('模型')}</th><th>{t('调用')}</th><th>{t('输入 token')}</th><th>{t('输出 token')}</th><th>{t('其他用量')}</th><th>{t('官方价成本')}</th><th>{quoteName}</th></tr></thead>
          <tbody>{data.by_model.map(row => (
            <tr key={`${row.media_type}/${row.provider}/${row.model}`}>
              <td>{mediaLabel(row.media_type)}</td><td className="finance-mono">{row.model}</td>
              <td>{count(row.calls)}{row.failed ? t('（失败 {0}）', [count(row.failed)]) : ''}</td>
              <td>{count(row.input_tokens)}</td><td>{count(row.output_tokens)}</td><td>{otherUnits(row)}</td>
              {row.unpriced_calls > 0 && Object.keys(row.cost).length === 0 ? <td colSpan={2}>{t('没有官方价')}</td> : <MoneyCells row={row} />}
            </tr>
          ))}</tbody>
        </table></div>
      )}

      <h3 className="finance-heading">{t('按项目')}</h3>
      {data.by_task.length === 0 ? <p className="finance-empty">{t('这段时间没有项目用量')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table usage-table">
          <thead><tr><th>{t('项目')}</th><th>{t('账号')}</th><th>{t('调用')}</th><th>Token</th><th>{t('其他用量')}</th><th>{t('官方价成本')}</th><th>{quoteName}</th></tr></thead>
          <tbody>{data.by_task.map(row => (
            <tr key={`${row.task_id}/${row.user_id}`}>
              <td>{row.title || t('未命名项目')}<br /><small className="finance-mono">{row.task_id}</small></td>
              <td>{row.user_name || row.user_id || '—'}</td><td>{count(row.calls)}</td><td>{count(row.tokens)}</td><td>{otherUnits(row)}</td>
              <MoneyCells row={row} />
            </tr>
          ))}</tbody>
        </table></div>
      )}

      <h3 className="finance-heading">{t('按账号')}</h3>
      {data.by_user.length === 0 ? <p className="finance-empty">{t('这段时间没有调用')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table usage-table">
          <thead><tr><th>{t('账号')}</th><th>{t('调用')}</th><th>Token</th><th>{t('其他用量')}</th><th>{t('官方价成本')}</th><th>{quoteName}</th></tr></thead>
          <tbody>{data.by_user.map(row => (
            <tr key={row.user_id || 'none'}>
              <td>{row.user_name || (row.user_id ? <span className="finance-mono">{row.user_id}</span> : t('没有归属账号'))}</td>
              <td>{count(row.calls)}</td><td>{count(row.tokens)}</td><td>{otherUnits(row)}</td>
              <MoneyCells row={row} />
            </tr>
          ))}</tbody>
        </table></div>
      )}

      <h3 className="finance-heading">{t('最新调用')}</h3>
      {data.recent.length === 0 ? <p className="finance-empty">{t('这段时间没有调用')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table usage-table">
          <thead><tr><th>{t('时间')}</th><th>{t('模型')}</th><th>{t('用途')}</th><th>{t('账号')}</th><th>{t('输入 / 输出 token')}</th><th>{t('官方价成本')}</th><th>{quoteName}</th></tr></thead>
          <tbody>{data.recent.map((row, at) => (
            <tr key={`${row.at}/${row.model}/${at}`}>
              <td>{when(row.at)}</td><td className="finance-mono">{row.model}</td><td className="finance-mono">{row.purpose || '—'}</td>
              <td>{row.user_name || '—'}</td>
              <td>{row.input_tokens || row.output_tokens ? `${count(row.input_tokens)} / ${count(row.output_tokens)}` : '—'}</td>
              {row.status !== 'success'
                ? <td colSpan={2}>{t('失败，不计成本')}</td>
                : row.cost === null ? <td colSpan={2}>{t('没有官方价')}</td>
                  : <><td>{fine(row.cost, row.currency)}</td><td><strong>{fine(row.quote, row.currency)}</strong></td></>}
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}
