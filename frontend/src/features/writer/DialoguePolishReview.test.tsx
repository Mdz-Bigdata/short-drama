// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DialoguePolishReview } from './DialoguePolishReview';
import { polishOperations, type DialoguePolishResult, type ScreenwritingEpisode } from './screenwritingApi';

const RESULT: DialoguePolishResult = {
  task_id: 't1', episode: 1, plan_revision: 'rev-1',
  items: [
    { id: 'E1S01#0', scene_id: 'E1S01', index: 0, speaker: '裘三娘', before: '我希望你在三天之内把这把刀磨好。', after: '三天。磨快它。' },
    { id: 'E1S01#2', scene_id: 'E1S01', index: 2, speaker: '谢九', before: '杀谁？', after: '杀谁？' },
    { id: 'E1S02#0', scene_id: 'E1S02', index: 0, speaker: '谢九', before: '你要杀的人是谁呢？', after: '杀谁。' },
  ],
  scenes: {
    E1S01: [
      { kind: 'dialogue', speaker: '裘三娘', text: '我希望你在三天之内把这把刀磨好。', delivery: '冷硬' },
      { kind: 'voiceover', speaker: null, text: '雨一直下。' },
      { kind: 'dialogue', speaker: '谢九', text: '杀谁？' },
    ],
    E1S02: [{ kind: 'dialogue', speaker: '谢九', text: '你要杀的人是谁呢？' }],
  },
};
const EPISODE = { episode: 1, planRevision: 'rev-1' } as ScreenwritingEpisode;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('polishOperations', () => {
  it('replaces only the accepted lines and keeps everything else in the scene', () => {
    const operations = polishOperations(RESULT, new Set(['E1S01#0']));
    expect(operations).toEqual([{ op: 'update', id: 'E1S01', fields: { utterances: [
      { kind: 'dialogue', speaker: '裘三娘', text: '三天。磨快它。', delivery: '冷硬' },
      { kind: 'voiceover', speaker: null, text: '雨一直下。' },
      { kind: 'dialogue', speaker: '谢九', text: '杀谁？' },
    ] } }]);
    // 原来的整组不被改动。
    expect(RESULT.scenes.E1S01[0].text).toBe('我希望你在三天之内把这把刀磨好。');
  });
});

describe('DialoguePolishReview', () => {
  it('shows what changed, lets lines be unticked, and writes back only the ticked ones', async () => {
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith('/polish-dialogue')) return { ok: true, json: async () => RESULT } as Response;
      return { ok: true, json: async () => ({ ...EPISODE, planRevision: 'rev-2' }) } as Response;
    });
    const onApplied = vi.fn();
    const user = userEvent.setup();
    render(<DialoguePolishReview taskId="t1" episode={EPISODE} onApplied={onApplied} />);

    await user.selectOptions(screen.getByRole('combobox'), '吵架');
    await user.click(screen.getByRole('button', { name: '润色台词' }));
    expect(calls[0].body).toEqual({ scene_ids: [], scene_kind: '吵架', extra: '' });
    expect(await screen.findAllByRole('listitem')).toHaveLength(2);
    await user.click(screen.getByLabelText('采纳 谢九 的这句'));
    await user.click(screen.getByRole('button', { name: '采纳选中的 1 句' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    const patch = calls.find(call => call.method === 'PATCH');
    expect(patch?.body).toMatchObject({ baseRevision: 'rev-1', confirmInvalidate: false });
    expect((patch?.body as { operations: { id: string }[] }).operations.map(op => op.id)).toEqual(['E1S01']);
  });

  it('asks before archiving downstream work, and keeps the result when declined', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).endsWith('/polish-dialogue')) return { ok: true, json: async () => RESULT } as Response;
      return { ok: false, status: 409, json: async () => ({ detail: '需要归档当前角色、分镜和成片' }) } as Response;
    });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    render(<DialoguePolishReview taskId="t1" episode={EPISODE} onApplied={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: '润色台词' }));
    await user.click(await screen.findByRole('button', { name: '采纳选中的 2 句' }));
    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByText(/已取消/)).toBeTruthy();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });
});
