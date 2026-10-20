// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { EpisodeLedgerTools } from './EpisodeLedgerTools';
import { discardedEpisodesOf, type LedgerView } from './screenwritingApi';
import { sentenceBoundaries } from './sourceSplitting';

const NOVEL = '林夏推开实验室的门，冷白灯光刺得她眯起眼。她在抽屉里找到了录音笔。周教授站在她身后，声音低沉：现在回头还来得及。';
const FIRST_END = NOVEL.indexOf('她在抽屉');

const LEDGER: LedgerView = {
  task_id: 't1',
  entries: [
    { episode: 1, title: '对峙', hook: '', origin: 'cut', source_range: { start: 0, end: FIRST_END }, units: FIRST_END, units_noun: '字', opening: NOVEL.slice(0, FIRST_END), closing: '', written: true, ledger_status: 'written' },
    { episode: 2, title: '反击', hook: '', origin: 'cut', source_range: { start: FIRST_END, end: NOVEL.length }, units: NOVEL.length - FIRST_END, units_noun: '字', opening: '她在抽屉', closing: '还来得及。', written: true, ledger_status: 'written' },
  ],
  unsplit: [],
  source_length: NOVEL.length,
  layout_revision: 'abc',
  candidate: null,
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) } as Response);
}

function bodyOf(init?: RequestInit): Record<string, unknown> {
  return init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
}

describe('sentenceBoundaries', () => {
  it('lists the end of every sentence that leaves text on both sides', () => {
    const points = sentenceBoundaries(NOVEL);
    expect(points).toEqual([NOVEL.indexOf('。') + 1, NOVEL.indexOf('录音笔。') + 4]);
  });

  it('reads the episodes a confirmation 409 names', () => {
    expect(discardedEpisodesOf('这一步会丢掉已写出的集：第 2 集、第 3 集；在 confirm_discard 里列出它们以确认')).toEqual([2, 3]);
    expect(discardedEpisodesOf('应用新剧本会归档当前角色、分镜或成片')).toEqual([]);
  });
});

