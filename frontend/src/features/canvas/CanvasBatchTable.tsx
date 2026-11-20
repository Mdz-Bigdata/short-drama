import { useEffect, useMemo, useState } from 'react';
import { ClipboardPaste, LoaderCircle, Plus, Table2, Trash2, X } from 'lucide-react';

import { t } from '../../i18n';
import {
  MAX_BATCH_ROWS, newRow, nodesFromRows, rowProblems, rowsFromPaste, totalsOf,
  type BatchKind, type BatchRow,
} from './canvasBeefBatchTable';
import type { CanvasNode, RunAssessment, RunStart, TierConfirmation } from './canvasTypes';
import './CanvasBeef.css';

export interface CanvasBatchTableProps {
  models: { image: string[]; video: string[] };
  defaults: { image: string; video: string };
  durations: number[];
  maxCount: number;
  /** Where the first node goes, read when the nodes are made (the view may have moved since the table opened). */
  originOf: () => { x: number; y: number };
  makeId: () => string;
  /** Put the nodes on the board and save it; resolves once they are saved. */
  onCreate: (nodes: CanvasNode[]) => Promise<void>;
  assess: (nodeIds: string[]) => Promise<RunAssessment>;
  start: (nodeIds: string[], confirmed: TierConfirmation[]) => Promise<RunStart>;
  onClose: () => void;
}

const KIND_LABEL: Record<BatchKind, string> = { image_gen: '图片', video_gen: '视频' };

function money(totals: Array<{ currency: string; cost: number }>): string {
  return totals.map(item => `${item.cost.toFixed(2)} ${item.currency}`).join(' + ');
}

