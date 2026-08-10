import { useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, Coins, CreditCard, LoaderCircle, ReceiptText, ShieldCheck } from 'lucide-react';

import { apiRequest } from '../../api/client';


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
  points: string;
  money: Record<string, string>;
  entries: Array<{ id: string; direction: string; amount: string; currency: string; category: string; created_at: string }>;
}


export function BillingCenterPage({ onBack }: { onBack: () => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [wallet, setWallet] = useState<Wallet>({ points: '0', money: {}, entries: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = async () => {
    setError('');
    try {
      const [planData, walletData, orderData] = await Promise.all([
        apiRequest<{ items: Plan[] }>('/api/billing/plans'),
        apiRequest<Wallet>('/api/billing/wallet'),
        apiRequest<{ items: Order[] }>('/api/billing/orders?page=1&page_size=50'),
      ]);
      setPlans(planData.items);
      setWallet(walletData);
      setOrders(orderData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '支付中心加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, []);

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
      setNotice(`${plan.name}沙箱订单已完成，积分已通过追加式账本入账。`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '沙箱订单创建失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <main className="portal-page">
      <header className="portal-header">
        <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> 返回创作台</button>
        <div><span className="eyebrow">MEMBERSHIP & BILLING</span><h1>会员与支付中心</h1><p>订单、积分和资金流水均使用 PostgreSQL 追加式账本与幂等处理。</p></div>
        <CreditCard size={34} className="portal-mark" />
      </header>

      <div className="billing-safety"><ShieldCheck size={18} /><span>当前开放沙箱支付；微信/支付宝在商户证书和签名密钥配置前不会发起真实扣款。</span></div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="command-result"><CheckCircle2 size={16} /> {notice}</div>}

      {loading ? <div className="empty-library"><LoaderCircle className="spin" /> 正在加载支付中心…</div> : (
        <>
          <section className="wallet-hero">
            <div><Coins size={25} /><span>可用创作积分</span><strong>{wallet.points}</strong></div>
            <div><ReceiptText size={25} /><span>账本记录</span><strong>{wallet.entries.length}</strong></div>
            <div><CreditCard size={25} /><span>订单数量</span><strong>{orders.length}</strong></div>
          </section>

          <section className="billing-section">
            <div className="section-title"><div><h2>会员计划</h2><p>下列按钮仅执行本地沙箱确认，不会调用外部支付服务。</p></div></div>
            <div className="plan-grid">
              {plans.map(plan => (
                <article className="plan-card" key={plan.id}>
                  <span>{plan.duration_days} 天</span><h2>{plan.name}</h2><p>{plan.description}</p>
                  <div className="plan-price"><strong>¥{plan.price}</strong><small> / 期</small></div>
                  <ul><li><CheckCircle2 size={15} /> {plan.points} 创作积分</li><li><CheckCircle2 size={15} /> 幂等订单与追加式流水</li></ul>
                  <button type="button" className="primary-action" onClick={() => void buySandbox(plan)} disabled={busy === plan.id}>{busy === plan.id ? <LoaderCircle className="spin" size={16} /> : <CreditCard size={16} />} 沙箱购买 {plan.name}</button>
                </article>
              ))}
            </div>
          </section>

          <section className="billing-section">
            <div className="section-title"><ReceiptText size={20} /><div><h2>订单记录</h2><p>金额和币种由服务端会员计划锁定，浏览器不能覆盖。</p></div></div>
            <div className="order-list">
              {orders.length === 0 ? <p>暂无订单</p> : orders.map(order => (
                <div className="order-row" key={order.id}><div><strong>{order.plan_id}</strong><small>{new Date(order.created_at).toLocaleString('zh-CN')}</small></div><span>{order.provider}</span><span>{order.currency} {order.amount}</span><span className={`order-status ${order.status}`}>{order.status === 'paid' ? '已支付' : '待支付'}</span></div>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
