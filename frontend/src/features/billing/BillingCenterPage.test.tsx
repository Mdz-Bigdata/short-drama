// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BillingCenterPage } from './BillingCenterPage';


describe('BillingCenterPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows wallet, membership plans and order history', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const payload = url.includes('/plans')
        ? { items: [{ id: 'starter', name: '创作入门', description: '500 积分', price: '29.00', currency: 'CNY', points: 500, duration_days: 30 }] }
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
});
