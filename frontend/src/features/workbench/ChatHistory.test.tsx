// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ChatHistory } from './ChatHistory';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function setHeight(element: HTMLElement, scrollHeight: number, clientHeight = 300) {
  Object.defineProperty(element, 'scrollHeight', { configurable: true, value: scrollHeight });
  Object.defineProperty(element, 'clientHeight', { configurable: true, value: clientHeight });
}

describe('reader-controlled chat history', () => {
  it('follows new messages only while the reader is close to the bottom', () => {
    const view = render(<ChatHistory><p>旧消息</p></ChatHistory>);
    const log = screen.getByRole('log', { name: '对话历史' });
    setHeight(log, 1000);
    log.scrollTop = 690;
    fireEvent.scroll(log);
    setHeight(log, 1200);
    view.rerender(<ChatHistory><p>旧消息</p><p>新消息</p></ChatHistory>);
    expect(log.scrollTop).toBe(1200);
    expect(screen.queryByRole('button', { name: '回到最新消息' })).toBeNull();
  });
  it('preserves the reader position when messages or progress change and resumes on demand', async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });
    const view = render(<ChatHistory><p>旧消息</p></ChatHistory>);
    const log = screen.getByRole('log', { name: '对话历史' });
    setHeight(log, 1000);
    log.scrollTop = 180;
    fireEvent.scroll(log);
    setHeight(log, 1200);
    view.rerender(<ChatHistory><p>旧消息</p><p>进度更新与新消息</p></ChatHistory>);
    expect(log.scrollTop).toBe(180);
    expect(scrollIntoView).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '回到最新消息' }));
    expect(log.scrollTop).toBe(1200);
    setHeight(log, 1400);
    view.rerender(<ChatHistory><p>再次更新</p></ChatHistory>);
    expect(log.scrollTop).toBe(1400);
  });
  it('resets following when a different project opens', () => {
    const view = render(<ChatHistory key="a"><p>项目 A</p></ChatHistory>);
    const log = screen.getByRole('log');
    setHeight(log, 1000);
    log.scrollTop = 50;
    fireEvent.scroll(log);
    expect(screen.getByRole('button', { name: '回到最新消息' })).toBeTruthy();
    view.rerender(<ChatHistory key="b"><p>项目 B</p></ChatHistory>);
    expect(screen.queryByRole('button', { name: '回到最新消息' })).toBeNull();
    expect(screen.getByRole('log').tabIndex).toBe(0);
  });
  it('constrains the sidebar and keeps the composer outside the shrinking scroll area', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/features/workbench/ChatHistory.css'), 'utf8');
    expect(css).toContain('grid-template-rows: minmax(0, 1fr)');
    expect(css).toMatch(/#workbench-chat-sidebar\s*\{[^}]*min-height: 0;[^}]*overflow: hidden/);
    expect(css).toMatch(/\.chat-sidebar__composer\s*\{[^}]*flex: 0 0 auto/);
    expect(css).toContain('height: min(640px, 100dvh)');
  });
});
