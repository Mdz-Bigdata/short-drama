// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserCenterPage } from './UserCenterPage';


describe('UserCenterPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows identity, role, membership, profile and password controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          user_id: 'u-1', username: 'admin', email: 'admin@short-drama.local',
          phone: null, role: 'admin', roles: ['super_admin'], permissions: ['role:assign', 'user:read', 'user:manage'], status: 'active', must_change_password: true,
        },
        membership: null,
      }),
    } as Response);
    render(<UserCenterPage onBack={() => undefined} />);

    expect(await screen.findByText('admin@short-drama.local')).toBeTruthy();
    expect(screen.getByText('超级管理员')).toBeTruthy();
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

  it('copies the one-time token, and selects it when the clipboard is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/mcp/tokens') && init?.method === 'POST') {
        return { ok: true, json: async () => ({ id: 'tok-1', label: 'x', hint: '****ab12', created_at: null, last_used_at: null, token: 'mcp_clear_secret_ab12' }) } as Response;
      }
      if (url.endsWith('/api/mcp/tokens')) return { ok: true, json: async () => ({ items: [] }) } as Response;
      return { ok: true, json: async () => ({ user: { user_id: 'u-1', username: 'me', email: 'me@x', phone: null, role: 'user', status: 'active', must_change_password: false }, membership: null }) } as Response;
    });
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('denied'));
    render(<UserCenterPage onBack={() => undefined} />);

    const card = await screen.findByRole('region', { name: 'MCP 令牌' });
    await user.click(within(card).getByRole('button', { name: '签发 MCP 令牌' }));
    await user.click(await within(card).findByRole('button', { name: '复制' }));
    expect(writeText).toHaveBeenCalledWith('mcp_clear_secret_ab12');
    await user.click(await within(card).findByRole('button', { name: '已复制' }));
    await waitFor(() => expect(window.getSelection()?.toString()).toBe('mcp_clear_secret_ab12'));
  });

  it('offers a way back and a retry when the page cannot load', async () => {
    const profile = { user: { user_id: 'u-1', username: 'me', email: 'me@x', phone: null, role: 'user', status: 'active', must_change_password: false }, membership: null };
    let down = true;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/api/mcp/tokens')) return { ok: true, json: async () => ({ items: [] }) } as Response;
      if (down) return { ok: false, status: 503, json: async () => ({ detail: '服务暂时不可用' }) } as Response;
      return { ok: true, json: async () => profile } as Response;
    });
    const onBack = vi.fn();
    render(<UserCenterPage onBack={onBack} />);

    const failure = await screen.findByRole('alert');
    expect(failure.textContent).toContain('服务暂时不可用');
    expect(screen.queryByText('正在加载用户中心…')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /返回创作台/ }));
    expect(onBack).toHaveBeenCalledTimes(1);

    down = false;
    await userEvent.click(within(failure).getByRole('button', { name: '重试' }));
    expect(await screen.findByText('me@x')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps a half-typed display name when the password change reloads the page', async () => {
    const profile = { user: { user_id: 'u-1', username: 'me', display_name: '旧名字', email: 'me@x', phone: null, role: 'user', status: 'active', must_change_password: false }, membership: null };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/api/mcp/tokens')) return { ok: true, json: async () => ({ items: [] }) } as Response;
      return { ok: true, json: async () => profile } as Response;
    });
    const user = userEvent.setup();
    render(<UserCenterPage onBack={() => undefined} passwordMinLength={8} />);
    const name = await screen.findByLabelText('显示名称') as HTMLInputElement;
    expect(name.value).toBe('旧名字');
    await user.clear(name);
    await user.type(name, '新名字');
    await user.type(screen.getByLabelText('当前密码'), 'old-password');
    await user.type(screen.getByLabelText('新密码'), 'new-password-1');
    await user.click(screen.getByRole('button', { name: '更新密码' }));
    expect(await screen.findByText('密码已更新，一次性管理员凭据已失效')).toBeTruthy();
    expect(name.value).toBe('新名字');
  });

  it('puts focus on Cancel when deleting asks for confirmation', async () => {
    const me = { user_id: 'me', username: 'me', email: 'me@x', phone: null, role: 'admin', roles: [], permissions: ['user:read', 'user:manage'], status: 'active', must_change_password: false };
    const customer = { user_id: 'c1', username: 'customer', email: 'c@x', phone: null, role: 'user', roles: [], permissions: [], status: 'active', must_change_password: false };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
      if (url.includes('/api/admin/users')) return json({ items: [customer], total: 1 });
      if (url.includes('/api/admin/roles')) return json({ items: [] });
      if (url.includes('/api/mcp/tokens')) return json({ items: [] });
      return json({ user: me, membership: null });
    });
    render(<UserCenterPage onBack={() => undefined} />);
    const row = (await screen.findByText('customer')).closest('[role="row"]') as HTMLElement;
    // Status and its actions share one cell, so the row has the three cells its grid lays out.
    expect(row.children).toHaveLength(3);
    await userEvent.click(within(row).getByRole('button', { name: '删除' }));
    expect(document.activeElement).toBe(within(row).getByRole('button', { name: '取消' }));
  });

  describe('role management', () => {
    const catalog = [
      { role: 'super_admin', label: '超级管理员', description: '全部权限', permissions: [] },
      { role: 'finance', label: '财务', description: '财务', permissions: [] },
    ];
    const me = (permissions: string[], roles: string[]) => ({
      user_id: 'me', username: 'me', email: 'me@x', phone: null, role: 'user', roles, permissions,
      status: 'active', must_change_password: false,
    });
    const customer = { user_id: 'c1', username: 'customer', email: 'c@x', phone: null, role: 'user', roles: [], permissions: [], status: 'active', must_change_password: false };
    const staff = { ...customer, user_id: 's1', username: 'staff', email: 's@x', roles: ['finance'] };

    function serve(user: ReturnType<typeof me>) {
      const puts: Array<[string, unknown]> = [];
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
        const url = String(input);
        const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
        if (init?.method === 'PUT') {
          puts.push([url, JSON.parse(String(init.body))]);
          return json({ user: customer });
        }
        if (url.includes('/api/admin/users')) return json({ items: [customer, staff], total: 2 });
        if (url.includes('/api/admin/roles')) return json({ items: catalog });
        if (url.includes('/api/mcp/tokens')) return json({ items: [], endpoint: '/mcp' });
        return json({ user, membership: null });
      });
      return puts;
    }

    it('lets someone with role:assign grant a role', async () => {
      const puts = serve(me(['role:assign', 'user:read', 'user:manage'], ['super_admin']));
      render(<UserCenterPage onBack={() => undefined} />);
      const group = await screen.findByRole('group', { name: 'customer 角色' });
      await userEvent.click(within(group).getByRole('checkbox', { name: '财务' }));
      await waitFor(() => expect(puts).toHaveLength(1));
      expect(puts[0][0]).toContain('/api/admin/users/c1/roles');
      expect(puts[0][1]).toEqual({ roles: ['finance'] });
    });

    it('shows support the roles but not how to change them, and lets them suspend only customers', async () => {
      serve(me(['user:read', 'user:manage'], ['support']));
      render(<UserCenterPage onBack={() => undefined} />);
      const group = await screen.findByRole('group', { name: 'customer 角色' });
      expect((within(group).getByRole('checkbox', { name: '财务' }) as HTMLInputElement).disabled).toBe(true);
      const rows = screen.getAllByRole('row').filter(row => row.querySelector('.status-control'));
      const button = (name: string) => rows.find(row => row.textContent?.includes(name))!.querySelector('.status-control') as HTMLButtonElement;
      expect(button('customer').disabled).toBe(false);
      expect(button('staff').disabled).toBe(true);
    });

    it('shows no user management to someone without user:read', async () => {
      serve(me([], []));
      render(<UserCenterPage onBack={() => undefined} />);
      expect(await screen.findByText('me@x')).toBeTruthy();
      expect(screen.queryByText('用户管理')).toBeNull();
    });
  });
});