describe('EpisodeLedgerTools', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let onChanged: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    onChanged = vi.fn<() => void>();
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse(LEDGER);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists every episode with its origin, length and the operations it allows', async () => {
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    expect(await screen.findByText('对峙')).toBeTruthy();
    expect(screen.getAllByText('切自整本源文')).toHaveLength(2);
    expect(screen.getByText(`${FIRST_END} 字`)).toBeTruthy();
    expect(screen.getByLabelText('拆分第 1 集')).toBeTruthy();
    expect(screen.getByLabelText('合并第 1 集与下一集')).toBeTruthy();
    expect(screen.queryByLabelText('合并第 2 集与下一集')).toBeNull();
    expect(screen.getByLabelText('从第 2 集起重新规划')).toBeTruthy();
  });

  it('opens a written episode\'s full screenplay from its 来源 cell', async () => {
    const onOpenEpisode = vi.fn();
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => jsonResponse({
      ...LEDGER,
      entries: [LEDGER.entries[0], { ...LEDGER.entries[1], written: false, ledger_status: 'planned' }],
    }));
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} onOpenEpisode={onOpenEpisode} />);

    const link = await screen.findByRole('button', { name: '查看第 1 集完整剧本' });
    expect(link.textContent).toBe('切自整本源文');
    await user.click(link);
    expect(onOpenEpisode).toHaveBeenCalledWith(1);
    // An episode with no screenplay yet has nothing to open.
    expect(screen.queryByRole('button', { name: '查看第 2 集完整剧本' })).toBeNull();
    expect(screen.getAllByText('切自整本源文')).toHaveLength(2);
  });

  it('shows the unsplit source and cuts it into an episode', async () => {
    const posted: Record<string, unknown>[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/ledger/ops')) {
        posted.push(bodyOf(init));
        return jsonResponse({ ...LEDGER, created: [3] });
      }
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse({ ...LEDGER, unsplit: [{ start: 60, end: 80 }] });
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    await userEvent.click(await screen.findByText('切为一集'));

    await waitFor(() => expect(screen.getByText(/新写出第 3 集/)).toBeTruthy());
    expect(posted[0]).toMatchObject({ operation: 'cut_unsplit', start: 60, end: 80, confirm_discard: [], confirm_invalidate: false });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('splits an episode at a sentence boundary chosen from its own text', async () => {
    const posted: Record<string, unknown>[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/ledger/source?')) {
        return jsonResponse({ task_id: 't1', start: FIRST_END, end: NOVEL.length, text: NOVEL.slice(FIRST_END) });
      }
      if (url.endsWith('/ledger/ops')) {
        posted.push(bodyOf(init));
        if (!(bodyOf(init).confirm_discard as number[]).length) {
          return jsonResponse({ detail: '这一步会丢掉已写出的集：第 2 集；在 confirm_discard 里列出它们以确认' }, 409);
        }
        return jsonResponse({ ...LEDGER, created: [3], discarded: [2] });
      }
      if (url.endsWith('/ledger/impact?episode=2')) {
        return jsonResponse({ task_id: 't1', episodes: [{ episode: 2, title: '反击', origin: 'cut', written: true, scenes: 2, has_prose: false }] });
      }
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse(LEDGER);
      throw new Error(`unexpected fetch: ${url}`);
    });
    const confirmations: string[] = [];
    vi.stubGlobal('confirm', (message: string) => { confirmations.push(message); return true; });
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    await userEvent.click(await screen.findByLabelText('拆分第 1 集'));
    // The split editor belongs to episode 1, but the source stub answers with episode 2's text;
    // the point chosen is relative to that excerpt and sent as an absolute offset.
    const form = await screen.findByLabelText('拆分第 1 集', { selector: 'form' });
    const sentence = within(form).getByLabelText('按句子');
    await waitFor(() => expect(within(sentence).getAllByRole('option').length).toBeGreaterThan(1));
    const options = within(sentence).getAllByRole('option');
    await userEvent.selectOptions(sentence, options[1]);
    await userEvent.type(within(form).getByLabelText('新集标题'), '回头');
    await userEvent.click(within(form).getByText('在此拆分'));

    await waitFor(() => expect(screen.getByText(/新写出第 3 集/)).toBeTruthy());
    const excerpt = NOVEL.slice(FIRST_END);
    const expectedOffset = FIRST_END + sentenceBoundaries(excerpt)[0];
    expect(posted[0]).toMatchObject({ operation: 'split', episode: 1, offset: expectedOffset, title: '回头', confirm_discard: [] });
    expect(posted[1]).toMatchObject({ operation: 'split', episode: 1, offset: expectedOffset, confirm_discard: [2] });
    expect(confirmations[0]).toMatch(/第 2 集《反击》：2 个分镜/);
    expect(screen.getByText(/丢弃了第 2 集/)).toBeTruthy();
  });

  it('keeps the ledger when the user declines to lose a written episode', async () => {
    const posted: Record<string, unknown>[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/ledger/ops')) {
        posted.push(bodyOf(init));
        return jsonResponse({ detail: '这一步会丢掉已写出的集：第 1 集；在 confirm_discard 里列出它们以确认' }, 409);
      }
      if (url.includes('/ledger/impact')) return jsonResponse({ task_id: 't1', episodes: [] });
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse(LEDGER);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('confirm', () => false);
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    await userEvent.click(await screen.findByLabelText('删除第 1 集'));

    await waitFor(() => expect(screen.getByText('已取消。')).toBeTruthy());
    expect(posted).toHaveLength(1);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('plans a candidate, compares it with the old cut and adopts it after the archive confirmation', async () => {
    const candidate = {
      from_episode: 2, adoptable: true, old_count: 1, new_count: 2, old_average_units: 40, new_average_units: 20, replaced_written: [2],
      entries: [
        { position: 1, title: '新二', hook: '钩子', source_range: { start: FIRST_END, end: 60 }, units: 20, relation: 'overlaps', overlaps: [2] },
        { position: 2, title: '新三', hook: '', source_range: { start: 60, end: NOVEL.length }, units: 20, relation: 'overlaps', overlaps: [2] },
      ],
    };
    const posted: { url: string; body: Record<string, unknown> }[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/screenwriting/replan')) {
        posted.push({ url, body: bodyOf(init) });
        return jsonResponse({ ...LEDGER, candidate });
      }
      if (url.endsWith('/replan/adopt')) {
        posted.push({ url, body: bodyOf(init) });
        if (!bodyOf(init).confirm_invalidate) return jsonResponse({ detail: '应用新剧本会归档当前角色、分镜或成片；确认后可安全创建新版本' }, 409);
        return jsonResponse({ ...LEDGER, candidate: null, created: [2, 3], notes: ['1 个已写出的旧集保留在末尾（无原文、已过期），可随时删除'] });
      }
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse(LEDGER);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('confirm', () => true);
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    await userEvent.click(await screen.findByLabelText('从第 2 集起重新规划'));

    const region = await screen.findByRole('region', { name: '候选重规划' });
    expect(within(region).getByText('候选重规划 · 从第 2 集起')).toBeTruthy();
    expect(within(region).getByText('原 1 集（均 40 字） → 新 2 集（均 20 字）')).toBeTruthy();
    expect(within(region).getAllByText('重新划分（原第 2 集）')).toHaveLength(2);
    expect(within(region).getByText(/替换已写出的第 2 集/)).toBeTruthy();
    expect(screen.getByLabelText('从第 1 集起重新规划').hasAttribute('disabled')).toBe(true);

    await userEvent.click(within(region).getByText('采纳并保留旧集'));

    await waitFor(() => expect(screen.getByText(/新写出第 2、3 集/)).toBeTruthy());
    expect(screen.queryByRole('region', { name: '候选重规划' })).toBeNull();
    expect(posted.map(item => item.url.split('/screenwriting')[1])).toEqual(['/replan', '/replan/adopt', '/replan/adopt']);
    expect(posted[0].body).toEqual({ from_episode: 2 });
    expect(posted[2].body).toMatchObject({ delete_replaced: false, confirm_invalidate: true });
    expect(screen.getByText(/旧集保留在末尾/)).toBeTruthy();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('creates an episode with its own text where the user puts it', async () => {
    const posted: Record<string, unknown>[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/ledger/ops')) {
        posted.push(bodyOf(init));
        return jsonResponse({ ...LEDGER, created: [1], renumbered: { '1': 2, '2': 3 } });
      }
      if (url.endsWith('/screenwriting/ledger')) return jsonResponse(LEDGER);
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(<EpisodeLedgerTools taskId="t1" onChanged={onChanged} />);

    await userEvent.click(await screen.findByText('新建一集'));
    await userEvent.type(screen.getByLabelText('标题'), '序章');
    await userEvent.selectOptions(screen.getByLabelText('排在'), '0');
    await userEvent.type(screen.getByLabelText(/这一集自己的原文/), '多年以前。');
    await userEvent.selectOptions(screen.getByLabelText('体裁'), 'screenplay');
    await userEvent.click(screen.getByText('创建并写出'));

    await waitFor(() => expect(screen.getByText(/重新编号：1→2，2→3/)).toBeTruthy());
    expect(posted[0]).toMatchObject({ operation: 'create', title: '序章', text: '多年以前。', source_kind: 'screenplay', after: 0 });
  });
});
