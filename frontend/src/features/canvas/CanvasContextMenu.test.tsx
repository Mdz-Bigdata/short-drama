// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasContextMenu } from './CanvasContextMenu';
import type { MenuItem } from './canvasMenus';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function items(handlers: Record<string, () => void> = {}): MenuItem[] {
  const on = (id: string) => handlers[id] ?? (() => undefined);
  return [
    { id: 'copy', label: '复制', shortcut: '⌘C', onSelect: on('copy') },
    { id: 'paste', label: '粘贴', disabled: true, onSelect: on('paste') },
    'separator',
    { id: 'align', label: '对齐', submenu: [
      { id: 'align:left', label: '左对齐', onSelect: on('align:left') },
      { id: 'align:right', label: '右对齐', onSelect: on('align:right') },
    ] },
    { id: 'delete', label: '删除', danger: true, onSelect: on('delete') },
  ];
}

const focused = () => (document.activeElement as HTMLElement | null)?.textContent ?? '';

describe('CanvasContextMenu', () => {
  it('shows labels, shortcuts, separators and danger items, and focuses the first item', () => {
    render(<CanvasContextMenu x={10} y={20} items={items()} onClose={vi.fn()} />);
    const menu = screen.getByRole('menu', { name: '右键菜单' });
    expect(menu.style.left).toBe('10px');
    expect(menu.style.top).toBe('20px');
    expect(screen.getByRole('menuitem', { name: /复制/ }).textContent).toContain('⌘C');
    expect(screen.getAllByRole('separator')).toHaveLength(1);
    expect(screen.getByRole('menuitem', { name: '删除' }).className).toContain('is-danger');
    expect(focused()).toContain('复制');
  });

  it('runs an item on click and closes', () => {
    const copy = vi.fn();
    const onClose = vi.fn();
    render(<CanvasContextMenu x={0} y={0} items={items({ copy })} onClose={onClose} />);
    fireEvent.click(screen.getByRole('menuitem', { name: /复制/ }));
    expect(copy).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('never runs a disabled item', () => {
    const paste = vi.fn();
    const onClose = vi.fn();
    render(<CanvasContextMenu x={0} y={0} items={items({ paste })} onClose={onClose} />);
    fireEvent.click(screen.getByRole('menuitem', { name: '粘贴' }));
    expect(paste).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('moves with the arrows past separators and disabled items, wrapping, and runs on Enter', () => {
    const remove = vi.fn();
    const onClose = vi.fn();
    render(<CanvasContextMenu x={0} y={0} items={items({ delete: remove })} onClose={onClose} />);
    const menu = screen.getByRole('menu');
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(focused()).toBe('对齐');
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(focused()).toBe('删除');
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(focused()).toContain('复制');
    fireEvent.keyDown(menu, { key: 'ArrowUp' });
    expect(focused()).toBe('删除');
    fireEvent.keyDown(menu, { key: 'Home' });
    expect(focused()).toContain('复制');
    fireEvent.keyDown(menu, { key: 'End' });
    fireEvent.keyDown(menu, { key: 'Enter' });
    expect(remove).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('opens a submenu from the keyboard, walks it, and goes back with ArrowLeft or Esc', () => {
    const left = vi.fn();
    const right = vi.fn();
    const onClose = vi.fn();
    render(<CanvasContextMenu x={0} y={0} items={items({ 'align:left': left, 'align:right': right })} onClose={onClose} />);
    const menu = screen.getByRole('menu', { name: '右键菜单' });
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    fireEvent.keyDown(menu, { key: 'ArrowRight' });
    const submenu = screen.getByRole('menu', { name: '对齐' });
    expect(screen.getByRole('menuitem', { name: '对齐' }).getAttribute('aria-expanded')).toBe('true');
    expect(focused()).toBe('左对齐');
    fireEvent.keyDown(submenu, { key: 'ArrowLeft' });
    expect(screen.queryByRole('menu', { name: '对齐' })).toBeNull();
    expect(focused()).toBe('对齐');
    fireEvent.keyDown(menu, { key: 'Enter' });
    fireEvent.keyDown(screen.getByRole('menu', { name: '对齐' }), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole('menu', { name: '对齐' })).toBeNull();
    fireEvent.keyDown(menu, { key: 'ArrowRight' });
    const again = screen.getByRole('menu', { name: '对齐' });
    fireEvent.keyDown(again, { key: 'ArrowDown' });
    fireEvent.keyDown(again, { key: 'Enter' });
    expect(right).toHaveBeenCalledOnce();
    expect(left).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('opens a submenu on hover without taking focus, and runs its items on click', () => {
    const left = vi.fn();
    render(<CanvasContextMenu x={0} y={0} items={items({ 'align:left': left })} onClose={vi.fn()} />);
    fireEvent.pointerEnter(screen.getByRole('menuitem', { name: '对齐' }));
    expect(screen.getByRole('menu', { name: '对齐' })).toBeTruthy();
    expect(focused()).toBe('对齐');
    fireEvent.click(screen.getByRole('menuitem', { name: '左对齐' }));
    expect(left).toHaveBeenCalledOnce();
  });

  it('closes on Esc and on a press outside, not on a press inside', () => {
    const onClose = vi.fn();
    render(<div><button type="button">outside</button><CanvasContextMenu x={0} y={0} items={items()} onClose={onClose} /></div>);
    fireEvent.pointerDown(screen.getByRole('menuitem', { name: '删除' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.pointerDown(screen.getByRole('button', { name: 'outside' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('stays inside the viewport', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 200, bottom: 300, width: 200, height: 300, toJSON: () => ({}) } as DOMRect);
    const width = window.innerWidth;
    const height = window.innerHeight;
    act(() => { Object.assign(window, { innerWidth: 1000, innerHeight: 800 }); });
    try {
      render(<CanvasContextMenu x={950} y={700} items={items()} onClose={vi.fn()} />);
      const menu = screen.getByRole('menu');
      expect(menu.style.left).toBe('792px');
      expect(menu.style.top).toBe('492px');
    } finally {
      Object.assign(window, { innerWidth: width, innerHeight: height });
    }
  });
});
