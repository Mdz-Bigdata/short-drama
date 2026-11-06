// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FinanceConsolePage } from './FinanceConsolePage';


const REFUND = {
  id: 'r1', order_id: 'o1', email: 'buyer@example.com', provider: 'alipay', amount_minor: 2320, suggested_minor: 2320, points: 400, reason: 'requested',
  status: 'requested', note: '客户申请', decision_note: '', detail: '', requested_by: 'asker', approved_by: null, created_at: '2026-11-05T00:00:00', decided_at: null, finished_at: null,
};
const SUMMARY = {
  received_minor: 2900, refunded_minor: 0, second_payments_minor: 0, second_payments_to_return_minor: 0, net_minor: 2900, earned_minor: 580, earned_usage_minor: 580,
  earned_expired_minor: 0, deferred_minor: 2320, kept_on_refunds_minor: 0, difference_minor: 0, gross_margin_minor: 300, reference_cost: { CNY: 2.8 }, open_items: { critical: 1 }, bills: 0,
  by_month: [{ month: '2026-11', received_minor: 2900, earned_minor: 580 }],
};

function serve(routes: Record<string, unknown>) {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? 'GET', body: init?.body as string | undefined });
    const match = Object.keys(routes).sort((a, b) => b.length - a.length).find(path => url.includes(path));
    return { ok: true, status: 200, json: async () => (match ? routes[match] : { items: [], total: 0 }) } as Response;
  });
  return calls;
}

describe('FinanceConsolePage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows only the tabs this person may use', async () => {
    serve({});
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['order:read_any', 'refund:request', 'wallet:adjust_request'] }} onBack={() => undefined} />);
    expect(screen.getByRole('tab', { name: '订单' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: '退款审批' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: '积分调整' })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: '财务概览' })).toBeNull();
    expect(screen.queryByRole('tab', { name: '对账差异' })).toBeNull();
    expect(screen.queryByRole('tab', { name: '审计记录' })).toBeNull();
    expect(await screen.findByText('没有符合条件的订单')).toBeTruthy();
  });

  it('shows the money and the equation that ties it to points', async () => {
    serve({ '/finance/summary': SUMMARY, '/recon/runs': { items: [], bills: [] } });
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['recon:read'] }} onBack={() => undefined} />);
    expect((await screen.findAllByText('¥29.00')).length).toBeGreaterThan(0);
    expect(screen.getByText(/净收 ¥29.00 = 已确认 ¥5.80 \+ 递延 ¥23.20/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /立即对账/ })).toBeNull();
  });

  it('never offers the person who asked for a refund the approve button', async () => {
    serve({ '/refunds': { items: [REFUND], total: 1 } });
    render(<FinanceConsolePage user={{ user_id: 'asker', permissions: ['order:read_any', 'refund:approve'] }} onBack={() => undefined} />);
    fireEvent.click(screen.getByRole('tab', { name: '退款审批' }));
    expect(await screen.findByText('这笔退款是你发起的，需要另一个人审批。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '批准并退款' })).toBeNull();
  });

  it('sends a changed amount in fen when someone else approves', async () => {
    const calls = serve({ '/refunds': { items: [REFUND], total: 1 } });
    render(<FinanceConsolePage user={{ user_id: 'other', permissions: ['order:read_any', 'refund:approve'] }} onBack={() => undefined} />);
    fireEvent.click(screen.getByRole('tab', { name: '退款审批' }));
    const approve = await screen.findByRole('button', { name: '批准并退款' });
    fireEvent.change(screen.getByLabelText(/金额（元）/), { target: { value: '19.90' } });
    fireEvent.click(approve);
    await waitFor(() => expect(calls.some(call => call.url.endsWith('/refunds/r1/approve'))).toBe(true));
    const call = calls.find(item => item.url.endsWith('/refunds/r1/approve'));
    expect(JSON.parse(call?.body ?? '{}').amount_minor).toBe(1990);
  });

  it('will not let a difference be closed without a reason', async () => {
    const item = { id: 'i1', rule: 'R1', kind: 'amount_differs', severity: 'critical', order_id: 'o1', reference: 'alipay:P1', expected: '2900', actual: '100', status: 'open', resolution: '', created_at: '2026-11-05T00:00:00' };
    const calls = serve({ '/recon/items': { items: [item], total: 1 } });
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['recon:read', 'recon:resolve'] }} onBack={() => undefined} />);
    fireEvent.click(screen.getByRole('tab', { name: '对账差异' }));
    expect(await screen.findByText('金额与账单不一致')).toBeTruthy();
    expect(screen.getByText('应为 2900，实际 100')).toBeTruthy();
    const done = screen.getByRole('button', { name: '已解决' }) as HTMLButtonElement;
    expect(done.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/处理原因/), { target: { value: '已查明' } });
    expect(done.disabled).toBe(false);
    fireEvent.click(done);
    await waitFor(() => expect(calls.some(call => call.url.endsWith('/items/i1/resolve'))).toBe(true));
  });

  it('opens an order, shows why it cannot be refunded, or offers the refund form with the suggested amount', async () => {
    const order = { id: 'o1', user_id: 'b', email: 'buyer@example.com', plan_id: 'starter', provider: 'alipay', amount: 29, status: 'paid', created_at: '2026-11-05T00:00:00', paid_at: null };
    const quote = { paid_minor: 2900, refunded_minor: 0, refundable_minor: 2900, suggested_points: 400, suggested_minor: 2320, blocked: null };
    const calls = serve({
      '/admin/orders?': { items: [order], total: 1 },
      '/admin/orders/o1': { order, attempts: [], refunds: [], lot: { granted: 500, remaining: 400, frozen: 0, expires_at: '2026-12-05T00:00:00' }, term: null, recon_items: [], quote },
    });
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['order:read_any', 'refund:request'] }} onBack={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: /buyer@example.com/ }));
    const amount = await screen.findByLabelText(/退款金额/) as HTMLInputElement;
    expect(amount.value).toBe('23.20');
    fireEvent.change(screen.getByLabelText('原因'), { target: { value: '客户申请' } });
    fireEvent.click(screen.getByRole('button', { name: '提交审批' }));
    await waitFor(() => expect(calls.some(call => call.url.endsWith('/orders/o1/refunds'))).toBe(true));
    const sent = JSON.parse(calls.find(call => call.url.endsWith('/orders/o1/refunds'))?.body ?? '{}');
    expect(sent).toEqual({ note: '客户申请', points: 400, amount_minor: 2320 });
  });
});
