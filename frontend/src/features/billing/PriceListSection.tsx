// 模型价目 on the customer's billing page: what each model is priced at, per unit of use. These are
// the outward prices only; the server never sends this page what a model costs us. The section
// loads on its own and stays out of the way when there is nothing to show, so a price list that
// fails to load never takes the wallet and the orders down with it.

import { Tags } from 'lucide-react';
import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { priceKindLabel } from '../finance/financeFormat';
import { QuotePrices } from '../finance/QuotePrices';
import type { QuoteRow } from '../finance/quoteSheet';
import '../finance/UsageLive.css';


export function PriceListSection() {
  const [rows, setRows] = useState<QuoteRow[]>([]);
  useEffect(() => {
    let current = true;
    const handle = window.setTimeout(() => {
      apiRequest<{ items?: QuoteRow[] }>('/api/billing/price-list')
        .then(data => { if (current) setRows((data.items ?? []).filter(row => row && row.model && row.quote)); })
        .catch(() => undefined);
    }, 0);
    return () => {
      current = false;
      window.clearTimeout(handle);
    };
  }, []);
  if (rows.length === 0) return null;
  return (
    <section className="billing-section">
      <div className="section-title"><Tags size={20} /><div><h2>{t('模型价目')}</h2><p>{t('各模型按用量计的单价。')}</p></div></div>
      <div className="finance-table-wrap"><table className="finance-table usage-table">
        <thead><tr><th>{t('模型')}</th><th>{t('计价方式')}</th><th>{t('单价')}</th></tr></thead>
        <tbody>{rows.map(row => (
          <tr key={row.model}>
            <td className="finance-mono">{row.model}</td><td>{priceKindLabel(row.kind)}</td>
            <td><QuotePrices row={row} prices={row.quote} /></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}
