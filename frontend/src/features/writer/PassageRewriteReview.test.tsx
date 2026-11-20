// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PassageRewriteReview } from './PassageRewriteReview';
import { passageOperations, type PassageRewriteResult, type ScreenwritingEpisode } from './screenwritingApi';

const EPISODE = {
  episode: 2, planRevision: 'rev-1',
  plan: { title: '赎回', scenes: [{ scene_id: 'E2S01' }, { scene_id: 'E2S02' }, { scene_id: 'E2S03' }] },
} as unknown as ScreenwritingEpisode;

const RESULT: PassageRewriteResult = {
  task_id: 't1', episode: 2, plan_revision: 'rev-1', instruction: '得抢',
  scenes: [
    { scene_id: 'E2S02', before: { scene_description: '掌柜取出玉佩。', utterances: [] },
      after: { setting: '当铺 夜 内景', characters_in_scene: ['林夏'], scene_description: '林夏夺过玉佩。', utterances: [{ kind: 'dialogue', speaker: '林夏', text: '这是我娘的。' }] } },
    { scene_id: 'E2S03', before: { scene_description: '林夏走进雨里。' },
      after: { setting: '长街 夜 外景', characters_in_scene: ['林夏'], scene_description: '林夏冲进雨里。', utterances: [] } },
  ],
  impact: {
    checked: true,
    findings: [{ episode: 3, fact: '【兑现】周教授认出玉佩背面的「周」字', quote: '林夏夺过玉佩', fix: '让刻字露一下' }],
    lost_key_lines: [],
    state_changes: { before: ['【物件】林夏赎回了玉佩'], after: ['【物件】林夏抢回了玉佩'] },
  },
};

type Call = { url: string; method?: string; body?: unknown };

function serve(answers: { rewrite?: PassageRewriteResult }) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith('/rewrite-passage')) return { ok: true, json: async () => answers.rewrite ?? RESULT } as Response;
    if (url.endsWith('/state-changes')) return { ok: true, json: async () => ({ episode: 2, state_changes: [] }) } as Response;
    return { ok: true, json: async () => ({ ...EPISODE, planRevision: 'rev-2' }) } as Response;
  });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('passageOperations', () => {
  it('writes every rewritten shot back as one update of its edited fields', () => {
    expect(passageOperations(RESULT)).toEqual([
      { op: 'update', id: 'E2S02', fields: RESULT.scenes[0].after },
      { op: 'update', id: 'E2S03', fields: RESULT.scenes[1].after },
    ]);
  });
});

describe('PassageRewriteReview', () => {
  it('sends the range, shows what the change breaks, and adopts it with the episode sheet', async () => {
    const calls = serve({});
    const onApplied = vi.fn();
    const user = userEvent.setup();
    render(<PassageRewriteReview taskId="t1" episode={EPISODE} onApplied={onApplied} />);

    await user.selectOptions(screen.getByLabelText('改写起点分镜'), 'E2S03');
    await user.selectOptions(screen.getByLabelText('改写终点分镜'), 'E2S02');
    await user.type(screen.getByLabelText('改写要求'), '得抢');
    await user.click(screen.getByRole('button', { name: '改写这 2 个分镜' }));
    expect(calls[0].body).toEqual({ scene_ids: ['E2S02', 'E2S03'], instruction: '得抢', keep: [] });

    const impact = await screen.findByRole('note', { name: '这次改动的后果' });
    expect(within(impact).getByText('第 3 集')).toBeTruthy();
    expect(within(impact).getByText('让刻字露一下')).toBeTruthy();
    expect(screen.getByText('林夏冲进雨里。')).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: '采纳时同时更新本集场记' }) as HTMLInputElement).checked).toBe(true);

    await user.click(screen.getByRole('button', { name: '采纳改写' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ planRevision: 'rev-2' }), true));
    const patch = calls.find(call => call.method === 'PATCH');
    expect(patch?.body).toMatchObject({ baseRevision: 'rev-1', operations: passageOperations(RESULT) });
    expect(calls.find(call => call.url.endsWith('/ledger/2/state-changes'))?.body).toEqual({ state_changes: ['【物件】林夏抢回了玉佩'] });
    expect(await screen.findByText('已写回 2 个分镜。第 3 集可能要跟着改。')).toBeTruthy();
  });

  it('asks again holding on to what was lost, and leaves the sheet alone when unticked', async () => {
    const calls = serve({});
    const onApplied = vi.fn();
    const user = userEvent.setup();
    render(<PassageRewriteReview taskId="t1" episode={EPISODE} onApplied={onApplied} />);

    await user.type(screen.getByLabelText('改写要求'), '更狠');
    await user.click(screen.getByRole('button', { name: '改写这 1 个分镜' }));
    await user.click(await screen.findByRole('button', { name: '守住这些再改一次' }));
    await waitFor(() => expect(calls.filter(call => call.url.endsWith('/rewrite-passage'))).toHaveLength(2));
    expect(calls[1].body).toEqual({ scene_ids: ['E2S01'], instruction: '更狠', keep: ['【兑现】周教授认出玉佩背面的「周」字'] });

    await user.click(await screen.findByRole('checkbox', { name: '采纳时同时更新本集场记' }));
    await user.click(screen.getByRole('button', { name: '采纳改写' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(expect.anything(), false));
    expect(calls.some(call => call.url.endsWith('/state-changes'))).toBe(false);
  });

  it('says plainly when the effects could not be checked', async () => {
    serve({ rewrite: { ...RESULT, impact: { checked: false, findings: [], lost_key_lines: [], state_changes: { before: [], after: [] } } } });
    const user = userEvent.setup();
    render(<PassageRewriteReview taskId="t1" episode={EPISODE} onApplied={vi.fn()} />);
    await user.type(screen.getByLabelText('改写要求'), '改');
    await user.click(screen.getByRole('button', { name: '改写这 1 个分镜' }));
    expect(await screen.findByText('这次没能核对后果，采纳前请自己对一下前后各集。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '守住这些再改一次' })).toBeNull();
  });
});
