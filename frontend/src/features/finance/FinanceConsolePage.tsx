import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowLeft, Landmark, LoaderCircle, Play, RefreshCw } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { hasPermission } from '../account/permissions';
import { channelLabel } from '../billing/paymentChannels';
import {
  adjustmentStatusLabel, itemStatusLabel, kindLabel, orderStatusLabel, refundStatusLabel, ruleLabel, severityLabel, when, yuan,
} from './financeFormat';


interface Viewer { user_id?: string; permissions?: string[] }
interface Paged<T> { items: T[]; total: number }
interface OrderRow { id: string; user_id: string; email: string; plan_id: string; provider: string; amount: number; status: string; created_at: string; paid_at: string | null }
interface RefundRow {
  id: string; order_id: string; email: string; provider: string; amount_minor: number; suggested_minor: number | null; points: number; reason: string; status: string;
  note: string; decision_note: string; detail: string; requested_by: string | null; approved_by: string | null; created_at: string; decided_at: string | null; finished_at: string | null;
}
interface AdjustmentRow { id: string; user_id: string; email: string; points: number; reason: string; status: string; requested_by: string; created_at: string; decision_note: string }
interface ReconItem { id: string; rule: string; kind: string; severity: string; order_id: string | null; reference: string; expected: string; actual: string; status: string; resolution: string; created_at: string }
interface ReconRun { id: string; period: string; status: string; summary: { found?: Record<string, number>; error?: string; posted_from_bill?: number }; started_at: string; finished_at: string | null }
interface Bill { provider: string; bill_date: string; row_count: number; paid_minor: number; refunded_minor: number }
interface AuditRow { id: string; actor_id: string | null; action: string; resource_type: string; resource_id: string; details: Record<string, unknown>; created_at: string }
interface OrderDetail {
  order: OrderRow;
  attempts: Array<{ id: string; provider: string; out_trade_no: string; channel_trade_no: string | null; amount_minor: number; status: string; settled_by: string | null; paid_at: string | null }>;
  refunds: RefundRow[];
  lot: { granted: number; remaining: number; frozen: number; expires_at: string } | null;
  term: { plan_id: string; status: string; starts_at: string; expires_at: string } | null;
  recon_items: ReconItem[];
  quote: { paid_minor: number; refunded_minor: number; refundable_minor: number; suggested_points: number; suggested_minor: number; blocked: string | null };
}
interface Summary {
  received_minor: number; refunded_minor: number; second_payments_minor: number; second_payments_to_return_minor: number; net_minor: number;
  earned_minor: number; earned_usage_minor: number; earned_expired_minor: number; deferred_minor: number; kept_on_refunds_minor: number; difference_minor: number;
  gross_margin_minor: number | null; reference_cost: Record<string, number>; open_items: Record<string, number>; bills: number;
  by_month: Array<{ month: string; received_minor?: number; refunded_minor?: number; earned_minor?: number; cost_cny_minor?: number }>;
}

const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : t(fallback));


/** Loads one list, and reloads it after anything that changed it. */
function useList<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    setError('');
    try {
      setData(await apiRequest<T>(path));
    } catch (err) {
      setError(errorText(err, '加载失败'));
    }
  }, [path]);
  useEffect(() => {
    const handle = window.setTimeout(() => { void reload(); }, 0);
    return () => window.clearTimeout(handle);
  }, [reload]);
  return { data, error, reload };
}

function Problem({ text }: { text: string }) {
  return text ? <div className="inline-error" role="alert">{text}</div> : null;
}

function Waiting() {
  return <div className="empty-library"><LoaderCircle className="spin" /> {t('正在加载…')}</div>;
}

function Stat({ name, value, hint }: { name: string; value: ReactNode; hint?: string }) {
  return <div className="finance-stat"><span>{name}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}


