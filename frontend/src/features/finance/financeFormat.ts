import { t } from '../../i18n';


export const yuan = (minor: number | string | null | undefined): string => {
  const value = Number(minor ?? 0) / 100;
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const when = (moment: string | null | undefined): string => {
  if (!moment) return '—';
  // The server sends UTC; SQLite in development drops the offset.
  const text = /[zZ]|[+-]\d\d:?\d\d$/.test(moment) ? moment : `${moment}Z`;
  return new Date(text).toLocaleString('zh-CN', { hour12: false });
};

const ORDER_STATUS: Record<string, string> = {
  pending: '待支付', paid: '已支付', closed: '已关闭', partially_refunded: '部分退款', refunded: '已全额退款',
};
const REFUND_STATUS: Record<string, string> = {
  requested: '待审批', pending: '等待发送', processing: '渠道处理中', succeeded: '已退款', failed: '退款失败', rejected: '已驳回',
};
const ADJUSTMENT_STATUS: Record<string, string> = { requested: '待审批', approved: '已批准', rejected: '已驳回' };
const ITEM_STATUS: Record<string, string> = { open: '未处理', auto_resolved: '已自动关闭', resolved: '已解决', ignored: '已忽略' };
const SEVERITY: Record<string, string> = { critical: '严重', warning: '警告', info: '提示' };
const RULES: Record<string, string> = {
  R1: '渠道账单与支付单', R2: '支付单与订单', R3: '订单与发放', R4: '退款', R5: '积分余额',
  R6: '用量与扣费', R7: '项目与计费', R8: '权益与订单', R9: '钱与积分', R10: '操作与审计',
};
const KINDS: Record<string, string> = {
  on_bill_not_here: '账单上有，这里没有这笔支付单',
  on_bill_not_paid_here: '账单上已付，这里没有入账',
  amount_differs: '金额与账单不一致',
  trade_number_differs: '渠道交易号与账单不一致',
  crosses_midnight: '接近零点的付款，等下一天账单',
  paid_here_not_on_bill: '这里已入账，账单上没有',
  bill_missing: '账单迟迟没有下载到',
  bill_unusable: '账单无法读取',
  attempt_mismatch: '通知的金额或商户不符，未入账',
  payment_but_order_not_paid: '有已付支付单，订单却不是已付',
  order_paid_without_payment: '订单已付，却没有对应支付单',
  second_payment_without_refund: '多付的一笔没有退款单',
  no_ledger_credit: '订单没有积分入账记录',
  no_lot: '订单没有积分批次',
  no_term: '订单没有会员周期',
  wrong_amount: '入账积分数量不对',
  lot_does_not_match: '批次积分数量不对',
  balance_differs: '账本、批次、余额三者不一致',
  lot_negative: '批次剩余小于冻结',
  frozen_differs: '批次冻结与退款单不一致',
  lot_differs: '批次剩余与账本不一致',
  balance_frozen_differs: '余额冻结与批次不一致',
  balance_held_differs: '余额预占与预占记录不一致',
  points_taken_without_refund: '回收了积分，退款却没有成功',
  points_not_taken: '退款成功，积分没有回收',
  refund_failed: '退款失败，钱没有退回',
  refund_stuck: '退款超过 3 天没有结果',
  refund_waiting_for_decision: '退款超过 3 天没有审批',
  refunded_more_than_paid: '退款超过实付',
  order_status_differs: '订单状态与退款不一致',
  refund_on_bill_not_here: '账单上有退款，这里没有退款单',
  refund_amount_differs: '退款金额与账单不一致',
  refund_on_bill_not_approved: '账单上有退款，这里没有批准',
  refund_not_on_bill: '退款成功，账单上没有',
  points: '扣费积分与费率不符',
  failed_call_charged: '失败的调用被计费',
  wrong_rate: '用了不对的费率',
  charge_not_taken: '应扣积分与实扣不一致',
  record_without_charge: '项目有用量，没有计费记录',
  charge_not_on_project: '有计费记录，项目上没有',
  term_without_paid_order: '会员周期有效，订单已不是已付',
  term_ended_order_not_refunded: '周期已终止，订单却没有全退',
  paid_tier_used_outside_term: '使用了套餐不包含的规格',
  money_and_points_differ: '净收与已确认加递延对不上',
  no_audit_record: '人工操作没有审计记录',
  not_allowed_at_the_time: '操作人当时没有这项权限',
  same_person: '发起人和批准人是同一人',
  role_grant_not_audited: '授予角色没有审计记录',
};

const label = (table: Record<string, string>, key: string) => (table[key] ? t(table[key]) : key);
export const orderStatusLabel = (key: string) => label(ORDER_STATUS, key);
export const refundStatusLabel = (key: string) => label(REFUND_STATUS, key);
export const adjustmentStatusLabel = (key: string) => label(ADJUSTMENT_STATUS, key);
export const itemStatusLabel = (key: string) => label(ITEM_STATUS, key);
export const severityLabel = (key: string) => label(SEVERITY, key);
export const ruleLabel = (key: string) => label(RULES, key);
export const kindLabel = (key: string) => label(KINDS, key);
export const FINANCE_PERMISSIONS = ['order:read_any', 'recon:read', 'wallet:adjust_request', 'audit:read'];
