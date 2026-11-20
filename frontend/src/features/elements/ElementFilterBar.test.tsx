// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';

const image = (id: string) => ({
  id: `${id}-f`, slot: 'front', mime_type: 'image/png', media_kind: 'image', size_bytes: 1, sha256: id, url: `/media/${id}.png`,
});

const actors = [
  { id: 'a1', kind: 'actor', name: '沈知微', description: '冷面女官', status: 'ready', version: 2, metadata: {}, model3d: null, files: [image('a1')] },
  { id: 'a2', kind: 'actor', name: '陆行远', description: '巡警', status: 'draft', version: 1, metadata: {}, model3d: null, files: [] },
  { id: 'a3', kind: 'actor', name: '裴崇', description: '', status: 'ready', version: 1, metadata: { needs_redraw: true }, model3d: null, files: [image('a3')] },
  {
    id: 'a4', kind: 'actor', name: '少年沈知微', description: '', status: 'draft', version: 1, model3d: null, files: [],
    metadata: { variant: { of: '沈知微', label: '少年', triggers: [] } },
  },
];

function serve() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/api/elements?kind=actor')) {
      return { ok: true, json: async () => ({ items: actors, total: actors.length }) } as Response;
    }
    return { ok: true, json: async () => ({ folders: [], total: 0, unfiled: 0 }) } as Response;
  });
}

const cardNames = () => screen.getAllByRole('article').map(card => card.getAttribute('aria-label'));

describe('element filter bar in the library', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('nests derived looks under their base character', async () => {
    serve();
    render(<ElementLibraryPage initialKind="actor" embedded taskId="t1" />);
    await screen.findByRole('article', { name: '演员资产“沈知微”' });
    const variants = screen.getByRole('group', { name: '“沈知微”的衍生形象' });
    expect(within(variants).getByText('衍生形象')).toBeTruthy();
    expect(within(variants).getByRole('article', { name: '演员资产“少年沈知微”' })).toBeTruthy();
    expect(cardNames()).toEqual(['演员资产“沈知微”', '演员资产“少年沈知微”', '演员资产“陆行远”', '演员资产“裴崇”']);
  });

  it('filters the cards by search, status and missing image', async () => {
    serve();
    render(<ElementLibraryPage initialKind="actor" embedded taskId="t1" />);
    await screen.findByRole('article', { name: '演员资产“沈知微”' });
    const bar = screen.getByRole('region', { name: '筛选资产' });
    expect(within(bar).getByText('共 4 个')).toBeTruthy();

    fireEvent.change(within(bar).getByRole('searchbox', { name: '搜索名称或描述' }), { target: { value: '巡警' } });
    expect(cardNames()).toEqual(['演员资产“陆行远”']);
    expect(within(bar).getByText('显示 1 / 4 个')).toBeTruthy();

    fireEvent.click(within(bar).getByRole('button', { name: '清除筛选' }));
    fireEvent.click(within(bar).getByRole('button', { name: '需重画 1' }));
    expect(cardNames()).toEqual(['演员资产“裴崇”']);

    fireEvent.click(within(bar).getByRole('button', { name: '待生成 2' }));
    expect(cardNames()).toEqual(['演员资产“陆行远”', '演员资产“少年沈知微”']);

    fireEvent.click(within(bar).getByRole('button', { name: '全部 4' }));
    fireEvent.click(within(bar).getByRole('checkbox', { name: '只看缺图' }));
    expect(cardNames()).toEqual(['演员资产“陆行远”', '演员资产“少年沈知微”']);

    fireEvent.change(within(bar).getByRole('searchbox', { name: '搜索名称或描述' }), { target: { value: '不存在' } });
    expect(screen.queryAllByRole('article')).toHaveLength(0);
    expect(screen.getByText('没有符合条件的演员')).toBeTruthy();
  });
});
