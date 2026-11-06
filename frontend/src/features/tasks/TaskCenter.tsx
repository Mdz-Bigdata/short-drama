import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, X } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { QUEUE_STATUS_LABELS, type QueueItem } from '../workbench/shotVisual';
import './TaskCenter.css';

const POLL_MS = 3000;
const FILTERS: ReadonlyArray<QueueItem['status'] | 'all'> = ['all', 'queued', 'running', 'failed', 'done', 'cancelled', 'skipped'];

export interface TaskCenterJob extends QueueItem {
  can_cancel: boolean;
  can_retry: boolean;
  cancel_requested: boolean;
  provider_job?: { job_id?: string; status?: string; error?: string } | null;
  failure?: { kind?: string; code?: string; message?: string } | null;
  log: Array<{ at: string; text: string }>;
}

export interface TaskCenterView {
  running: boolean;
  counts: Partial<Record<QueueItem['status'], number>>;
  buckets: Record<string, { limit: number; running: number }>;
  progress: { settled: number; total: number; percent: number; running: number; label: string };
  jobs: TaskCenterJob[];
}

interface TaskCenterProps {
  taskId: string;
  onClose: () => void;
}

function clock(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleTimeString();
}

/** Every generation job of one project: what waits, runs and failed, with cancel and retry. */
export function TaskCenter({ taskId, onClose }: TaskCenterProps) {
  const [view, setView] = useState<TaskCenterView | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const base = `/api/drama/${encodeURIComponent(taskId)}`;
  const load = useCallback(async () => {
    const data = await apiRequest<TaskCenterView>(`${base}/tasks`);
    setView(data);
    return data;
  }, [base]);

  useEffect(() => {
    let timer: number | undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const data = await load();
        if (!stopped) setError('');
        if (!stopped && data.running) timer = window.setTimeout(() => { void tick(); }, POLL_MS);
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : t('读取任务失败'));
      }
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [load, view?.running]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const act = useCallback(async (id: string, path: string, success: string) => {
    setBusy(id);
    setError('');
    setNotice('');
    try {
      await apiRequest<unknown>(`${base}${path}`, { method: 'POST', body: JSON.stringify({}) });
      setNotice(success);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setBusy('');
    }
  }, [base, load]);

  const toggle = (key: string) => setOpen(current => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });

  const jobs = (view?.jobs ?? []).filter(job => filter === 'all' || job.status === filter);
  const anyQueued = (view?.jobs ?? []).some(job => job.can_cancel);

  return (
    <div className="task-center" role="dialog" aria-modal="true" aria-label={t('任务中心')}>
      <div className="task-center__panel">
        <header className="task-center__head">
          <h2>{t('任务中心')}</h2>
          <button type="button" className="task-center__icon" onClick={onClose} aria-label={t('关闭')}><X size={16} /></button>
        </header>

        {view && view.progress.total > 0 && (
          <div className="task-center__progress">
            <span>
              {t('{settled}/{total} 项已结束', { settled: view.progress.settled, total: view.progress.total })}
              {view.running ? ` · ${t('运行中')} ${view.progress.running}` : ` · ${t('上一轮')}`}
              {view.progress.label ? ` · ${view.progress.label}` : ''}
            </span>
            <div className="task-center__bar" role="progressbar" aria-valuenow={view.progress.percent} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${view.progress.percent}%` }} />
            </div>
            <div className="task-center__buckets">
              {Object.entries(view.buckets).map(([bucket, state]) => (
                <span key={bucket} className="task-center__bucket">{bucket} {state.running}/{state.limit}</span>
              ))}
            </div>
          </div>
        )}

        <div className="task-center__filters" role="group" aria-label={t('按状态筛选')}>
          {FILTERS.map(option => (
            <button key={option} type="button" className="task-center__filter" aria-pressed={filter === option} onClick={() => setFilter(option)}>
              {option === 'all' ? t('全部') : t(QUEUE_STATUS_LABELS[option])}
              {option !== 'all' && view?.counts[option] ? ` ${view.counts[option]}` : ''}
            </button>
          ))}
          <span className="task-center__spacer" />
          <button type="button" className="task-center__action" disabled={!anyQueued || Boolean(busy)}
            onClick={() => { void act('all', '/queue/cancel-queued', t('已请求取消所有排队中的项；运行中的会跑完并保留结果。')); }}>
            {t('取消全部排队')}
          </button>
          <button type="button" className="task-center__icon" aria-label={t('刷新')} disabled={Boolean(busy)}
            onClick={() => { void load().catch(err => setError(err instanceof Error ? err.message : t('读取任务失败'))); }}>
            <RefreshCw size={14} />
          </button>
        </div>

        {notice && <p className="task-center__notice" role="status">{notice}</p>}
        {error && <p className="task-center__error" role="alert">{error}</p>}

        <ul className="task-center__list">
          {view && jobs.length === 0 && (
            <li className="task-center__empty">{view.jobs.length ? t('这个状态下没有任务') : t('这个项目还没有生成任务')}</li>
          )}
          {jobs.map(job => {
            const expanded = open.has(job.key);
            const message = job.failure?.message || job.error;
            return (
              <li key={job.key} className="task-center__job">
                <div className="task-center__row">
                  <button type="button" className="task-center__toggle" aria-expanded={expanded} onClick={() => toggle(job.key)}>
                    {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <span>{job.label}</span>
                  </button>
                  <span className="task-center__bucket-name">{job.bucket}</span>
                  <span className={`task-center__status task-center__status--${job.status}`}>
                    {job.cancel_requested ? t('取消中') : t(QUEUE_STATUS_LABELS[job.status] ?? job.status)}
                  </span>
                  {job.can_cancel && (
                    <button type="button" className="task-center__action" disabled={Boolean(busy)}
                      onClick={() => { void act(job.key, `/queue/${encodeURIComponent(job.key)}/cancel`, t('已请求取消，队列在下次派发前生效。')); }}>
                      {t('取消')}
                    </button>
                  )}
                  {job.can_retry && (
                    <button type="button" className="task-center__action" disabled={Boolean(busy)}
                      onClick={() => { void act(job.key, `/tasks/${encodeURIComponent(job.key)}/retry`, t('已重跑第 5 阶段：只补失败和未完成的项，已出片的沿用。')); }}>
                      {busy === job.key ? t('提交中…') : t('重试')}
                    </button>
                  )}
                </div>
                {expanded && (
                  <div className="task-center__detail">
                    {message && <p className="task-center__job-error">{message}</p>}
                    {job.reason && !job.error && <p>{t('原因')}: {job.reason}</p>}
                    {job.depends_on.length > 0 && <p>{t('依赖')}: {job.depends_on.join(', ')}</p>}
                    {job.provider_job?.job_id && <p>{t('供应商任务')}: {job.provider_job.job_id} ({job.provider_job.status})</p>}
                    <ol className="task-center__log">
                      {job.log.map((entry, index) => (
                        <li key={`${entry.at}-${index}`}><time dateTime={entry.at}>{clock(entry.at)}</time>{entry.text}</li>
                      ))}
                    </ol>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
