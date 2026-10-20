// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatComposer } from './ChatComposer';

function Harness({ busy = false, onSend = vi.fn() }: { busy?: boolean; onSend?: (message: string) => void }) {
  const [value, setValue] = useState('');
  return <ChatComposer value={value} busy={busy} onChange={setValue} onSend={message => { onSend(message); setValue(''); }} />;
}
afterEach(cleanup);

describe('slash command composer', () => {
  it('opens every command for slash without sending the slash itself', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/');
    expect(screen.getAllByRole('option')).toHaveLength(11);
    expect(screen.getByRole('combobox').getAttribute('aria-expanded')).toBe('true');
    await user.keyboard('{Enter}');
    expect(onSend).not.toHaveBeenCalled();
  });
  it('navigates with arrows and executes the selected canonical command on Enter', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/');
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(onSend).toHaveBeenCalledExactlyOnceWith('/resume');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
  it('supports Chinese search and starts automatic production with one explicit selection', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/一键成片');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByText(/无需逐步确认/)).toBeTruthy();
    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledExactlyOnceWith('/auto');
  });
  it('supports English search and pointer selection', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/com');
    await user.click(screen.getByRole('option', { name: /合成视频/ }));
    expect(onSend).toHaveBeenCalledExactlyOnceWith('/compose');
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
  });
  it('retains the highlighted command when the send button is clicked', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/');
    await user.keyboard('{ArrowDown}');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    expect(onSend).toHaveBeenCalledExactlyOnceWith('/pause');
  });
  it('closes on Escape and leaves unknown commands unsent', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/');
    await user.keyboard('{ArrowDown}{Escape}{Enter}');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
    await user.type(screen.getByRole('combobox'), 'not-a-command');
    expect(screen.getByText(/没有匹配的命令/)).toBeTruthy();
    await user.keyboard('{Enter}');
    expect(onSend).not.toHaveBeenCalled();
  });
  it('does not submit commands while another message is pending or IME is composing', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    const view = render(<Harness busy onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '/pause');
    await user.keyboard('{Enter}');
    expect(onSend).not.toHaveBeenCalled();
    view.rerender(<Harness onSend={onSend} />);
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter', isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledExactlyOnceWith('/pause');
  });
  it('continues to send ordinary natural-language messages', async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    await user.type(screen.getByRole('textbox'), '现在做到哪一步了？{Enter}');
    expect(onSend).toHaveBeenCalledExactlyOnceWith('现在做到哪一步了？');
  });
});
