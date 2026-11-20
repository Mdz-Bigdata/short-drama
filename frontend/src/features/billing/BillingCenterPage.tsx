import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, Coins, CreditCard, LoaderCircle, ReceiptText, ShieldCheck } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { money, when } from '../finance/financeFormat';
import { PaymentDialog } from './PaymentDialog';
import { PriceListSection } from './PriceListSection';
import { channelLabel, type PaymentChannelName } from './paymentChannels';


interface Plan {
  id: string;
  name: string;
  description: string;
  price: string;
  currency: string;
  points: number;
  duration_days: number;
}

interface Order {
  id: string;
  plan_id: string;
  provider: string;
  amount: string;
  currency: string;
  status: string;
  created_at: string;
}

interface Wallet {
  available?: string | number;
  held?: string | number;
  frozen?: string | number;
  charging?: boolean;
  points: string;
  money: Record<string, string>;
  entries: Array<{ id: string; direction: string; amount: string; currency: string; category: string; created_at: string }>;
}


const orderStatusLabel = (status: string) => {
  if (status === 'paid') return t('已支付');
  if (status === 'closed') return t('已关闭');
  if (status === 'partially_refunded') return t('部分退款');
  if (status === 'refunded') return t('已全额退款');
  return t('待支付');
};


export function BillingCenterPage({ onBack, inProject = false }: { onBack: () => void; inProject?: boolean }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [sandboxEnabled, setSandboxEnabled] = useState(false);
  const [channels, setChannels] = useState<PaymentChannelName[]>([]);
  const [paying, setPaying] = useState<{ plan?: Plan; order?: Order; provider: PaymentChannelName } | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [wallet, setWallet] = useState<Wallet>({ points: '0', money: {}, entries: [] });
  const [loading, setLoading] = useState(true);
  // Until one load works the page has no wallet or plans to show, only the reason and a retry.
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = async () => {
    setError('');
    try {
      const [planData, walletData, orderData] = await Promise.all([
        apiRequest<{ items: Plan[]; sandbox_enabled?: boolean; channels?: PaymentChannelName[] }>('/api/billing/plans'),
        apiRequest<Wallet>('/api/billing/wallet'),
        apiRequest<{ items: Order[] }>('/api/billing/orders?page=1&page_size=50'),
      ]);
      setPlans(planData.items);
      setSandboxEnabled(Boolean(planData.sandbox_enabled));
      setChannels(planData.channels ?? []);
      setWallet(walletData);
      setOrders(orderData.items);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('支付中心加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, []);

  const createOrderFor = useCallback((plan: Plan) => async () => {
    const order = await apiRequest<Order>('/api/billing/orders', {
      method: 'POST',
      body: JSON.stringify({ plan_id: plan.id, idempotency_key: `web-${plan.id}-${crypto.randomUUID()}` }),
    });
    return order.id;
  }, []);
  const reload = useCallback(() => { void load(); }, []);
  const retry = () => {
    setLoading(true);
    void load();
  };
  const closePaying = () => {
    setPaying(null);
    void load();
  };

  const buySandbox = async (plan: Plan) => {
    setBusy(plan.id);
    setError('');
    setNotice('');
    try {
      const order = await apiRequest<Order>('/api/billing/orders', {
        method: 'POST',
        body: JSON.stringify({
          plan_id: plan.id,
          provider: 'sandbox',
          idempotency_key: `web-${plan.id}-${crypto.randomUUID()}`,
        }),
      });
      await apiRequest(`/api/billing/orders/${order.id}/sandbox-confirm`, { method: 'POST' });
      setNotice(t('{0}沙箱订单已完成，积分已通过追加式账本入账。', [plan.name]));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('沙箱订单创建失败'));
    } finally {
      setBusy('');
    }
  };

  return (
    <main className="portal-page">
      <header className="portal-header">
        <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> {t('返回创作台')}</button>
        <div><span className="eyebrow">MEMBERSHIP & BILLING</span><h1>{t('会员与支付中心')}</h1><p>{t('订单、积分和资金流水均使用 PostgreSQL 追加式账本与幂等处理。')}</p></div>
        <CreditCard size={34} className="portal-mark" />
      </header>

      {loaded && <div className="billing-safety"><ShieldCheck size={18} /><span>{channels.length > 0
        ? t('付款在支付宝或微信内完成，本站不接触你的支付账号。')
        : sandboxEnabled
          ? t('当前开放沙箱支付；微信/支付宝在商户证书和签名密钥配置前不会发起真实扣款。')
          : t('在线支付暂未开放，暂时无法购买。')}</span></div>}
      {error && loaded && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="command-result" role="status"><CheckCircle2 size={16} /> {notice}</div>}

      {loading ? <div className="empty-library" role="status"><LoaderCircle className="spin" /> {t('正在加载支付中心…')}</div> : !loaded ? (
        <div className="empty-library" role="alert">
          <strong>{t('支付中心没有加载出来')}</strong>
          <span>{error}</span>
          <button type="button" className="secondary-action" onClick={retry}>{t('重试')}</button>
        </div>
      ) : (
        <>
          <section className="wallet-hero">
            <div><Coins size={25} /><span>{t('可用创作积分')}</span><strong>{wallet.charging ? Number(wallet.available ?? 0) : wallet.points}</strong>{Number(wallet.held ?? 0) > 0 && <small>{t('其中 {0} 积分正在使用', [String(Number(wallet.held))])}</small>}{Number(wallet.frozen ?? 0) > 0 && <small>{t('另有 {0} 积分在退款审核中，暂不可用', [String(Number(wallet.frozen))])}</small>}</div>
            <div><ReceiptText size={25} /><span>{t('账本记录')}</span><strong>{wallet.entries.length}</strong></div>
            <div><CreditCard size={25} /><span>{t('订单数量')}</span><strong>{orders.length}</strong></div>
          </section>

          <section className="billing-section">
            <div className="section-title"><div><h2>{t('会员计划')}</h2>{sandboxEnabled && <p>{t('下列按钮仅执行本地沙箱确认，不会调用外部支付服务。')}</p>}</div></div>
            <div className="plan-grid">
              {plans.length === 0 && <p>{t('暂时没有可购买的会员计划')}</p>}
              {plans.map(plan => (
                <article className="plan-card" key={plan.id}>
                  <span>{t('{0} 天', [plan.duration_days])}</span><h2>{plan.name}</h2><p>{plan.description}</p>
                  <div className="plan-price"><strong>{money(plan.price, plan.currency)}</strong><small> {t('/ 期')}</small></div>
                  <ul><li><CheckCircle2 size={15} /> {t('{0} 创作积分', [plan.points])}</li><li><CheckCircle2 size={15} /> {t('幂等订单与追加式流水')}</li></ul>
                  {channels.map(channel => (
                    <button type="button" className="primary-action" key={channel} onClick={() => setPaying({ plan, provider: channel })}><CreditCard size={16} /> {channelLabel(channel)}</button>
                  ))}
                  {(sandboxEnabled || channels.length === 0) && (
                    <button type="button" className={channels.length > 0 ? 'secondary-action' : 'primary-action'} onClick={() => void buySandbox(plan)} disabled={!sandboxEnabled || busy === plan.id}>{busy === plan.id ? <LoaderCircle className="spin" size={16} /> : <CreditCard size={16} />} {sandboxEnabled ? t('沙箱购买 {0}', [plan.name]) : t('暂未开放购买')}</button>
                  )}
                </article>
              ))}
            </div>
          </section>

          <section className="billing-section">
            <div className="section-title"><ReceiptText size={20} /><div><h2>{t('订单记录')}</h2><p>{t('金额和币种由服务端会员计划锁定，浏览器不能覆盖。')}</p></div></div>
            <div className="order-list">
              {orders.length === 0 ? <p>{t('暂无订单')}</p> : orders.map(order => (
                <div className="order-row" key={order.id}><div><strong>{order.plan_id}</strong><small>{when(order.created_at)}</small></div><span>{channelLabel(order.provider)}</span><span>{money(order.amount, order.currency)}</span>
                  {/* Status and its action share the last column; a fifth cell would wrap under the plan name. */}
                  <div><span className={`order-status ${order.status}`}>{orderStatusLabel(order.status)}</span>{order.status === 'pending' && order.provider !== 'sandbox' && channels.length > 0 && (
                    <button type="button" className="secondary-action" onClick={() => setPaying({ order, provider: channels.includes(order.provider as PaymentChannelName) ? order.provider as PaymentChannelName : channels[0] })}>{t('继续支付')}</button>
                  )}</div></div>
              ))}
            </div>
          </section>

          <PriceListSection />
        </>
      )}
      {paying && (
        <PaymentDialog
          title={paying.plan?.name ?? paying.order?.plan_id ?? ''}
          amount={paying.plan?.price ?? paying.order?.amount ?? ''}
          points={paying.plan?.points ?? plans.find(plan => plan.id === paying.order?.plan_id)?.points}
          channels={channels}
          provider={paying.provider}
          orderId={paying.order?.id}
          createOrder={paying.plan ? createOrderFor(paying.plan) : undefined}
          onClose={closePaying}
          onPaid={reload}
          onBackToProject={inProject ? onBack : undefined}
        />
      )}
    </main>
  );
}
