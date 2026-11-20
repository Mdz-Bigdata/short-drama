// 对外报价: every model that has an official price, with the price it is quoted at outward (the
// official price plus the markup). The sheet that leaves the building carries the quote alone.

import { Download } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { priceKindLabel } from './financeFormat';
import { Problem, Waiting } from './financeParts';
import { QuotePrices } from './QuotePrices';
import { percent, quoteSheet, type QuoteRow } from './quoteSheet';
import './UsageLive.css';


interface QuoteList { markup: number; usd_cny?: number; items: QuoteRow[] }

export function QuoteTab() {
  const [data, setData] = useState<QuoteList | null>(null);
  const [error, setError] = useState('');
  const [find, setFind] = useState('');
  const load = useCallback(async () => {
    setError('');
    try {
      setData(await apiRequest<QuoteList>('/api/admin/pricing/quote'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('加载失败'));
    }
  }, []);
  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);
  if (!data) return error ? <Problem text={error} /> : <Waiting />;

  const wanted = find.trim().toLowerCase();
  const rows = wanted ? data.items.filter(row => row.model.toLowerCase().includes(wanted)) : data.items;
  const save = () => {
    // Made in the page from what is on it: nothing is sent anywhere.
    const url = URL.createObjectURL(new Blob([quoteSheet(data.items)], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${t('模型报价单')}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <p className="quote-list__note">{t('对外报价 = 官方价 × {0}（加 {1}）。官方价改了，报价跟着变；没有官方价的模型不在这张表里。', [
        String(Math.round((1 + data.markup) * 1000) / 1000), percent(data.markup),
      ])}{data.usd_cny && data.items.some(row => row.priced_in === 'USD') ? ` ${t('官方价按美元计的模型按 1 美元 = ¥{0} 折成人民币。', [String(data.usd_cny)])}` : ''}</p>
      <div className="finance-filters">
        <input aria-label={t('按模型名查找')} placeholder={t('按模型名查找')} value={find} onChange={event => setFind(event.target.value)} />
        <button type="button" className="secondary-action" onClick={save} disabled={data.items.length === 0}><Download size={15} /> {t('导出报价单（不含官方价）')}</button>
      </div>
      {rows.length === 0 ? <p className="finance-empty">{data.items.length === 0 ? t('价目文件里还没有官方价') : t('没有叫这个名字的模型')}</p> : (
        <div className="finance-table-wrap"><table className="finance-table usage-table">
          <thead><tr><th>{t('模型')}</th><th>{t('计价方式')}</th><th>{t('官方价')}</th><th>{t('对外报价（+{0}）', [percent(data.markup)])}</th></tr></thead>
          <tbody>{rows.map(row => (
            <tr key={row.model}>
              <td className="finance-mono">{row.model}</td><td>{priceKindLabel(row.kind)}</td>
              <td className="quote-list__official"><QuotePrices row={row} prices={row.official} /></td>
              <td><strong><QuotePrices row={row} prices={row.quote} /></strong></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}
