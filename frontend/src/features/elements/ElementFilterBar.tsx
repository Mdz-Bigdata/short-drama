import { Search, X } from 'lucide-react';

import { t } from '../../i18n';
import { countByStatus, filtersActive, type ElementFilters, type ElementStatusFilter } from './elementFilters';
import type { ElementItem } from './elementTypes';
import './ElementFilterBar.css';

const statusChips: Array<[ElementStatusFilter, string]> = [
  ['all', '全部'],
  ['pending', '待生成'],
  ['redraw', '需重画'],
  ['ready', '已就绪'],
];

/** 资产卡片上方的搜索、状态和缺图筛选；只筛眼前这份清单，不发请求。 */
export function ElementFilterBar({ items, filters, shown, onChange }: {
  items: ElementItem[];
  filters: ElementFilters;
  /** 筛完还剩几个。 */
  shown: number;
  onChange: (next: ElementFilters) => void;
}) {
  const counts = countByStatus(items);
  const active = filtersActive(filters);
  return (
    <section className="element-filter-bar" aria-label={t('筛选资产')}>
      <label className="element-filter-bar__search">
        <Search size={14} aria-hidden="true" />
        <input
          type="search"
          value={filters.query}
          placeholder={t('搜索名称或描述')}
          aria-label={t('搜索名称或描述')}
          onChange={event => onChange({ ...filters, query: event.target.value })}
        />
      </label>
      <div className="element-filter-bar__chips" role="group" aria-label={t('按状态筛选')}>
        {statusChips.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="element-filter-chip"
            aria-pressed={filters.status === value}
            onClick={() => onChange({ ...filters, status: value })}
          >{`${t(label)} ${counts[value]}`}</button>
        ))}
      </div>
      <label className="element-filter-bar__toggle">
        <input
          type="checkbox"
          checked={filters.missing === 'image'}
          onChange={event => onChange({ ...filters, missing: event.target.checked ? 'image' : 'none' })}
        />
        {t('只看缺图')}
      </label>
      <span className="element-filter-bar__count" aria-live="polite">
        {active ? t('显示 {0} / {1} 个', [shown, items.length]) : t('共 {0} 个', [items.length])}
      </span>
      {active && (
        <button
          type="button"
          className="element-filter-bar__clear"
          onClick={() => onChange({ query: '', status: 'all', missing: 'none' })}
        ><X size={12} aria-hidden="true" /> {t('清除筛选')}</button>
      )}
    </section>
  );
}
