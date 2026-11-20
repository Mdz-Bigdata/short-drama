/**
 * 资产卡片的筛选和分组：只看已有字段，不另存状态。
 *
 * 状态三档：需重画(设定改过 / 妆效核对没过 / 上次重出失败) > 已就绪(status=ready) > 待生成(其余)。
 * 衍生形象(variantOf)排在它来源角色的下面；来源不在当前清单里时自成一组。
 */
import { actorRegeneration, findPoster, lookCheckProblems, variantOf, type ElementItem } from './elementTypes';

export type ElementStatusFilter = 'all' | 'pending' | 'redraw' | 'ready';
export type ElementMissingFilter = 'image' | 'none';

export interface ElementFilters {
  query: string;
  status: ElementStatusFilter;
  missing: ElementMissingFilter;
}

export const EMPTY_FILTERS: ElementFilters = { query: '', status: 'all', missing: 'none' };

export function elementStatus(item: ElementItem): Exclude<ElementStatusFilter, 'all'> {
  if (item.metadata?.needs_redraw || lookCheckProblems(item).length > 0 || actorRegeneration(item).error) return 'redraw';
  return item.status === 'ready' ? 'ready' : 'pending';
}

export function isMissingImage(item: ElementItem): boolean {
  return !findPoster(item);
}

export function filtersActive(filters: ElementFilters): boolean {
  return Boolean(filters.query.trim()) || filters.status !== 'all' || filters.missing !== 'none';
}

export function filterElements(items: ElementItem[], filters: Partial<ElementFilters>): ElementItem[] {
  const query = (filters.query ?? '').trim().toLowerCase();
  const status = filters.status ?? 'all';
  const missing = filters.missing ?? 'none';
  return items.filter(item => {
    if (query && !`${item.name}\n${item.description ?? ''}`.toLowerCase().includes(query)) return false;
    if (status !== 'all' && elementStatus(item) !== status) return false;
    if (missing === 'image' && !isMissingImage(item)) return false;
    return true;
  });
}

/** 每档状态各有几个，给筛选按钮标数。 */
export function countByStatus(items: ElementItem[]): Record<ElementStatusFilter, number> {
  const counts: Record<ElementStatusFilter, number> = { all: items.length, pending: 0, redraw: 0, ready: 0 };
  for (const item of items) counts[elementStatus(item)] += 1;
  return counts;
}

export interface ElementGroup {
  base: ElementItem;
  variants: ElementItem[];
}

/** 按清单原有顺序排出各组；衍生形象跟在来源角色后面，保持各自原来的先后。 */
export function groupByBase(items: ElementItem[]): ElementGroup[] {
  const baseNames = new Set(items.filter(item => !variantOf(item)).map(item => item.name));
  const groups: ElementGroup[] = [];
  const byName = new Map<string, ElementGroup>();
  for (const item of items) {
    const variant = variantOf(item);
    if (variant && baseNames.has(variant.of)) continue;
    const group: ElementGroup = { base: item, variants: [] };
    groups.push(group);
    if (!variant && !byName.has(item.name)) byName.set(item.name, group);
  }
  for (const item of items) {
    const variant = variantOf(item);
    if (variant && baseNames.has(variant.of)) byName.get(variant.of)?.variants.push(item);
  }
  return groups;
}
