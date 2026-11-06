import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, LoaderCircle, RefreshCw, X } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';

import { ApiError, apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { channelLabel, type PaymentChannelName } from './paymentChannels';


interface PayState {
  id: string;
  status: string;
  attempt: { provider: PaymentChannelName; qr_code: string; expires_at: string } | null;
}

const POLL_MS = 3000;
const RETRY_IN_FLIGHT_MS = 1500;

const secondsUntil = (moment: string) => Math.max(0, Math.floor((new Date(moment).getTime() - Date.now()) / 1000));
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;


/**
 * Pays one order by QR code. The order is only paid once the server says so: nothing here can claim a payment.
 * Closing the dialog leaves the order open, because someone may be in the middle of paying on their phone.
 */
export function PaymentDialog({ title, amount, points, channels, provider, orderId, createOrder, onClose, onPaid, onBackToProject }: {
  title: string;
  amount: string;
  points?: number;
  channels: PaymentChannelName[];
  provider: PaymentChannelName;
  orderId?: string;
  createOrder?: () => Promise<string>;
  onClose: () => void;
  onPaid: () => void;
  onBackToProject?: () => void;
}) {
  const orderRef = useRef(orderId ?? '');
  const closedRef = useRef(false);
  const [state, setState] = useState<PayState | null>(null);
  const [chosen, setChosen] = useState(provider);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [left, setLeft] = useState(0);
  const [outcome, setOutcome] = useState<'open' | 'paid' | 'closed'>('open');
  const paidRef = useRef(false);

  const take = useCallback((next: PayState) => {
    if (closedRef.current) return;
    setState(next);
    if (next.attempt) setLeft(secondsUntil(next.attempt.expires_at));
    if (next.status === 'paid' && !paidRef.current) {
      paidRef.current = true;
      setOutcome('paid');
      onPaid();
    } else if (next.status === 'closed') {
      setOutcome('closed');
    }
  }, [onPaid]);

  const show = useCallback(async (channel: PaymentChannelName) => {
    setChosen(channel);
    setBusy(true);
    setError('');
    try {
      if (!orderRef.current && createOrder) orderRef.current = await createOrder();
      const request = () => apiRequest<PayState>(`/api/billing/orders/${orderRef.current}/pay`, {
        method: 'POST', body: JSON.stringify({ provider: channel }),
      });
      try {
        take(await request());
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 409) throw err;
        await new Promise(resolve => window.setTimeout(resolve, RETRY_IN_FLIGHT_MS));
        take(await request());
      }
    } catch (err) {
      if (!closedRef.current) {
        setState(previous => previous && { ...previous, attempt: null });
        setError(err instanceof Error ? err.message : t('付款码生成失败'));
      }
    } finally {
      if (!closedRef.current) setBusy(false);
    }
  }, [createOrder, take]);

  useEffect(() => {
    closedRef.current = false;
    const handle = window.setTimeout(() => { void show(provider); }, 0);
    return () => {
      closedRef.current = true;
      window.clearTimeout(handle);
    };
    // Opens once with the channel it was asked for. Switching goes through the buttons.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (outcome !== 'open') return undefined;
    const poll = window.setInterval(() => {
      if (!orderRef.current) return;
      apiRequest<PayState>(`/api/billing/orders/${orderRef.current}`).then(take).catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(poll);
  }, [outcome, take]);

  const expiresAt = state?.attempt?.expires_at;
  useEffect(() => {
    if (!expiresAt) return undefined;
    const tick = window.setInterval(() => setLeft(secondsUntil(expiresAt)), 1000);
    return () => window.clearInterval(tick);
  }, [expiresAt]);

  const cancel = async () => {
    setBusy(true);
    setError('');
    try {
      take(await apiRequest<PayState>(`/api/billing/orders/${orderRef.current}/cancel`, { method: 'POST' }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('取消失败'));
    } finally {
      setBusy(false);
    }
  };

  const code = outcome === 'open' && left > 0 ? state?.attempt?.qr_code : undefined;
  const waitingForCode = busy && !code;

  return (
    <div className="pay-dialog" role="dialog" aria-modal="true" aria-label={t('扫码支付')}>
      <div className="pay-dialog__panel">
        <header>
          <div><h2>{title}</h2><strong>¥{amount}</strong></div>
          <button type="button" className="pay-dialog__close" aria-label={t('关闭')} onClick={onClose}><X size={18} /></button>
        </header>

        {outcome === 'paid' && (
          <div className="pay-dialog__done">
            <CheckCircle2 size={44} />
            <h3>{t('支付成功')}</h3>
            {points !== undefined && <p>{t('{0} 积分已到账', [String(points)])}</p>}
            {onBackToProject && <p>{t('生成不会自动继续，回到项目后点“继续”。')}</p>}
            {onBackToProject
              ? <button type="button" className="primary-action" onClick={onBackToProject}>{t('回到项目')}</button>
              : <button type="button" className="primary-action" onClick={onClose}>{t('完成')}</button>}
          </div>
        )}

        {outcome === 'closed' && (
          <div className="pay-dialog__done">
            <h3>{t('订单已取消')}</h3>
            <p>{t('如果你已经付款，金额会自动入账，不用重新购买。')}</p>
            <button type="button" className="secondary-action" onClick={onClose}>{t('关闭')}</button>
          </div>
        )}

        {outcome === 'open' && (
          <>
            {channels.length > 1 && (
              <div className="pay-dialog__channels" role="group" aria-label={t('支付方式')}>
                {channels.map(channel => (
                  <button
                    type="button" key={channel} aria-pressed={channel === chosen}
                    className={channel === chosen ? 'is-chosen' : ''} disabled={busy}
                    onClick={() => { if (channel !== chosen || !code) void show(channel); }}
                  >{channelLabel(channel)}</button>
                ))}
              </div>
            )}
            <div className="pay-dialog__code">
              {code && <QRCodeSVG value={code} size={208} level="M" marginSize={2} title={t('付款二维码')} />}
              {waitingForCode && <p><LoaderCircle className="spin" size={18} /> {t('正在生成付款码…')}</p>}
              {!code && !busy && !error && (
                <div className="pay-dialog__expired">
                  <p>{t('付款码已过期')}</p>
                  <button type="button" className="secondary-action" onClick={() => void show(chosen)}><RefreshCw size={15} /> {t('刷新付款码')}</button>
                </div>
              )}
              {!code && !busy && error && (
                <div className="pay-dialog__expired">
                  <button type="button" className="secondary-action" onClick={() => void show(chosen)}><RefreshCw size={15} /> {t('重试')}</button>
                </div>
              )}
            </div>
            {error && <div className="inline-error" role="alert">{error}</div>}
            {code && (
              <p className="pay-dialog__hint">
                {t('请用{0}扫码付款，{1} 后过期。付款后这里会自动更新。', [channelLabel(chosen), clock(left)])}
              </p>
            )}
            {state && (
              <button type="button" className="pay-dialog__cancel" disabled={busy} onClick={() => void cancel()}>{t('取消订单')}</button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