function OverviewTab({ canRun }: { canRun: boolean }) {
  const summary = useList<Summary>('/api/admin/finance/summary');
  const runs = useList<{ items: ReconRun[]; bills: Bill[] }>('/api/admin/recon/runs?limit=10');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const run = async () => {
    setRunning(true);
    setError('');
    try {
      await apiRequest('/api/admin/recon/runs', { method: 'POST' });
      await Promise.all([summary.reload(), runs.reload()]);
    } catch (err) {
      setError(errorText(err, '对账运行失败'));
    } finally {
      setRunning(false);
    }
  };
  const data = summary.data;
  if (!data) return summary.error ? <Problem text={summary.error} /> : <Waiting />;
  return (
    <>
      <Problem text={error || runs.error} />
      <div className="finance-stats">
        <Stat name={t('实收')} value={yuan(data.received_minor)} hint={data.second_payments_minor ? t('含多付 {0}', [yuan(data.second_payments_minor)]) : undefined} />
        <Stat name={t('已退款')} value={yuan(data.refunded_minor)} hint={data.second_payments_to_return_minor ? t('还有 {0} 多付待退回', [yuan(data.second_payments_to_return_minor)]) : undefined} />
        <Stat name={t('已确认收入')} value={yuan(data.earned_minor)} hint={t('其中到期作废 {0}', [yuan(data.earned_expired_minor)])} />
        <Stat name={t('递延（积分未用）')} value={yuan(data.deferred_minor)} />
        <Stat name={t('毛利')} value={data.gross_margin_minor === null ? '—' : yuan(data.gross_margin_minor)} hint={data.gross_margin_minor === null ? t('成本含外币，未折算') : t('已消耗积分收入减参考成本')} />
        <Stat name={t('未处理差异')} value={`${data.open_items.critical ?? 0} / ${data.open_items.warning ?? 0} / ${data.open_items.info ?? 0}`} hint={t('严重 / 警告 / 提示')} />
      </div>
      <p className="finance-equation">{t('净收 {0} = 已确认 {1} + 递延 {2} + 退款差额 {3}，相差 {4}', [
        yuan(data.net_minor), yuan(data.earned_minor), yuan(data.deferred_minor), yuan(data.kept_on_refunds_minor), yuan(data.difference_minor),
      ])}</p>

      <h3 className="finance-heading">{t('按月')}</h3>
      {data.by_month.length === 0 ? <p className="finance-empty">{t('还没有收支')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table">
          <thead><tr><th>{t('月份')}</th><th>{t('实收')}</th><th>{t('已退款')}</th><th>{t('已确认收入')}</th><th>{t('参考成本')}</th></tr></thead>
          <tbody>{data.by_month.map(row => (
            <tr key={row.month}><td>{row.month}</td><td>{yuan(row.received_minor)}</td><td>{yuan(row.refunded_minor)}</td><td>{yuan(row.earned_minor)}</td><td>{yuan(row.cost_cny_minor)}</td></tr>
          ))}</tbody>
        </table></div>
      )}

      <div className="finance-heading-row">
        <h3 className="finance-heading">{t('对账记录')}</h3>
        {canRun && <button type="button" className="secondary-action" disabled={running} onClick={() => void run()}>{running ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />} {t('立即对账')}</button>}
      </div>
      {(runs.data?.items.length ?? 0) === 0 ? <p className="finance-empty">{t('还没有对账记录')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table">
          <thead><tr><th>{t('周期')}</th><th>{t('状态')}</th><th>{t('发现')}</th><th>{t('开始时间')}</th></tr></thead>
          <tbody>{runs.data?.items.map(item => (
            <tr key={item.id}>
              <td>{item.period.startsWith('manual:') ? t('手动') : item.period}</td>
              <td>{item.status === 'done' ? t('完成') : item.status === 'failed' ? t('失败') : t('运行中')}</td>
              <td>{item.summary.error ?? (Object.entries(item.summary.found ?? {}).map(([rule, count]) => `${rule}: ${count}`).join('，') || t('无差异'))}</td>
              <td>{when(item.started_at)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}

      <h3 className="finance-heading">{t('渠道账单')}</h3>
      {(runs.data?.bills.length ?? 0) === 0 ? <p className="finance-empty">{t('还没有下载到账单。配置好支付渠道后，每天上午自动下载前一天的账单。')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table">
          <thead><tr><th>{t('日期')}</th><th>{t('渠道')}</th><th>{t('笔数')}</th><th>{t('收款')}</th><th>{t('退款')}</th></tr></thead>
          <tbody>{runs.data?.bills.map(bill => (
            <tr key={`${bill.provider}-${bill.bill_date}`}><td>{bill.bill_date}</td><td>{channelLabel(bill.provider)}</td><td>{bill.row_count}</td><td>{yuan(bill.paid_minor)}</td><td>{yuan(bill.refunded_minor)}</td></tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}


function RefundForm({ detail, onDone }: { detail: OrderDetail; onDone: () => void }) {
  const [note, setNote] = useState('');
  const [points, setPoints] = useState(String(Number(detail.quote.suggested_points)));
  const [amount, setAmount] = useState((detail.quote.suggested_minor / 100).toFixed(2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await apiRequest(`/api/admin/orders/${detail.order.id}/refunds`, {
        method: 'POST',
        body: JSON.stringify({ note, points: Number(points), amount_minor: Math.round(Number(amount) * 100) }),
      });
      onDone();
    } catch (err) {
      setError(errorText(err, '发起退款失败'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="finance-form" onSubmit={event => void submit(event)}>
      <h4>{t('发起退款')}</h4>
      <p>{t('发起后积分立即冻结，用户无法继续使用。需要另一位财务批准才会退款。')}</p>
      <label>{t('回收积分')}<input type="number" min="0" step="any" value={points} onChange={event => setPoints(event.target.value)} /></label>
      <label>{t('退款金额（元），最多 {0}', [yuan(detail.quote.refundable_minor)])}<input type="number" min="0.01" step="0.01" value={amount} onChange={event => setAmount(event.target.value)} required /></label>
      <label>{t('原因')}<input value={note} maxLength={500} onChange={event => setNote(event.target.value)} required /></label>
      <Problem text={error} />
      <button type="submit" className="primary-action" disabled={busy}>{t('提交审批')}</button>
    </form>
  );
}

function OrderPanel({ orderId, canRefund, onChanged }: { orderId: string; canRefund: boolean; onChanged: () => void }) {
  const { data, error, reload } = useList<OrderDetail>(`/api/admin/orders/${orderId}`);
  if (!data) return error ? <Problem text={error} /> : <Waiting />;
  return (
    <div className="finance-detail">
      <div className="finance-stats">
        <Stat name={t('实付')} value={yuan(data.quote.paid_minor)} />
        <Stat name={t('已退')} value={yuan(data.quote.refunded_minor)} />
        <Stat name={t('积分')} value={data.lot ? `${Number(data.lot.remaining)} / ${Number(data.lot.granted)}` : '—'} hint={data.lot && Number(data.lot.frozen) > 0 ? t('{0} 冻结中', [String(Number(data.lot.frozen))]) : t('剩余 / 发放')} />
        <Stat name={t('会员周期')} value={data.term ? data.term.plan_id : '—'} hint={data.term ? `${data.term.status} · ${when(data.term.expires_at)}` : undefined} />
      </div>
      <h4>{t('支付单')}</h4>
      {data.attempts.length === 0 ? <p className="finance-empty">{t('没有支付单')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table">
          <thead><tr><th>{t('渠道')}</th><th>{t('商户单号')}</th><th>{t('渠道单号')}</th><th>{t('金额')}</th><th>{t('状态')}</th><th>{t('入账来源')}</th></tr></thead>
          <tbody>{data.attempts.map(item => (
            <tr key={item.id}><td>{channelLabel(item.provider)}</td><td className="finance-mono">{item.out_trade_no}</td><td className="finance-mono">{item.channel_trade_no ?? '—'}</td><td>{yuan(item.amount_minor)}</td><td>{item.status}</td><td>{item.settled_by ?? '—'}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      {data.refunds.length > 0 && <>
        <h4>{t('退款')}</h4>
        <div className="finance-table-wrap"><table className="finance-table">
          <thead><tr><th>{t('金额')}</th><th>{t('积分')}</th><th>{t('状态')}</th><th>{t('原因')}</th><th>{t('时间')}</th></tr></thead>
          <tbody>{data.refunds.map(item => (
            <tr key={item.id}><td>{yuan(item.amount_minor)}</td><td>{Number(item.points)}</td><td>{refundStatusLabel(item.status)}</td><td>{item.reason === 'duplicate_payment' ? t('重复支付自动退回') : item.note}</td><td>{when(item.created_at)}</td></tr>
          ))}</tbody>
        </table></div>
      </>}
      {data.recon_items.length > 0 && <p className="finance-warning">{t('这笔订单有 {0} 条未处理的对账差异。', [String(data.recon_items.length)])}</p>}
      {data.quote.blocked
        ? <p className="finance-empty">{t('不能退款：')}{data.quote.blocked}</p>
        : canRefund && <RefundForm detail={data} onDone={() => { void reload(); onChanged(); }} />}
    </div>
  );
}

function OrdersTab({ canRefund }: { canRefund: boolean }) {
  const [query, setQuery] = useState('');
  const [applied, setApplied] = useState('');
  const [status, setStatus] = useState('');
  const [openId, setOpenId] = useState('');
  const params = new URLSearchParams({ page_size: '50', ...(status ? { status } : {}), ...(applied ? { q: applied } : {}) });
  const { data, error, reload } = useList<Paged<OrderRow>>(`/api/admin/orders?${params.toString()}`);
  return (
    <>
      <form className="finance-filters" onSubmit={event => { event.preventDefault(); setApplied(query.trim()); }}>
        <input placeholder={t('邮箱、订单号或渠道单号')} aria-label={t('搜索订单')} value={query} onChange={event => setQuery(event.target.value)} />
        <select aria-label={t('订单状态')} value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">{t('全部状态')}</option>
          {['pending', 'paid', 'partially_refunded', 'refunded', 'closed'].map(item => <option key={item} value={item}>{orderStatusLabel(item)}</option>)}
        </select>
        <button type="submit" className="secondary-action">{t('搜索')}</button>
      </form>
      <Problem text={error} />
      {!data ? (!error && <Waiting />) : data.items.length === 0 ? <p className="finance-empty">{t('没有符合条件的订单')}</p> : (
        <div className="finance-list">{data.items.map(order => (
          <div key={order.id} className="finance-row-group">
            <button type="button" className="finance-row" aria-expanded={openId === order.id} onClick={() => setOpenId(openId === order.id ? '' : order.id)}>
              <span><strong>{order.email || order.user_id}</strong><small>{order.plan_id} · {when(order.created_at)}</small></span>
              <span>{channelLabel(order.provider)}</span>
              <span>¥{Number(order.amount).toFixed(2)}</span>
              <span className={`order-status ${order.status}`}>{orderStatusLabel(order.status)}</span>
            </button>
            {openId === order.id && <OrderPanel orderId={order.id} canRefund={canRefund} onChanged={() => void reload()} />}
          </div>
        ))}</div>
      )}
    </>
  );
}


function RefundsTab({ viewer, canDecide }: { viewer: Viewer; canDecide: boolean }) {
  const [status, setStatus] = useState('requested');
  const { data, error, reload } = useList<Paged<RefundRow>>(`/api/admin/refunds?page_size=50${status ? `&status=${status}` : ''}`);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [problem, setProblem] = useState('');
  const decide = async (refund: RefundRow, action: 'approve' | 'reject') => {
    setBusy(refund.id);
    setProblem('');
    const typed = amounts[refund.id];
    try {
      await apiRequest(`/api/admin/refunds/${refund.id}/${action}`, {
        method: 'POST',
        body: JSON.stringify({ note: notes[refund.id] ?? '', ...(action === 'approve' && typed ? { amount_minor: Math.round(Number(typed) * 100) } : {}) }),
      });
      await reload();
    } catch (err) {
      setProblem(errorText(err, '操作失败'));
    } finally {
      setBusy('');
    }
  };
  return (
    <>
      <div className="finance-filters">
        <select aria-label={t('退款状态')} value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">{t('全部状态')}</option>
          {['requested', 'pending', 'processing', 'succeeded', 'failed', 'rejected'].map(item => <option key={item} value={item}>{refundStatusLabel(item)}</option>)}
        </select>
        <button type="button" className="secondary-action" onClick={() => void reload()}><RefreshCw size={15} /> {t('刷新')}</button>
      </div>
      <Problem text={problem || error} />
      {!data ? (!error && <Waiting />) : data.items.length === 0 ? <p className="finance-empty">{t('没有符合条件的退款')}</p> : (
        <div className="finance-list">{data.items.map(refund => {
          const ownRequest = refund.requested_by === viewer.user_id;
          return (
            <div key={refund.id} className="finance-card">
              <div className="finance-card__head">
                <strong>{yuan(refund.amount_minor)}</strong>
                <span>{refund.email} · {channelLabel(refund.provider)}</span>
                <span className={`order-status ${refund.status}`}>{refundStatusLabel(refund.status)}</span>
              </div>
              <p>{refund.reason === 'duplicate_payment' ? t('重复支付自动退回') : refund.note}</p>
              <small>{t('回收 {0} 积分', [String(Number(refund.points))])} · {when(refund.created_at)}{refund.detail ? ` · ${refund.detail}` : ''}{refund.decision_note ? ` · ${refund.decision_note}` : ''}</small>
              {refund.status === 'requested' && canDecide && (ownRequest
                ? <p className="finance-empty">{t('这笔退款是你发起的，需要另一个人审批。')}</p>
                : (
                  <div className="finance-decision">
                    <label>{t('金额（元），留空按申请金额')}<input type="number" min="0.01" step="0.01" value={amounts[refund.id] ?? ''} placeholder={(refund.amount_minor / 100).toFixed(2)} onChange={event => setAmounts({ ...amounts, [refund.id]: event.target.value })} /></label>
                    <label>{t('备注')}<input value={notes[refund.id] ?? ''} maxLength={500} onChange={event => setNotes({ ...notes, [refund.id]: event.target.value })} /></label>
                    <div>
                      <button type="button" className="primary-action" disabled={busy === refund.id} onClick={() => void decide(refund, 'approve')}>{t('批准并退款')}</button>
                      <button type="button" className="secondary-action" disabled={busy === refund.id} onClick={() => void decide(refund, 'reject')}>{t('驳回')}</button>
                    </div>
                  </div>
                ))}
            </div>
          );
        })}</div>
      )}
    </>
  );
}


function AdjustmentsTab({ viewer, canDecide }: { viewer: Viewer; canDecide: boolean }) {
  const { data, error, reload } = useList<Paged<AdjustmentRow>>('/api/admin/wallet-adjustments?page_size=50');
  const [userId, setUserId] = useState('');
  const [points, setPoints] = useState('');
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem('');
    try {
      await apiRequest('/api/admin/wallet-adjustments', { method: 'POST', body: JSON.stringify({ user_id: userId.trim(), points: Number(points), reason }) });
      setUserId(''); setPoints(''); setReason('');
      await reload();
    } catch (err) {
      setProblem(errorText(err, '发起调整失败'));
    }
  };
  const decide = async (id: string, action: 'approve' | 'reject') => {
    setProblem('');
    try {
      await apiRequest(`/api/admin/wallet-adjustments/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) });
      await reload();
    } catch (err) {
      setProblem(errorText(err, '操作失败'));
    }
  };
  return (
    <>
      <form className="finance-form" onSubmit={event => void submit(event)}>
        <h4>{t('发起积分调整')}</h4>
        <p>{t('需要另一个人批准才会生效。正数增加，负数扣减。')}</p>
        <label>{t('用户 ID')}<input value={userId} onChange={event => setUserId(event.target.value)} required /></label>
        <label>{t('积分')}<input type="number" step="any" value={points} onChange={event => setPoints(event.target.value)} required /></label>
        <label>{t('原因')}<input value={reason} maxLength={500} onChange={event => setReason(event.target.value)} required /></label>
        <button type="submit" className="primary-action">{t('提交审批')}</button>
      </form>
      <Problem text={problem || error} />
      {data && data.items.length === 0 && <p className="finance-empty">{t('还没有积分调整')}</p>}
      <div className="finance-list">{data?.items.map(item => (
        <div key={item.id} className="finance-card">
          <div className="finance-card__head">
            <strong>{Number(item.points) > 0 ? '+' : ''}{Number(item.points)}</strong>
            <span>{item.email || item.user_id}</span>
            <span className={`order-status ${item.status}`}>{adjustmentStatusLabel(item.status)}</span>
          </div>
          <p>{item.reason}</p>
          <small>{when(item.created_at)}</small>
          {item.status === 'requested' && canDecide && (item.requested_by === viewer.user_id
            ? <p className="finance-empty">{t('这笔调整是你发起的，需要另一个人审批。')}</p>
            : (
              <div className="finance-decision"><div>
                <button type="button" className="primary-action" onClick={() => void decide(item.id, 'approve')}>{t('批准')}</button>
                <button type="button" className="secondary-action" onClick={() => void decide(item.id, 'reject')}>{t('驳回')}</button>
              </div></div>
            ))}
        </div>
      ))}</div>
    </>
  );
}


function DifferencesTab({ canResolve }: { canResolve: boolean }) {
  const [status, setStatus] = useState('open');
  const { data, error, reload } = useList<Paged<ReconItem>>(`/api/admin/recon/items?page_size=100${status ? `&status=${status}` : ''}`);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState('');
  const resolve = async (id: string, result: 'resolved' | 'ignored') => {
    setProblem('');
    try {
      await apiRequest(`/api/admin/recon/items/${id}/resolve`, { method: 'POST', body: JSON.stringify({ status: result, resolution: notes[id] ?? '' }) });
      await reload();
    } catch (err) {
      setProblem(errorText(err, '操作失败'));
    }
  };
  return (
    <>
      <div className="finance-filters">
        <select aria-label={t('差异状态')} value={status} onChange={event => setStatus(event.target.value)}>
          {['open', 'auto_resolved', 'resolved', 'ignored'].map(item => <option key={item} value={item}>{itemStatusLabel(item)}</option>)}
        </select>
      </div>
      <Problem text={problem || error} />
      {!data ? (!error && <Waiting />) : data.items.length === 0 ? <p className="finance-empty">{t('没有差异')}</p> : (
        <div className="finance-list">{data.items.map(item => (
          <div key={item.id} className={`finance-card severity-${item.severity}`}>
            <div className="finance-card__head">
              <strong>{kindLabel(item.kind)}</strong>
              <span>{item.rule} · {ruleLabel(item.rule)}</span>
              <span className={`finance-severity ${item.severity}`}>{severityLabel(item.severity)}</span>
            </div>
            <small className="finance-mono">{item.reference}</small>
            {(item.expected || item.actual) && <small>{t('应为 {0}，实际 {1}', [item.expected || '—', item.actual || '—'])}</small>}
            <small>{when(item.created_at)}{item.resolution ? ` · ${item.resolution}` : ''}</small>
            {item.status === 'open' && canResolve && (
              <div className="finance-decision">
                <label>{t('处理原因（必填）。这里只记录说明，账目修正要另走积分调整。')}<input value={notes[item.id] ?? ''} maxLength={500} onChange={event => setNotes({ ...notes, [item.id]: event.target.value })} /></label>
                <div>
                  <button type="button" className="primary-action" disabled={!(notes[item.id] ?? '').trim()} onClick={() => void resolve(item.id, 'resolved')}>{t('已解决')}</button>
                  <button type="button" className="secondary-action" disabled={!(notes[item.id] ?? '').trim()} onClick={() => void resolve(item.id, 'ignored')}>{t('忽略')}</button>
                </div>
              </div>
            )}
          </div>
        ))}</div>
      )}
    </>
  );
}


function AuditTab() {
  const { data, error } = useList<Paged<AuditRow>>('/api/admin/audit-events?page=1&page_size=100');
  if (!data) return error ? <Problem text={error} /> : <Waiting />;
  return data.items.length === 0 ? <p className="finance-empty">{t('还没有审计记录')}</p> : (
    <div className="finance-table-wrap"><table className="finance-table">
      <thead><tr><th>{t('时间')}</th><th>{t('操作')}</th><th>{t('操作人')}</th><th>{t('对象')}</th><th>{t('详情')}</th></tr></thead>
      <tbody>{data.items.map(item => (
        <tr key={item.id}><td>{when(item.created_at)}</td><td>{item.action}</td><td className="finance-mono">{item.actor_id ?? t('系统')}</td><td className="finance-mono">{item.resource_id}</td><td className="finance-mono">{JSON.stringify(item.details)}</td></tr>
      ))}</tbody>
    </table></div>
  );
}


export function FinanceConsolePage({ user, onBack }: { user: Viewer; onBack: () => void }) {
  const tabs = [
    hasPermission(user, 'recon:read') && { id: 'overview', name: t('财务概览') },
    hasPermission(user, 'order:read_any') && { id: 'orders', name: t('订单') },
    hasPermission(user, 'order:read_any') && { id: 'refunds', name: t('退款审批') },
    hasPermission(user, 'wallet:adjust_request') && { id: 'adjustments', name: t('积分调整') },
    hasPermission(user, 'recon:read') && { id: 'differences', name: t('对账差异') },
    hasPermission(user, 'audit:read') && { id: 'audit', name: t('审计记录') },
  ].filter((tab): tab is { id: string; name: string } => Boolean(tab));
  const [active, setActive] = useState(tabs[0]?.id ?? '');
  return (
    <main className="portal-page">
      <header className="portal-header">
        <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> {t('返回创作台')}</button>
        <div><span className="eyebrow">FINANCE</span><h1>{t('财务后台')}</h1><p>{t('动钱的操作都要两个人，所有修正只追加记录，不改原记录。')}</p></div>
        <Landmark size={34} className="portal-mark" />
      </header>
      <section className="billing-section">
        <div className="finance-tabs" role="tablist">
          {tabs.map(tab => <button type="button" key={tab.id} role="tab" aria-selected={active === tab.id} className={active === tab.id ? 'is-active' : ''} onClick={() => setActive(tab.id)}>{tab.name}</button>)}
        </div>
        {active === 'overview' && <OverviewTab canRun={hasPermission(user, 'recon:resolve')} />}
        {active === 'orders' && <OrdersTab canRefund={hasPermission(user, 'refund:request')} />}
        {active === 'refunds' && <RefundsTab viewer={user} canDecide={hasPermission(user, 'refund:approve')} />}
        {active === 'adjustments' && <AdjustmentsTab viewer={user} canDecide={hasPermission(user, 'wallet:adjust_approve')} />}
        {active === 'differences' && <DifferencesTab canResolve={hasPermission(user, 'recon:resolve')} />}
        {active === 'audit' && <AuditTab />}
      </section>
    </main>
  );
}
