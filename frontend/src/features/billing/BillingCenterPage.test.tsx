// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BillingCenterPage } from './BillingCenterPage';


describe('BillingCenterPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows wallet, membership plans and order history', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const payload = url.includes('/plans')
        ? { sandbox_enabled: true, items: [{ id: 'starter', name: '创作入门', description: '500 积分', price: '29.00', currency: 'CNY', points: 500, duration_days: 30 }] }
        : url.includes('/wallet')
          ? { points: '132', money: {}, entries: [] }
          : { items: [], page: 1, page_size: 20, total: 0 };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);

    expect(await screen.findByText('132')).toBeTruthy();
    expect(screen.getByText('创作入门')).toBeTruthy();
    expect(screen.getByRole('button', { name: /沙箱购买/ })).toBeTruthy();
    expect(screen.getByText('订单记录')).toBeTruthy();
  });

  it('says buying is not open and offers no purchase while the sandbox is off', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const payload = url.includes('/plans')
        ? { sandbox_enabled: false, items: [{ id: 'starter', name: '创作入门', description: '500 积分', price: '29.00', currency: 'CNY', points: 500, duration_days: 30 }] }
        : url.includes('/wallet')
          ? { points: '0', money: {}, entries: [] }
          : { items: [], page: 1, page_size: 20, total: 0 };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);

    const button = await screen.findByRole('button', { name: /暂未开放购买/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText('在线支付暂未开放，暂时无法购买。')).toBeTruthy();
    expect(screen.queryByText(/沙箱/)).toBeNull();
  });

  it('pays by QR code at the chosen channel and only reports success when the server does', async () => {
    let status = 'pending';
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? 'GET'} ${url}`);
      const attempt = status === 'pending' ? { provider: url.includes('/pay') && String(init?.body).includes('wechat') ? 'wechat' : 'alipay', qr_code: 'weixin://wxpay/bizpayurl?pr=abc', expires_at: new Date(Date.now() + 600000).toISOString() } : null;
      let payload: unknown;
      if (url.includes('/plans')) payload = { sandbox_enabled: false, channels: ['alipay', 'wechat'], items: [{ id: 'starter', name: '创作入门', description: '', price: '29.00', currency: 'CNY', points: 500, duration_days: 30 }] };
      else if (url.includes('/wallet')) payload = { points: '0', money: {}, entries: [] };
      else if (url.endsWith('/pay') || url.endsWith('/orders/o1')) payload = { id: 'o1', status, attempt };
      else if (init?.method === 'POST') payload = { id: 'o1', status: 'pending' };
      else payload = { items: [] };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);

    fireEvent.click(await screen.findByRole('button', { name: /微信支付/ }));
    expect(await screen.findByTitle('付款二维码')).toBeTruthy();
    expect(screen.getByText(/请用微信支付扫码付款/)).toBeTruthy();
    expect(screen.queryByText('支付成功')).toBeNull();
    const payCall = calls.find(call => call.endsWith('/pay'));
    expect(payCall).toMatch(/^POST .*\/api\/billing\/orders\/o1\/pay$/);

    status = 'paid';
    expect(await screen.findByText('支付成功', {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText('500 积分已到账')).toBeTruthy();
  }, 8000);

  it('never shows a code when the channel fails, and offers to try again', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/pay')) return { ok: false, status: 502, json: async () => ({ detail: '支付渠道暂时不可用，请稍后重试或换一种支付方式' }) } as Response;
      let payload: unknown = { items: [] };
      if (url.includes('/plans')) payload = { sandbox_enabled: false, channels: ['alipay'], items: [{ id: 'starter', name: '创作入门', description: '', price: '29.00', currency: 'CNY', points: 500, duration_days: 30 }] };
      else if (url.includes('/wallet')) payload = { points: '0', money: {}, entries: [] };
      else if (init?.method === 'POST') payload = { id: 'o1', status: 'pending' };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: /支付宝/ }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: /重试/ })).toBeTruthy();
    expect(screen.queryByTitle('付款二维码')).toBeNull();
  });

  it('lets an open order be picked up again, and labels closed ones', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const payload = url.includes('/plans')
        ? { sandbox_enabled: false, channels: ['alipay'], items: [] }
        : url.includes('/wallet')
          ? { points: '0', money: {}, entries: [] }
          : { items: [
            { id: 'o1', plan_id: 'starter', provider: 'alipay', amount: '29.00', currency: 'CNY', status: 'pending', created_at: '2026-11-05T00:00:00Z' },
            { id: 'o2', plan_id: 'starter', provider: 'wechat', amount: '29.00', currency: 'CNY', status: 'closed', created_at: '2026-11-05T00:00:00Z' },
          ] };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);
    expect(await screen.findByRole('button', { name: '继续支付' })).toBeTruthy();
    expect(screen.getByText('已关闭')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '继续支付' })).toHaveLength(1);
  });

  it('shows what can be spent once charging is on', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const payload = url.includes('/plans')
        ? { sandbox_enabled: false, items: [] }
        : url.includes('/wallet')
          ? { points: '999', available: '420', held: '80', charging: true, money: {}, entries: [] }
          : { items: [], page: 1, page_size: 20, total: 0 };
      return { ok: true, json: async () => payload } as Response;
    });
    render(<BillingCenterPage onBack={() => undefined} />);
    expect(await screen.findByText('420')).toBeTruthy();
    expect(screen.getByText('其中 80 积分正在使用')).toBeTruthy();
    expect(screen.queryByText('999')).toBeNull();
  });
});
