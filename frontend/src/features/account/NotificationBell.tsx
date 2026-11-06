import { useCallback, useEffect, useState } from 'react';
import { Bell } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';


const POLL_MS = 60000;

interface Notice {
  id: string;
  kind: string;
  data: { plan_name?: string; points?: number | string; amount_minor?: number; days?: number };
  read: boolean;
  created_at: string;
}
interface Inbox { unread: number; to_do: Record<string, number>; items: Notice[] }

const yuan = (minor?: number) => `¥${(Number(minor ?? 0) / 100).toFixed(2)}`;

function noticeText(notice: Notice): string {
  const { plan_name: plan = '', points = 0, amount_minor: amount, days } = notice.data;
  switch (notice.kind) {
    case 'order_paid': return t('{0}支付成功，{1} 积分已到账。', [plan, String(Number(points))]);
    case 'refund_succeeded': return t('退款 {0} 已原路退回。', [yuan(amount)]);
    case 'duplicate_refunded': return t('你多付的 {0} 已自动退回。', [yuan(amount)]);
    case 'membership_expiring': return days === 1 ? t('{0}明天到期，到期后剩余积分作废。', [plan]) : t('{0}将在 7 天内到期，到期后剩余积分作废。', [plan]);
    case 'membership_expired': return t('{0}已到期，已回到免费版。', [plan]);
    default: return notice.kind;
  }
}

const TO_DO_TEXT: Record<string, string> = {
  refunds_to_decide: '{0} 笔退款等你审批',
  adjustments_to_decide: '{0} 笔积分调整等你审批',
  critical_differences: '{0} 条严重对账差异未处理',
  payment_alerts: '近 7 天有 {0} 条支付告警',
};

/** Only the money-related ones lead anywhere yet, and they all lead to the same two pages. */
export function NotificationBell({ onOpenBilling, onOpenFinance }: { onOpenBilling: () => void; onOpenFinance: () => void }) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setInbox(await apiRequest<Inbox>('/api/notifications'));
    } catch {
      // A bell that could not ring this time. The next poll tries again.
    }
  }, []);

  useEffect(() => {
    const first = window.setTimeout(() => { void load(); }, 0);
    const poll = window.setInterval(() => { if (document.visibilityState === 'visible') void load(); }, POLL_MS);
    return () => { window.clearTimeout(first); window.clearInterval(poll); };
  }, [load]);

  const toDo = Object.entries(inbox?.to_do ?? {}).filter(([, count]) => count > 0);
  const badge = (inbox?.unread ?? 0) + toDo.reduce((sum, [, count]) => sum + count, 0);

  const toggle = () => {
    const opening = !open;
    setOpen(opening);
    if (opening) void load();
  };
  const openNotice = async (notice: Notice) => {
    setOpen(false);
    onOpenBilling();
    if (!notice.read) {
      await apiRequest(`/api/notifications/${notice.id}/read`, { method: 'POST' }).catch(() => undefined);
      void load();
    }
  };
  const readAll = async () => {
    await apiRequest('/api/notifications/read-all', { method: 'POST' }).catch(() => undefined);
    void load();
  };

  return (
    <div className="notification-bell">
      <button type="button" className="notification-bell__button" aria-label={badge ? t('通知，{0} 条未读', [String(badge)]) : t('通知')} aria-expanded={open} onClick={toggle}>
        <Bell size={17} />
        {badge > 0 && <span className="notification-bell__badge">{badge > 99 ? '99+' : badge}</span>}
      </button>
      {open && (
        <div className="notification-bell__panel">
          <header>
            <strong>{t('通知')}</strong>
            {(inbox?.unread ?? 0) > 0 && <button type="button" onClick={() => void readAll()}>{t('全部已读')}</button>}
          </header>
          {toDo.map(([key, count]) => (
            <button type="button" key={key} className="notification-bell__item is-todo" onClick={() => { setOpen(false); onOpenFinance(); }}>
              {t(TO_DO_TEXT[key] ?? key, [String(count)])}
            </button>
          ))}
          {inbox?.items.map(notice => (
            <button type="button" key={notice.id} className={`notification-bell__item${notice.read ? '' : ' is-unread'}`} onClick={() => void openNotice(notice)}>
              <span>{noticeText(notice)}</span>
              <small>{new Date(notice.created_at).toLocaleString('zh-CN', { hour12: false })}</small>
            </button>
          ))}
          {!toDo.length && !inbox?.items.length && <p>{t('没有新通知')}</p>}
        </div>
      )}
    </div>
  );
}
