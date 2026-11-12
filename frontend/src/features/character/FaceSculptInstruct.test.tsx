// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiRequest } from '../../api/client';
import { FaceSculptInstruct } from './FaceSculptInstruct';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);

const preview = { description: '女主角；瓜子脸', face_text: '骨相：瓜子脸；五官：丹凤眼', layers: {}, issues: [], expressions: {}, sheet_stale: false, stale_note: '' };
const sculpt = { face: { face_shape: 'melon', eye_shape: 'phoenix' }, notes: {}, expressions: {}, preset: '' };

describe('FaceSculptInstruct', () => {
  beforeEach(() => {
    mocked.mockReset();
  });
  afterEach(cleanup);

  it('sends the sentence as a proposal and hands the sculpt to the parent', async () => {
    mocked.mockResolvedValue({ reply: '鼻梁调高、眼睛改成丹凤眼', patch: { eye_shape: 'phoenix' }, unknown: [], sculpt, preview, saved: false, current: null });
    const onProposed = vi.fn();
    render(<FaceSculptInstruct taskId="t 1" characterName="林婉" onProposed={onProposed} />);

    const input = screen.getByRole('textbox', { name: '用一句话捏' });
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(input, '鼻梁再高一点，眼睛改成丹凤眼{Enter}');

    await waitFor(() => expect(onProposed).toHaveBeenCalledTimes(1));
    expect(mocked).toHaveBeenCalledWith(
      `/api/drama/t%201/characters/${encodeURIComponent('林婉')}/face-sculpt/instruct`,
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(String(mocked.mock.calls[0][1]?.body))).toEqual({ message: '鼻梁再高一点，眼睛改成丹凤眼', apply: false });
    expect(onProposed).toHaveBeenCalledWith(sculpt, { reply: '鼻梁调高、眼睛改成丹凤眼', unknown: [], preview });
    expect(screen.getByRole('status').textContent).toBe('鼻梁调高、眼睛改成丹凤眼');
    expect((input as HTMLInputElement).value).toBe('');
    expect(screen.queryByText(/没认出来/)).toBeNull();
  });

  it('lists what the server did not understand', async () => {
    mocked.mockResolvedValue({ reply: '只改了眼睛', patch: {}, unknown: ['耳垂厚一点', '有点像她妈'], sculpt, preview, saved: false, current: null });
    render(<FaceSculptInstruct taskId="t1" characterName="林婉" onProposed={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: '用一句话捏' }), '眼睛大点，耳垂厚一点，有点像她妈');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('没认出来：耳垂厚一点；有点像她妈')).toBeTruthy();
  });

  it('shows the error inline, does not call the parent, and ignores an empty or busy send', async () => {
    mocked.mockRejectedValue(new Error('服务端没响应'));
    const onProposed = vi.fn();
    const { rerender } = render(<FaceSculptInstruct taskId="t1" characterName="林婉" onProposed={onProposed} />);

    const input = screen.getByRole('textbox', { name: '用一句话捏' });
    await userEvent.type(input, '   {Enter}');
    expect(mocked).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, '眼睛大点{Enter}');
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('服务端没响应');
    expect(onProposed).not.toHaveBeenCalled();

    rerender(<FaceSculptInstruct taskId="t1" characterName="林婉" busy onProposed={onProposed} />);
    expect((screen.getByRole('textbox', { name: '用一句话捏' }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
