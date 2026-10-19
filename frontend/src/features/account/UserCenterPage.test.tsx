// @vitest-environment jsdom
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

  it('issues an MCP token once, lists it masked and revokes it', async () => {
    let tokens: Array<{ id: string; label: string; hint: string; created_at: string | null; last_used_at: string | null }> = [];
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/mcp/tokens') && init?.method === 'POST') {
        calls.push(`POST ${JSON.parse(String(init.body)).label}`);
        tokens = [{ id: 'tok-1', label: 'Claude Code', hint: '****ab12', created_at: '2026-10-14T00:00:00', last_used_at: null }];
        return { ok: true, json: async () => ({ ...tokens[0], token: 'mcp_clear_secret_ab12' }) } as Response;
      }
      if (url.includes('/api/mcp/tokens/tok-1') && init?.method === 'DELETE') {
        calls.push('DELETE tok-1');
        tokens = [];
        return { ok: true, json: async () => ({ id: 'tok-1', revoked: true }) } as Response;
      }
      if (url.endsWith('/api/mcp/tokens')) return { ok: true, json: async () => ({ items: tokens, endpoint: '/mcp' }) } as Response;
      return { ok: true, json: async () => ({ user: { user_id: 'u-1', username: 'me', email: 'me@x', phone: null, role: 'user', status: 'active', must_change_password: false }, membership: null }) } as Response;
    });
    render(<UserCenterPage onBack={() => undefined} />);

    const card = await screen.findByRole('region', { name: 'MCP 令牌' });
    await userEvent.type(within(card).getByLabelText('令牌名称'), 'Claude Code');
    await userEvent.click(within(card).getByRole('button', { name: '签发 MCP 令牌' }));
    expect(await within(card).findByText('mcp_clear_secret_ab12')).toBeTruthy();
    expect(within(card).getByText('****ab12')).toBeTruthy();
    await userEvent.click(within(card).getByRole('button', { name: '撤销令牌 Claude Code' }));
    await waitFor(() => expect(within(card).queryByText('****ab12')).toBeNull());
    expect(calls).toEqual(['POST Claude Code', 'DELETE tok-1']);
  });
});
