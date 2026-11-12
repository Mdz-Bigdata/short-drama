// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ColorField, NumberField } from './fields';

describe('ColorField', () => {
  afterEach(cleanup);

  it('sends nothing while the picker is being dragged, and the colour once when it is closed', () => {
    const onCommit = vi.fn();
    render(<ColorField label="颜色" value="#336699" onCommit={onCommit} />);
    const input = screen.getByLabelText('颜色') as HTMLInputElement;
    // What a browser does during a drag inside the picker: `input` on every move.
    fireEvent.input(input, { target: { value: '#aa0000' } });
    fireEvent.input(input, { target: { value: '#bb0000' } });
    fireEvent.input(input, { target: { value: '#cc0000' } });
    expect(onCommit).not.toHaveBeenCalled();
    // …and `change` once, when the picker is dismissed.
    fireEvent.change(input, { target: { value: '#cc0000' } });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith('#cc0000');
  });

  it('sends nothing when the picker is closed on the colour it opened with', () => {
    const onCommit = vi.fn();
    render(<ColorField label="颜色" value="#336699" onCommit={onCommit} />);
    const input = screen.getByLabelText('颜色') as HTMLInputElement;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    fireEvent.blur(input);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('shows the colour the server answered with', () => {
    const { rerender } = render(<ColorField label="颜色" value="#336699" onCommit={() => {}} />);
    rerender(<ColorField label="颜色" value="#112233" onCommit={() => {}} />);
    expect((screen.getByLabelText('颜色') as HTMLInputElement).value).toBe('#112233');
  });
});

describe('NumberField', () => {
  afterEach(cleanup);

  it('sends on Enter and keeps focus in the field, so a Backspace right after edits the number and not the stage', async () => {
    const seen: EventTarget[] = [];
    const listen = (event: KeyboardEvent) => { if (event.key === 'Backspace' && event.target) seen.push(event.target); };
    window.addEventListener('keydown', listen);
    try {
      const onCommit = vi.fn();
      const { rerender } = render(<NumberField label="高（米）" value={1} min={0.05} max={50} onCommit={onCommit} />);
      const input = screen.getByLabelText('高（米）') as HTMLInputElement;
      await userEvent.clear(input);
      await userEvent.type(input, '25{Enter}');
      expect(onCommit.mock.calls).toEqual([[25]]);
      // The answer comes back as the new value: the same field, still focused, now showing it.
      rerender(<NumberField label="高（米）" value={25} min={0.05} max={50} onCommit={onCommit} />);
      expect(document.activeElement).toBe(input);
      expect(screen.getByLabelText('高（米）')).toBe(input);
      expect(input.value).toBe('25');
      // The desk skips a key typed into a field; one that reached the page would delete the selection.
      await userEvent.keyboard('{Backspace}');
      expect(input.value).toBe('2');
      expect(seen).toEqual([input]);
      // Leaving the field afterwards sends what is in it now, and only that.
      fireEvent.blur(input);
      expect(onCommit.mock.calls).toEqual([[25], [2]]);
    } finally {
      window.removeEventListener('keydown', listen);
    }
  });

  it('follows the value between sends, but never writes over what is being typed', async () => {
    const onCommit = vi.fn();
    const { rerender } = render(<NumberField label="X（米）" value={0} onCommit={onCommit} />);
    const input = screen.getByLabelText('X（米）') as HTMLInputElement;
    rerender(<NumberField label="X（米）" value={1.5} onCommit={onCommit} />);
    expect(input.value).toBe('1.5');

    await userEvent.clear(input);
    await userEvent.type(input, '3');
    // The playhead moves, or a queued edit is answered, while the director is typing.
    rerender(<NumberField label="X（米）" value={1.75} onCommit={onCommit} />);
    expect(input.value).toBe('3');
    expect(document.activeElement).toBe(input);
    await userEvent.keyboard('{Enter}');
    expect(onCommit.mock.calls).toEqual([[3]]);
  });

  it('clamps what it sends and shows what was sent; a blank or unchanged number sends nothing and shows the value again', async () => {
    const onCommit = vi.fn();
    render(<NumberField label="高（米）" value={1} min={0.05} max={50} onCommit={onCommit} />);
    const input = screen.getByLabelText('高（米）') as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, '900{Enter}');
    expect(onCommit.mock.calls).toEqual([[50]]);
    expect(input.value).toBe('50');
    await userEvent.clear(input);
    await userEvent.keyboard('{Enter}');
    expect(input.value).toBe('1');
    await userEvent.type(input, '{Enter}');
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it('sends a number once when Enter is followed by leaving the field, though the value it shows has not changed', async () => {
    // On a key the field shows the sampled value, which can stay put: −180° is drawn as 180°, a hundredth of a
    // millimetre rounds away. That send is one edit and one undo step, not one per key and one more on blur.
    const onCommit = vi.fn();
    render(<NumberField label="朝向（°）" value={180} min={-180} max={180} onCommit={onCommit} />);
    const input = screen.getByLabelText('朝向（°）') as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, '-180{Enter}');
    await userEvent.keyboard('{Enter}');
    fireEvent.blur(input);
    expect(onCommit.mock.calls).toEqual([[-180]]);
  });
});
