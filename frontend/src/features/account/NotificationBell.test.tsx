// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NotificationBell } from './NotificationBell';


function serve(inbox: unknown) {
  const calls: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    calls.push(`${init?.method ?? 'GET'} ${String(input)}`);
    return { ok: true, status: 200, json: async () => inbox } as Response;
  });
  return calls;
}

describe('NotificationBell', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('counts unread and to-do, and says what each one is', async () => {
    serve({
      unread: 1,
      to_do: { refunds_to_decide: 2, critical_differences: 0 },
      items: [{ id: 'n1', kind: 'refund_succeeded', data: { amount_minor: 2320 }, read: false, created_at: '2026-11-05T00:00:00Z' }],
    });
    render(<NotificationBell onOpenBilling={() => undefined} onOpenFinance={() => undefined} />);
    const bell = await screen.findByRole('button', { name: '通知，3 条未读' });
    fireEvent.click(bell);
    expect(await screen.findByText('退款 ¥23.20 已原路退回。')).toBeTruthy();
    expect(screen.getByText('2 笔退款等你审批')).toBeTruthy();
    expect(screen.queryByText(/严重对账差异/)).toBeNull();
  });

  it('opening a notice goes to billing and marks it read; a to-do goes to the console', async () => {
    const calls = serve({
      unread: 1,
      to_do: { adjustments_to_decide: 1 },
      items: [{ id: 'n1', kind: 'membership_expiring', data: { plan_name: '创作入门', days: 1 }, read: false, created_at: '2026-11-05T00:00:00Z' }],
    });
    const billing = vi.fn();
    const finance = vi.fn();
    render(<NotificationBell onOpenBilling={billing} onOpenFinance={finance} />);
    fireEvent.click(await screen.findByRole('button', { name: /通知，2 条未读/ }));
    fireEvent.click(await screen.findByText('创作入门明天到期，到期后剩余积分作废。'));
    await waitFor(() => expect(calls.some(call => call.endsWith('/api/notifications/n1/read'))).toBe(true));
    expect(billing).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /通知/ }));
    fireEvent.click(await screen.findByText('1 笔积分调整等你审批'));
    expect(finance).toHaveBeenCalled();
  });

  it('says so when there is nothing', async () => {
    serve({ unread: 0, to_do: {}, items: [] });
    render(<NotificationBell onOpenBilling={() => undefined} onOpenFinance={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: '通知' }));
    expect(await screen.findByText('没有新通知')).toBeTruthy();
  });
});
