import { describe, expect, it } from 'vitest';

import { countByStatus, elementStatus, filterElements, filtersActive, groupByBase, EMPTY_FILTERS } from './elementFilters';
import type { ElementItem } from './elementTypes';

function item(id: string, extra: Partial<ElementItem> = {}): ElementItem {
  return {
    id, kind: 'actor', name: id, description: '', status: 'draft', version: 1, metadata: {}, model3d: null, files: [], ...extra,
  };
}

const image = { id: 'f', slot: 'reference', mime_type: 'image/png', media_kind: 'image' as const, size_bytes: 1, sha256: 's', url: '/x.png' };

describe('elementFilters', () => {
  const ready = item('沈知微', { status: 'ready', files: [image], description: '冷面女官' });
  const pending = item('陆行远', { description: '巡警' });
  const redraw = item('裴崇', { status: 'ready', files: [image], metadata: { needs_redraw: true } });

  it('derives pending, redraw and ready from existing fields', () => {
    expect(elementStatus(ready)).toBe('ready');
    expect(elementStatus(pending)).toBe('pending');
    expect(elementStatus(redraw)).toBe('redraw');
    expect(elementStatus(item('x', { status: 'ready', metadata: { look_check: { passed: false, problems: ['伤口位置'] } } }))).toBe('redraw');
    expect(countByStatus([ready, pending, redraw])).toEqual({ all: 3, pending: 1, redraw: 1, ready: 1 });
  });

  it('filters by query on name or description, status and missing image', () => {
    const all = [ready, pending, redraw];
    expect(filterElements(all, { query: '女官' }).map(entry => entry.id)).toEqual(['沈知微']);
    expect(filterElements(all, { query: ' 陆行 ' }).map(entry => entry.id)).toEqual(['陆行远']);
    expect(filterElements(all, { status: 'redraw' }).map(entry => entry.id)).toEqual(['裴崇']);
    expect(filterElements(all, { missing: 'image' }).map(entry => entry.id)).toEqual(['陆行远']);
    expect(filterElements(all, { query: '沈', missing: 'image' })).toEqual([]);
    expect(filterElements(all, EMPTY_FILTERS)).toHaveLength(3);
    expect(filtersActive(EMPTY_FILTERS)).toBe(false);
    expect(filtersActive({ ...EMPTY_FILTERS, query: ' ' })).toBe(false);
    expect(filtersActive({ ...EMPTY_FILTERS, status: 'ready' })).toBe(true);
  });

  it('nests variants under their base in list order and keeps orphans on their own', () => {
    const young = item('少年沈知微', { metadata: { variant: { of: '沈知微', label: '少年' } } });
    const orphan = item('婚纱林夏', { metadata: { variant: { of: '林夏', label: '婚纱' } } });
    const groups = groupByBase([young, pending, ready, orphan]);
    expect(groups.map(group => [group.base.id, group.variants.map(entry => entry.id)])).toEqual([
      ['陆行远', []],
      ['沈知微', ['少年沈知微']],
      ['婚纱林夏', []],
    ]);
  });
});
