// The price list as a file to hand to a customer: the quote only, never the official price beside it.

import { t } from '../../i18n';
import { priceKindLabel, unitPrice } from './financeFormat';


export interface QuotePrices { input?: number; output?: number; price?: number; by_resolution?: Record<string, number> }
/** `currency` is what the prices are shown in (yuan); `priced_in`, sent to finance only, is what the official price was set in. */
export interface QuoteRow { model: string; kind: string; currency: string; quote: QuotePrices; official?: QuotePrices; priced_in?: string }

/** 0.2 → "20%". */
export const percent = (markup: number): string => `${Math.round(markup * 1000) / 10}%`;

const cell = (value: string): string => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
// Numbers go out plain (no thousands separator), so a spreadsheet reads them as numbers.
const plain = (value: number | undefined): string => (value === undefined ? '' : String(Number(value)));

const BYTE_ORDER_MARK = String.fromCharCode(0xfeff);

/** CSV with a byte-order mark, so a spreadsheet opens the Chinese headings as they are. */
export function quoteSheet(rows: readonly QuoteRow[]): string {
  const lines = [[t('模型'), t('计价方式'), t('币种'), t('输入价'), t('输出价'), t('单价'), t('按分辨率')]];
  for (const row of rows) {
    const sizes = Object.entries(row.quote.by_resolution ?? {}).map(([size, price]) => `${size} ${unitPrice(price)}`).join(' / ');
    const tokens = row.kind === 'per_million_tokens';
    lines.push([
      row.model, priceKindLabel(row.kind), row.currency,
      tokens ? plain(row.quote.input) : '', tokens ? plain(row.quote.output) : '', tokens ? '' : plain(row.quote.price), sizes,
    ]);
  }
  return `${BYTE_ORDER_MARK}${lines.map(line => line.map(cell).join(',')).join('\r\n')}\r\n`;
}
