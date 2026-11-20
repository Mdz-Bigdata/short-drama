// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { SelectionRef } from '../deskTypes';
import { StagePrompt } from './StagePrompt';

const CHAT = 'http://localhost:8000/api/drama/t1/director-desk/scenes/E1S01/director/chat';
const MEASURED = { score: 80, errors: 0, warnings: 0, failing: [], notes: [] };

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('StagePrompt', () => {
  const fetchMock = vi.fn();
  const onPlanChanged = vi.fn();
  const onDeselect = vi.fn();
  const onOpenLog = vi.fn();
  const sent: Array<Record<string, unknown>> = [];

  const show = (selection: SelectionRef[] = [], locked = false) => render(
    <StagePrompt
      taskId="t1" sceneId="E1S01" revision={7} selection={selection} locked={locked}
      onPlanChanged={onPlanChanged} onDeselect={onDeselect} onOpenLog={onOpenLog}
    />,
  );
  const answer = (reply: (body: Record<string, unknown>) => unknown) => {
    fetchMock.mockImplementation((url: string, options: RequestInit = {}) => {
      if (String(url) !== CHAT || options.method !== 'POST') return json({ detail: `unexpected ${url}` }, 500);
      const body = JSON.parse(String(options.body)) as Record<string, unknown>;
      sent.push(body);
      const result = reply(body);
      return result instanceof Promise ? result : json(result);
    });
  };

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    sent.length = 0;
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    [fetchMock, onPlanChanged, onDeselect, onOpenLog].forEach(mock => mock.mockReset());
  });

  it('sends what is picked along with the request, shows the answer and has the stage read again', async () => {
    answer(() => ({ message: { role: 'assistant', text: '把长案挪到了窗下' }, changed: true, measured: MEASURED, failing: [] }));
    show([{ kind: 'landmark', name: '长案' }, { kind: 'camera', id: 'cam-01' }, { kind: 'actor', name: '林夏' }]);
    // A lens has no name the model knows it by: it is not a chip.
    expect(screen.getByTitle('只改「长案」')).toBeTruthy();
    expect(screen.getByTitle('只改「林夏」')).toBeTruthy();
    expect(screen.queryByText('cam-01')).toBeNull();
    const field = screen.getByLabelText('想怎么改') as HTMLInputElement;
    await userEvent.type(field, '靠窗放{Enter}');
    expect((await screen.findByRole('status')).textContent).toContain('把长案挪到了窗下');
    expect(sent).toEqual([{ base_revision: 7, message: '靠窗放', names: ['长案', '林夏'], shot_id: null }]);
    expect(onPlanChanged).toHaveBeenCalledTimes(1);
    expect(field.value).toBe('');
  });

  it('keeps the words and leaves the stage alone when the model fails, and says why', async () => {
    answer(() => json({ detail: '模型没有返回结果，舞台没有改动' }, 422));
    show();
    const field = screen.getByLabelText('想怎么改') as HTMLInputElement;
    await userEvent.type(field, '压迫感强一点');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    expect((await screen.findByRole('alert')).textContent).toContain('模型没有返回结果');
    expect(field.value).toBe('压迫感强一点');
    expect(onPlanChanged).not.toHaveBeenCalled();
    expect(sent[0].names).toEqual([]);
  });

  it('does not reload the stage for an answer that changed nothing', async () => {
    answer(() => ({ message: { role: 'assistant', text: '林夏在左边' }, changed: false, measured: MEASURED, failing: [] }));
    show();
    await userEvent.type(screen.getByLabelText('想怎么改'), '谁在左边{Enter}');
    expect((await screen.findByRole('status')).textContent).toContain('林夏在左边');
    expect(onPlanChanged).not.toHaveBeenCalled();
  });

  it('cannot send while the stage is locked or the field is empty', async () => {
    const { rerender } = show([], true);
    expect((screen.getByLabelText('想怎么改') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<StagePrompt taskId="t1" sceneId="E1S01" revision={7} selection={[]} locked={false} onPlanChanged={onPlanChanged} onDeselect={onDeselect} onOpenLog={onOpenLog} />);
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(screen.getByLabelText('想怎么改'), '  {Enter}');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('closes a chip by taking that thing out of the selection, and opens the whole conversation on request', async () => {
    show([{ kind: 'actor', name: '林夏' }]);
    await userEvent.click(screen.getByRole('button', { name: '不再指定 林夏' }));
    expect(onDeselect).toHaveBeenCalledWith({ kind: 'actor', name: '林夏' });
    await userEvent.click(screen.getByRole('button', { name: '打开完整对话' }));
    expect(onOpenLog).toHaveBeenCalledTimes(1);
  });

  it('folds a long selection into a count', () => {
    show(['甲', '乙', '丙', '丁', '戊', '己'].map(name => ({ kind: 'actor', name })));
    expect(screen.getByText('+2')).toBeTruthy();
    expect(screen.queryByText('戊')).toBeNull();
  });
});
