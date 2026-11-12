// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasSearchDialog } from './CanvasSearchDialog';
import { newNode } from './canvasGraph';
import type { CanvasNode } from './canvasTypes';

const nodes: CanvasNode[] = [
  { ...newNode('note', 0, 0, { label: '雨夜开场' }), id: 'a' },
  { ...newNode('image_gen', 0, 0, { label: '定妆', prompt: '雨夜 街头 霓虹' }), id: 'b' },
  { ...newNode('video_gen', 0, 0, { label: '追逐' }), id: 'c' },
];

afterEach(cleanup);

function setup() {
  const onJump = vi.fn();
  const onClose = vi.fn();
  const view = render(<CanvasSearchDialog open nodes={nodes} onJump={onJump} onClose={onClose} />);
  const input = screen.getByRole('combobox', { name: '搜索节点' });
  return { onJump, onClose, input, view };
}

describe('CanvasSearchDialog', () => {
  it('renders nothing while closed', () => {
    const { container } = render(<CanvasSearchDialog open={false} nodes={nodes} onJump={() => {}} onClose={() => {}} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows live results with a count and the match highlighted', () => {
    const { input } = setup();
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: '雨夜' } });
    expect(screen.getByText('2 个结果')).toBeTruthy();
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain('雨夜开场');
    expect(options[0].querySelector('mark')?.textContent).toBe('雨夜');
    expect(options[1].textContent).toContain('提示词');
    expect(options.map(option => option.getAttribute('aria-selected'))).toEqual(['true', 'false']);
    fireEvent.change(input, { target: { value: '没有这个' } });
    expect(screen.getByText('没有匹配的节点')).toBeTruthy();
  });

  it('moves with the arrows and jumps with Enter', () => {
    const { input, onJump, onClose } = setup();
    fireEvent.change(input, { target: { value: '雨夜' } });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getAllByRole('option')[0].getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onJump).toHaveBeenCalledWith('b');
    expect(onClose).toHaveBeenCalled();
  });

  it('jumps on click and closes with Esc or the backdrop', () => {
    const { input, onJump, onClose, view } = setup();
    fireEvent.change(input, { target: { value: '追逐' } });
    fireEvent.click(screen.getByRole('option'));
    expect(onJump).toHaveBeenCalledWith('c');
    onClose.mockClear();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.mouseDown(view.container.querySelector('.csd-backdrop')!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
