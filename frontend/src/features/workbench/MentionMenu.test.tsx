// @vitest-environment jsdom
import { useRef, useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { notifyAssetsChanged } from '../elements/assetEvents';
import type { MentionCandidate } from './mentionAutocomplete';
import { MentionMenu } from './MentionMenu';
import { clearMentionCandidatesCache, useMentionCandidates } from './useMentionCandidates';
import { useMentionInput } from './useMentionInput';

const CANDIDATES: MentionCandidate[] = [
  { name: '林秋', kind: 'actor' },
  { name: '林夏', kind: 'actor', thumbUrl: '/media/linxia.png' },
  { name: '林家祠堂', kind: 'scene' },
  { name: '铜镜', kind: 'prop' },
];

function Harness({ candidates = CANDIDATES, initial = '' }: { candidates?: MentionCandidate[]; initial?: string }) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const mention = useMentionInput({ value, onChange: setValue, candidates, inputRef: ref });
  return (
    <div style={{ position: 'relative' }}>
      <textarea ref={ref} aria-label="提示词" {...mention.inputProps} value={value}
        onChange={event => setValue(event.target.value)} onKeyDown={event => { mention.onKeyDown(event); }} />
      <MentionMenu {...mention.menuProps} />
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearMentionCandidatesCache();
});

describe('mention menu', () => {
  it('filters on @林, moves with ArrowDown and inserts @[林夏] on Enter', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const field = screen.getByLabelText('提示词') as HTMLTextAreaElement;
    await user.type(field, '镜头里@林');
    expect(screen.getAllByRole('option').map(option => option.textContent)).toEqual(['林秋数字演员', '林夏数字演员', '林家祠堂拍摄场地']);
    expect(field.getAttribute('aria-expanded')).toBe('true');
    expect(field.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[0].id);
    expect(screen.getAllByRole('option')[1].querySelector('img')?.getAttribute('src')).toContain('/media/linxia.png');

    await user.keyboard('{ArrowDown}');
    expect(field.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[1].id);
    await user.keyboard('{Enter}');
    expect(field.value).toBe('镜头里@[林夏] ');
    expect(field.selectionStart).toBe(field.value.length);
    expect(screen.queryByRole('listbox')).toBeNull();

    await user.keyboard('回头');
    expect(field.value).toBe('镜头里@[林夏] 回头');
  });

  it('shows the empty state, closes on Escape and picks with the mouse', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const field = screen.getByLabelText('提示词') as HTMLTextAreaElement;
    await user.type(field, '@无此人');
    expect(screen.getByText('没有匹配的人物、场景或道具')).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();

    await user.clear(field);
    await user.type(field, '@铜');
    await user.click(screen.getByRole('option', { name: /铜镜/ }));
    expect(field.value).toBe('@[铜镜] ');
    expect(document.activeElement).toBe(field);
  });

  it('leaves keys alone while an IME is composing', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const field = screen.getByLabelText('提示词') as HTMLTextAreaElement;
    await user.type(field, '@林');
    fireEvent.keyDown(field, { key: 'Enter', keyCode: 229 });
    fireEvent.keyDown(field, { key: 'Enter', isComposing: true });
    expect(field.value).toBe('@林');
    expect(screen.getByRole('listbox')).toBeTruthy();
  });

  it('does not open for an email address', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText('提示词'), 'a@b');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});

function CandidatesProbe({ taskId }: { taskId?: string }) {
  const { items, loading, error } = useMentionCandidates(taskId);
  return <p data-testid="probe">{loading ? 'loading' : error || items.map(item => `${item.kind}:${item.name}`).join(',')}</p>;
}

function mentionableResponse(items: unknown[]) {
  return new Response(JSON.stringify({ items }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

describe('useMentionCandidates', () => {
  it('does not fetch without a task id', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(<CandidatesProbe />);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('loads once per task, shares the cache and refetches when assets change', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(mentionableResponse([
        { name: '林夏', kind: 'actor', element_id: 'e1', aliases: ['阿夏'], description: '', thumb_url: '/media/a.png' },
        { name: '坏[名]', kind: 'prop' },
      ]))
      .mockResolvedValueOnce(mentionableResponse([{ name: '林夏', kind: 'actor' }, { name: '铜镜', kind: 'prop' }]));
    vi.stubGlobal('fetch', fetchMock);

    const view = render(<CandidatesProbe taskId="t 1" />);
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('actor:林夏'));
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/drama/t%201/mentionable?q=&limit=');

    view.rerender(<><CandidatesProbe taskId="t 1" /><CandidatesProbe taskId="t 1" /></>);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => notifyAssetsChanged({ reason: 'create', kind: 'prop', name: '铜镜' }));
    await waitFor(() => expect(screen.getAllByTestId('probe')[0].textContent).toBe('actor:林夏,prop:铜镜'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
