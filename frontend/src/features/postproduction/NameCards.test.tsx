// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NameCards } from './NameCards';
import type { StudioClip } from './postProduction';

const clip = (over: Partial<StudioClip>): StudioClip => ({
  shot_id: 1, shot_uid: 100101, scene_id: 'E1S01', video_url: '/media/a.mp4', candidates: [], duration: 8, in: 0, out: null, muted: false,
  subtitle: '', voice_path: null, transition_in: null, review: { decision: 'pending', note: '', decided_at: null }, ...over,
});

const first = clip({ name_cards: [{ name: '石砚', identity: '外门杂役', side: 'right', at: 0.6, slot: 0 }] });
const second = clip({
  shot_uid: 100201, scene_id: 'E1S02',
  name_cards: [{ name: '阿禾', identity: '丹房帮工少女', side: 'left', at: 0.6, slot: 0, unsure: true }],
});

afterEach(cleanup);

describe('NameCards', () => {
  it('lists who is introduced where, and flags a card whose place was a guess', () => {
    render(<NameCards clips={[first, second]} enabled busy={false} onChange={vi.fn()} />);

    expect(screen.getByDisplayValue('石砚')).toBeTruthy();
    expect(screen.getByDisplayValue('丹房帮工少女')).toBeTruthy();
    expect(screen.getAllByText('请核对位置')).toHaveLength(1);
    expect(screen.getByText(/E1S02/)).toBeTruthy();
  });

  it('sends the whole clip back when a card changes, without the derived fields', () => {
    const onChange = vi.fn();
    render(<NameCards clips={[first, second]} enabled busy={false} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: '阿禾 的字幕在画面哪一侧' }));
    expect(onChange).toHaveBeenLastCalledWith(second, [{ name: '阿禾', identity: '丹房帮工少女', side: 'right', at: 0.6 }]);

    const identity = screen.getByLabelText('石砚 的身份');
    fireEvent.change(identity, { target: { value: '绝灵体' } });
    fireEvent.blur(identity);
    expect(onChange).toHaveBeenLastCalledWith(first, [{ name: '石砚', identity: '绝灵体', side: 'right', at: 0.6 }]);
  });

  it('leaves the card alone when a field is left unchanged or the name is emptied', () => {
    const onChange = vi.fn();
    render(<NameCards clips={[first]} enabled busy={false} onChange={onChange} />);

    const name = screen.getByDisplayValue('石砚') as HTMLInputElement;
    fireEvent.blur(name);
    fireEvent.change(name, { target: { value: '  ' } });
    fireEvent.blur(name);

    expect(onChange).not.toHaveBeenCalled();
    expect(name.value).toBe('石砚');
  });

  it('removes one card with an empty list, which means this clip shows none', () => {
    const onChange = vi.fn();
    render(<NameCards clips={[first]} enabled busy={false} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: '删除 石砚 的出场字幕' }));
    expect(onChange).toHaveBeenCalledWith(first, []);
  });

  it('adds a card to the clip under the playhead and hands an edited clip back to automatic', () => {
    const onChange = vi.fn();
    const edited = { ...first, name_cards_edited: true };
    render(<NameCards clips={[edited, second]} current={second} enabled busy={false} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /给 E1S02 · 镜头 1 加一条/ }));
    expect(onChange).toHaveBeenLastCalledWith(second, [
      { name: '阿禾', identity: '丹房帮工少女', side: 'left', at: 0.6 }, { name: '姓名', identity: '', side: 'right', at: 0.6 },
    ]);

    fireEvent.click(screen.getByRole('button', { name: /E1S01 · 镜头 1 恢复自动/ }));
    expect(onChange).toHaveBeenLastCalledWith(edited, undefined);
  });

  it('says so when the switch is off or nobody is new', () => {
    render(<NameCards clips={[clip({})]} enabled={false} busy={false} onChange={vi.fn()} />);

    expect(screen.getByText(/已在基础设定里关掉/)).toBeTruthy();
    expect(screen.getByText('这一集没有第一次出场的人物。')).toBeTruthy();
    expect((screen.getByRole('button', { name: '加一条' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
