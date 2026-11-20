// One model's prices as the price list writes them, for the finance console and the customer's price list.

import { t } from '../../i18n';
import { unitPrice } from './financeFormat';
import type { QuotePrices as Prices, QuoteRow } from './quoteSheet';


const symbol = (currency: string) => (currency === 'CNY' ? '¥' : `${currency} `);

export function QuotePrices({ row, prices }: { row: Pick<QuoteRow, 'kind' | 'currency'>; prices: Prices | undefined }) {
  if (!prices) return <>—</>;
  const sign = symbol(row.currency);
  if (row.kind === 'per_million_tokens') {
    return <>{t('输入 {0} · 输出 {1}', [`${sign}${unitPrice(prices.input ?? 0)}`, `${sign}${unitPrice(prices.output ?? 0)}`])}</>;
  }
  const sizes = Object.entries(prices.by_resolution ?? {});
  return (
    <>
      {sign}{unitPrice(prices.price ?? 0)}
      {sizes.length > 0 && <span className="quote-list__sizes">{sizes.map(([size, price]) => `${size} ${sign}${unitPrice(price)}`).join(' · ')}</span>}
    </>
  );
}