/** Several picture and clip nodes made at once from a table: create them, or create them and run them after one confirmation with the total. */
export function CanvasBatchTable({ models, defaults, durations, maxCount, originOf, makeId, onCreate, assess, start, onClose }: CanvasBatchTableProps) {
  const [rows, setRows] = useState<BatchRow[]>(() => [newRow('image_gen')]);
  const [paste, setPaste] = useState('');
  const [busy, setBusy] = useState<'' | 'create' | 'assess' | 'start'>('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<{ ids: string[]; assessment: RunAssessment } | null>(null);
  const [done, setDone] = useState('');

  const problems = useMemo(() => rows.map(row => rowProblems(row, maxCount)), [rows, maxCount]);
  // Escape closes the table, but not while a create or run is on its way.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);
  const ready = rows.length > 0 && problems.every(list => list.length === 0);

  const edit = (key: string, change: Partial<BatchRow>) => setRows(current => current.map(row => (row.key === key ? { ...row, ...change } : row)));

  const create = async (andRun: boolean) => {
    setBusy(andRun ? 'assess' : 'create');
    setError('');
    setDone('');
    try {
      const nodes = nodesFromRows(rows, originOf(), makeId);
      await onCreate(nodes);
      const ids = nodes.map(node => node.id);
      if (!andRun) {
        setDone(t('已放上画布 {0} 个节点，还没有生成', [ids.length]));
        setRows([newRow(rows[rows.length - 1]?.kind ?? 'image_gen')]);
        return;
      }
      setPending({ ids, assessment: await assess(ids) });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('批量创作没有完成'));
    } finally {
      setBusy('');
    }
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy('start');
    setError('');
    try {
      const outcome = await start(pending.ids, pending.assessment.confirmations);
      if (outcome.status === 'started') {
        setDone(t('已开始生成 {0} 个节点', [pending.ids.length]));
        setPending(null);
        setRows([newRow()]);
      } else if (outcome.assessment) {
        setPending({ ids: pending.ids, assessment: outcome.assessment });
        setError(outcome.status === 'blocked' ? t('有节点不能生成，见下面的说明') : t('费用或时长有变化，请再确认一次'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('批量创作没有完成'));
    } finally {
      setBusy('');
    }
  };

  const summary = pending ? totalsOf(pending.assessment) : null;

  return (
    <div className="canvas-beef-backdrop" role="presentation">
      <div className="canvas-beef-batch" role="dialog" aria-modal="true" aria-label={t('批量创作表')}>
        <header>
          <strong><Table2 size={15} aria-hidden="true" /> {t('批量创作表')}</strong>
          <span>{t('每一行变成一个图片或视频节点；生成前会列出合计费用再确认。')}</span>
          <button type="button" onClick={onClose} aria-label={t('关闭')}><X size={15} /></button>
        </header>
        <div className="canvas-beef-batch__table" role="table" aria-label={t('批量创作的行')}>
          <div role="row" className="canvas-beef-batch__head">
            <span role="columnheader">{t('类型')}</span><span role="columnheader">{t('标题')}</span>
            <span role="columnheader">{t('提示词')}</span><span role="columnheader">{t('模型')}</span>
            <span role="columnheader">{t('时长')}</span><span role="columnheader">{t('数量')}</span><span role="columnheader" />
          </div>
          {rows.map((row, index) => {
            const choices = row.kind === 'video_gen' ? models.video : models.image;
            const rowLabel = t('第 {0} 行', [index + 1]);
            return (
              <div role="row" key={row.key} className={problems[index].length ? 'has-problem' : ''}>
                <select aria-label={`${rowLabel} ${t('类型')}`} value={row.kind} onChange={event => edit(row.key, { kind: event.target.value as BatchKind, model: '' })}>
                  {(Object.keys(KIND_LABEL) as BatchKind[]).map(kind => <option key={kind} value={kind}>{t(KIND_LABEL[kind])}</option>)}
                </select>
                <input aria-label={`${rowLabel} ${t('标题')}`} value={row.title} maxLength={80} onChange={event => edit(row.key, { title: event.target.value })} />
                <textarea aria-label={`${rowLabel} ${t('提示词')}`} value={row.prompt} rows={2} onChange={event => edit(row.key, { prompt: event.target.value })} />
                <select aria-label={`${rowLabel} ${t('模型')}`} value={row.model} onChange={event => edit(row.key, { model: event.target.value })}>
                  <option value="">{t('默认（{0}）', [row.kind === 'video_gen' ? defaults.video : defaults.image])}</option>
                  {choices.map(model => <option key={model} value={model}>{model}</option>)}
                </select>
                {row.kind === 'video_gen' ? (
                  <select aria-label={`${rowLabel} ${t('时长')}`} value={row.durationSeconds ?? ''} onChange={event => edit(row.key, { durationSeconds: Number(event.target.value) || undefined })}>
                    <option value="">{t('默认')}</option>
                    {durations.map(seconds => <option key={seconds} value={seconds}>{t('{0} 秒', [seconds])}</option>)}
                  </select>
                ) : <span className="canvas-beef-muted">—</span>}
                <input
                  aria-label={`${rowLabel} ${t('数量')}`} type="number" min={1} max={Math.max(1, maxCount)} value={row.count}
                  onChange={event => edit(row.key, { count: Number.parseInt(event.target.value, 10) || 0 })}
                />
                <button type="button" aria-label={t('删除{0}', [rowLabel])} onClick={() => setRows(current => current.filter(item => item.key !== row.key))}><Trash2 size={14} /></button>
              </div>
            );
          })}
        </div>
        <div className="canvas-beef-batch__tools">
          <button type="button" disabled={rows.length >= MAX_BATCH_ROWS} onClick={() => setRows(current => [...current, newRow(current[current.length - 1]?.kind ?? 'image_gen')])}>
            <Plus size={14} /> {t('加一行')}
          </button>
          <textarea
            aria-label={t('从表格粘贴')} rows={1} value={paste} placeholder={t('从表格粘贴：每行一条，依次是提示词、标题、类型、秒数，用制表符分开')}
            onChange={event => setPaste(event.target.value)}
          />
          <button type="button" disabled={!paste.trim()} onClick={() => {
            const pasted = rowsFromPaste(paste);
            setRows(current => [...current.filter(row => row.prompt.trim()), ...pasted].slice(0, MAX_BATCH_ROWS));
            setPaste('');
          }}><ClipboardPaste size={14} /> {t('粘贴成行')}</button>
        </div>
        {error && <div className="inline-error" role="alert">{error}</div>}
        {done && <div className="command-result" role="status">{done}</div>}
        {pending && summary && (
          <div className="canvas-beef-batch__confirm" role="group" aria-label={t('确认生成')}>
            <strong>{t('将生成 {0} 个节点', [pending.ids.length])}</strong>
            <span>{summary.totals.length ? t('预计合计 {0}', [money(summary.totals)]) : t('这一批没有可预估的费用')}</span>
            {summary.unpriced > 0 && <span>{t('另有 {0} 项暂无价格，按渠道实际计费', [summary.unpriced])}</span>}
            {summary.blocked > 0 && <span className="is-warning">{t('{0} 个节点现在不能生成', [summary.blocked])}</span>}
            <ul>
              {pending.assessment.nodes.flatMap(node => node.problems.map(problem => <li key={`${node.node_id}:${problem.code}`}>{node.label}：{problem.message}</li>))}
            </ul>
            <div>
              <button type="button" onClick={() => setPending(null)}>{t('先不生成')}</button>
              <button type="button" className="is-primary" disabled={busy !== '' || pending.assessment.decision === 'blocked'} onClick={() => void confirm()}>
                {busy === 'start' && <LoaderCircle className="spin" size={14} />} {t('确认生成')}
              </button>
            </div>
          </div>
        )}
        <footer>
          <span className="canvas-beef-muted">{t('{0} 行', [rows.length])}</span>
          <span className="canvas-beef-spacer" />
          <button type="button" disabled={!ready || busy !== '' || Boolean(pending)} onClick={() => void create(false)}>
            {busy === 'create' && <LoaderCircle className="spin" size={14} />} {t('只放上画布')}
          </button>
          <button type="button" className="is-primary" disabled={!ready || busy !== '' || Boolean(pending)} onClick={() => void create(true)}>
            {busy === 'assess' && <LoaderCircle className="spin" size={14} />} {t('放上画布并生成')}
          </button>
        </footer>
      </div>
    </div>
  );
}
