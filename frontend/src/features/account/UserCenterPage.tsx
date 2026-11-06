import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, KeyRound, LoaderCircle, ShieldCheck, UserRound, UsersRound } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { DEFAULT_CLIENT_CONFIG } from '../../api/clientConfig';
import { t } from '../../i18n';
import { hasPermission } from './permissions';


interface UserRecord {
  user_id: string;
  username: string;
  display_name?: string | null;
  email?: string | null;
  phone?: string | null;
  role: 'admin' | 'user';
  roles: string[];
  permissions: string[];
  status: 'active' | 'suspended' | 'deleted';
  must_change_password: boolean;
}

interface CenterResponse {
  user: UserRecord;
  membership: null | {
    plan_name: string;
    status: string;
    expires_at: string;
  };
}

interface RoleInfo {
  role: string;
  label: string;
  description: string;
  permissions: string[];
}

interface AdminUsersResponse {
  items: UserRecord[];
  total: number;
}

interface McpToken {
  id: string;
  label: string;
  hint: string;
  created_at: string | null;
  last_used_at: string | null;
}


const ROLE_NAMES: Record<string, string> = {
  super_admin: '超级管理员', ops: '运维', finance: '财务', support: '客服', auditor: '审计',
};


export function UserCenterPage({
  onBack,
  onUserChange,
  passwordMinLength = DEFAULT_CLIENT_CONFIG.passwordMinLength,
}: {
  onBack: () => void;
  onUserChange?: (user: UserRecord) => void;
  /** Shortest password the server accepts; sent with the session. */
  passwordMinLength?: number;
}) {
  const [center, setCenter] = useState<CenterResponse | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [roleCatalog, setRoleCatalog] = useState<RoleInfo[]>([]);
  const [displayName, setDisplayName] = useState('');
  const [phone, setPhone] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [confirmingDelete, setConfirmingDelete] = useState('');
  const [notice, setNotice] = useState('');
  // MCP tokens let an external agent (Claude Code, etc.) work on this user's projects through /mcp.
  const [mcpTokens, setMcpTokens] = useState<McpToken[]>([]);
  const [mcpLabel, setMcpLabel] = useState('');
  const [issuedToken, setIssuedToken] = useState('');

  const loadMcpTokens = useCallback(async () => {
    try {
      const data = await apiRequest<{ items?: McpToken[] }>('/api/mcp/tokens');
      setMcpTokens(Array.isArray(data.items) ? data.items : []);
    } catch {
      setMcpTokens([]);
    }
  }, []);

  const issueMcpToken = useCallback(async () => {
    setBusy('mcp');
    setError('');
    try {
      const created = await apiRequest<McpToken & { token: string }>('/api/mcp/tokens', { method: 'POST', body: JSON.stringify({ label: mcpLabel.trim() }) });
      setIssuedToken(created.token);
      setMcpLabel('');
      await loadMcpTokens();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'MCP 令牌创建失败');
    } finally {
      setBusy('');
    }
  }, [loadMcpTokens, mcpLabel]);

  const revokeMcpToken = useCallback(async (token: McpToken) => {
    setBusy(`mcp:${token.id}`);
    try {
      await apiRequest(`/api/mcp/tokens/${token.id}`, { method: 'DELETE' });
      await loadMcpTokens();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'MCP 令牌撤销失败');
    } finally {
      setBusy('');
    }
  }, [loadMcpTokens]);

  const load = useCallback(async () => {
    setError('');
    try {
      const data = await apiRequest<CenterResponse>('/api/users/me');
      void loadMcpTokens();
      setCenter(data);
      onUserChange?.(data.user);
      setDisplayName(data.user.display_name || '');
      setPhone(data.user.phone || '');
      if (hasPermission(data.user, 'user:read') && !data.user.must_change_password) {
        const [result, roles] = await Promise.all([
          apiRequest<AdminUsersResponse>('/api/admin/users?page=1&page_size=50'),
          apiRequest<{ items: RoleInfo[] }>('/api/admin/roles'),
        ]);
        setUsers(Array.isArray(result.items) ? result.items : []);
        setRoleCatalog(Array.isArray(roles.items) ? roles.items : []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户中心加载失败');
    }
  }, [onUserChange, loadMcpTokens]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const saveProfile = async () => {
    setBusy('profile');
    setError('');
    setNotice('');
    try {
      await apiRequest('/api/users/me', {
        method: 'PATCH',
        body: JSON.stringify({ display_name: displayName, phone }),
      });
      setNotice(t('个人资料已保存'));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '资料保存失败');
    } finally {
      setBusy('');
    }
  };

  const changePassword = async () => {
    setBusy('password');
    setError('');
    setNotice('');
    try {
      await apiRequest('/api/users/me/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setCurrentPassword('');
      setNewPassword('');
      setNotice(t('密码已更新，一次性管理员凭据已失效'));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '密码更新失败');
    } finally {
      setBusy('');
    }
  };

  const deleteUser = async (target: UserRecord) => {
    setBusy(target.user_id);
    setError('');
    try {
      await apiRequest(`/api/admin/users/${target.user_id}`, { method: 'DELETE' });
      setConfirmingDelete('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除账号失败');
    } finally {
      setBusy('');
    }
  };

  const updateUser = async (target: UserRecord, patch: Pick<UserRecord, 'status'>) => {
    setBusy(target.user_id);
    setError('');
    try {
      await apiRequest(`/api/admin/users/${target.user_id}`, {
        method: 'PATCH', body: JSON.stringify(patch),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户状态更新失败');
    } finally {
      setBusy('');
    }
  };

  const toggleRole = async (target: UserRecord, role: string, granted: boolean) => {
    setBusy(target.user_id);
    setError('');
    try {
      const roles = granted ? [...target.roles, role] : target.roles.filter(item => item !== role);
      await apiRequest(`/api/admin/users/${target.user_id}/roles`, {
        method: 'PUT', body: JSON.stringify({ roles }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('角色更新失败'));
    } finally {
      setBusy('');
    }
  };

  const canAssignRoles = hasPermission(center?.user, 'role:assign') && !center?.user.must_change_password;
  const canManageUsers = hasPermission(center?.user, 'user:manage') && !center?.user.must_change_password;

  if (!center) {
    return <main className="portal-page"><div className="empty-library"><LoaderCircle className="spin" /> {t('正在加载用户中心…')}</div>{error && <div className="inline-error">{error}</div>}</main>;
  }

  return (
    <main className="portal-page">
      <header className="portal-header">
        <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> {t('返回创作台')}</button>
        <div><span className="eyebrow">ACCOUNT & ACCESS</span><h1>{t('用户中心')}</h1><p>{t('管理身份、资料、密码、会员和平台访问权限。')}</p></div>
        <UserRound size={34} className="portal-mark" />
      </header>

      {center.user.must_change_password && (
        <div className="account-warning"><KeyRound size={18} /><div><strong>{t('首次登录必须修改密码')}</strong><span>{t('当前为一次性引导凭据，改密后本地临时凭据文件会删除。')}</span></div></div>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="command-result"><ShieldCheck size={16} /> {notice}</div>}

      <div className="account-grid">
        <section className="account-card identity-card">
          <div className="identity-avatar">{center.user.username.slice(0, 1).toUpperCase()}</div>
          <div>{(center.user.roles?.length ? center.user.roles : ['']).map(role => (
            <span className="role-pill" key={role}>{role ? t(ROLE_NAMES[role] ?? role) : t('成员')}</span>
          ))}<h2>{center.user.display_name || center.user.username}</h2><p>{center.user.email || center.user.phone}</p></div>
          <dl><div><dt>{t('账号状态')}</dt><dd>{center.user.status === 'active' ? t('正常') : t('已停用')}</dd></div><div><dt>{t('会员')}</dt><dd>{center.membership?.plan_name || '未开通'}</dd></div></dl>
        </section>

        <section className="account-card account-form">
          <h2>{t('个人资料')}</h2>
          <label>{t('显示名称')}<input value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>
          <label>{t('手机号')}<input value={phone} onChange={event => setPhone(event.target.value)} placeholder={t('可选')} /></label>
          <button type="button" className="primary-action" onClick={() => void saveProfile()} disabled={busy === 'profile'}>{t('保存资料')}</button>
        </section>

        <section className="account-card account-form">
          <h2>{t('登录安全')}</h2>
          <label>{t('当前密码')}<input type="password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} /></label>
          <label>{t('新密码')}<input type="password" minLength={passwordMinLength} value={newPassword} onChange={event => setNewPassword(event.target.value)} placeholder={`至少 ${passwordMinLength} 位`} /></label>
          <button type="button" className="primary-action" onClick={() => void changePassword()} disabled={!currentPassword || newPassword.length < passwordMinLength || busy === 'password'}>{t('更新密码')}</button>
        </section>

        <section className="account-card account-form" aria-label={t('MCP 令牌')}>
          <h2>{t('MCP 令牌')}</h2>
          <p className="account-help">{t('外部 Agent（如 Claude Code）凭令牌通过')} <code>POST /mcp</code> {t('使用与站内工具助手相同的工具；付费工具仍需显式确认。令牌只显示一次。')}</p>
          {issuedToken && <div className="command-result" role="status"><KeyRound size={16} /> {t('新令牌（请立即复制）：')}<code>{issuedToken}</code></div>}
          {issuedToken && (
            <div className="command-result" role="note">
              {t('接入 Claude Code：')}<code>{`claude mcp add --transport http short-drama ${apiUrl('/mcp')} --header "Authorization: Bearer ${issuedToken}"`}</code>
              <small>{t('其他客户端见项目里的 agent-kit/README.md')}</small>
            </div>
          )}
          <ul className="mcp-token-list">
            {mcpTokens.map(token => (
              <li key={token.id}>
                <strong>{token.label}</strong><code>{token.hint}</code>
                <small>{token.last_used_at ? `最近使用 ${token.last_used_at.slice(0, 16).replace('T', ' ')}` : '尚未使用'}</small>
                <button type="button" aria-label={`撤销令牌 ${token.label}`} disabled={busy === `mcp:${token.id}`} onClick={() => void revokeMcpToken(token)}>{t('撤销')}</button>
              </li>
            ))}
          </ul>
          <label>{t('令牌名称')}<input value={mcpLabel} onChange={event => setMcpLabel(event.target.value)} placeholder={t('如 Claude Code')} /></label>
          <button type="button" className="primary-action" onClick={() => void issueMcpToken()} disabled={busy === 'mcp'}>{t('签发 MCP 令牌')}</button>
        </section>
      </div>

      {hasPermission(center.user, 'user:read') && (
        <section className="user-management">
          <div className="section-title"><UsersRound size={20} /><div><h2>{t('用户管理')}</h2><p>共 {users.length} 个账号；系统会保护最后一个有效管理员。</p></div></div>
          <div className="user-table" role="table">
            <div className="user-row user-row-head" role="row"><span>{t('用户')}</span><span>{t('角色')}</span><span>{t('状态')}</span></div>
            {users.map(user => (
              <div className="user-row" role="row" key={user.user_id}>
                <div><strong>{user.display_name || user.username}</strong><small>{user.email || user.phone}</small></div>
                <div className="user-roles" role="group" aria-label={`${user.username} 角色`}>
                  {roleCatalog.map(item => (
                    <label key={item.role} title={item.description}>
                      <input
                        type="checkbox"
                        checked={user.roles.includes(item.role)}
                        disabled={!canAssignRoles || busy === user.user_id}
                        onChange={event => void toggleRole(user, item.role, event.target.checked)}
                      />
                      {t(ROLE_NAMES[item.role] ?? item.label)}
                    </label>
                  ))}
                </div>
                {user.status === 'deleted' ? <span className="status-control deleted">{t('已删除')}</span> : (
                  <>
                <button type="button" className={`status-control ${user.status}`} disabled={!canManageUsers || (user.roles.length > 0 && !canAssignRoles) || busy === user.user_id} onClick={() => void updateUser(user, { status: user.status === 'active' ? 'suspended' : 'active' })}>{user.status === 'active' ? t('正常') : t('已停用')}</button>
                    {confirmingDelete === user.user_id ? (
                      <span className="account-delete-confirm">
                        <span>{t('删除后无法恢复。财务记录会保留，登录信息会清除。')}</span>
                        <button type="button" className="status-control suspended" disabled={busy === user.user_id} onClick={() => void deleteUser(user)}>{t('确认删除')}</button>
                        <button type="button" className="status-control" onClick={() => setConfirmingDelete('')}>{t('取消')}</button>
                      </span>
                    ) : (
                      <button type="button" className="status-control" disabled={!canManageUsers || (user.roles.length > 0 && !canAssignRoles) || user.user_id === center.user.user_id} onClick={() => setConfirmingDelete(user.user_id)}>{t('删除')}</button>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
