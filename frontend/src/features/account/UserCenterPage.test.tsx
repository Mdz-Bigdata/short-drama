// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserCenterPage } from './UserCenterPage';


describe('UserCenterPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows identity, role, membership, profile and password controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          user_id: 'u-1', username: 'admin', email: 'admin@short-drama.local',
          phone: null, role: 'admin', status: 'active', must_change_password: true,
        },
        membership: null,
      }),
    } as Response);
    render(<UserCenterPage onBack={() => undefined} />);

    expect(await screen.findByText('admin@short-drama.local')).toBeTruthy();
    expect(screen.getByText('管理员')).toBeTruthy();
    expect(screen.getByText(/首次登录必须修改密码/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '保存资料' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '更新密码' })).toBeTruthy();
  });
});
