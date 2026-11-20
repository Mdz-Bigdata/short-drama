// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasSelectionToolbar, type CanvasSelectionToolbarProps } from './CanvasSelectionToolbar';

afterEach(cleanup);

function mount(overrides: Partial<CanvasSelectionToolbarProps> = {}) {
  const props: CanvasSelectionToolbarProps = {
    rect: { x: 100, y: 200, width: 400, height: 300 }, count: 3,
    onAlign: vi.fn(), onDistribute: vi.fn(), onArrange: vi.fn(), onGroup: vi.fn(), onDuplicate: vi.fn(), onDelete: vi.fn(), ...overrides,
  };
  render(<CanvasSelectionToolbar {...props} />);
  return props;
}

describe('CanvasSelectionToolbar', () => {
  it('sits centred above the selection', () => {
    mount();
    const bar = screen.getByRole('toolbar', { name: '选区工具栏' });
    expect(bar.style.left).toBe('300px');
    expect(bar.style.top).toBe('190px');
    expect(bar.className).not.toContain('is-below');
    expect(bar.textContent).toContain('已选 3 个');
  });

  it('drops below when there is no room above', () => {
    mount({ rect: { x: 0, y: 20, width: 100, height: 100 } });
    const bar = screen.getByRole('toolbar');
    expect(bar.className).toContain('is-below');
    expect(bar.style.top).toBe('130px');
  });

  it('runs each action with its kind', () => {
    const props = mount();
    fireEvent.click(screen.getByRole('button', { name: '左对齐' }));
    fireEvent.click(screen.getByRole('button', { name: '垂直居中' }));
    fireEvent.click(screen.getByRole('button', { name: '水平等距' }));
    fireEvent.click(screen.getByRole('button', { name: '宫格排列' }));
    fireEvent.click(screen.getByRole('button', { name: '按连线整理' }));
    fireEvent.click(screen.getByRole('button', { name: '散开重叠' }));
    fireEvent.click(screen.getByRole('button', { name: '成组' }));
    fireEvent.click(screen.getByRole('button', { name: '就地复制' }));
    fireEvent.click(screen.getByRole('button', { name: '删除所选' }));
    expect(props.onAlign).toHaveBeenNthCalledWith(1, 'left');
    expect(props.onAlign).toHaveBeenNthCalledWith(2, 'vcenter');
    expect(props.onDistribute).toHaveBeenCalledWith('horizontal');
    expect(props.onArrange).toHaveBeenNthCalledWith(1, 'grid');
    expect(props.onArrange).toHaveBeenNthCalledWith(2, 'edges');
    expect(props.onArrange).toHaveBeenNthCalledWith(3, 'spread');
    expect(props.onGroup).toHaveBeenCalledOnce();
    expect(props.onDuplicate).toHaveBeenCalledOnce();
    expect(props.onDelete).toHaveBeenCalledOnce();
  });

  it('labels every button for its tooltip and disables distribute below three', () => {
    mount({ count: 2 });
    for (const label of ['左对齐', '水平居中', '右对齐', '顶对齐', '垂直居中', '底对齐', '横向排列', '纵向排列']) {
      expect(screen.getByRole('button', { name: label }).getAttribute('data-tip')).toBe(label);
    }
    expect((screen.getByRole('button', { name: '水平等距' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '垂直等距' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '左对齐' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows 解组 only when it can ungroup, and keeps presses from the canvas', () => {
    const outside = vi.fn();
    const onUngroup = vi.fn();
    const { container } = render(<div onPointerDown={outside}><CanvasSelectionToolbar rect={{ x: 0, y: 100, width: 10, height: 10 }} count={1} onAlign={vi.fn()} onDistribute={vi.fn()} onArrange={vi.fn()} onGroup={vi.fn()} onUngroup={onUngroup} onDuplicate={vi.fn()} onDelete={vi.fn()} /></div>);
    fireEvent.click(screen.getByRole('button', { name: '解组' }));
    expect(onUngroup).toHaveBeenCalledOnce();
    expect((screen.getByRole('button', { name: '成组' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.pointerDown(container.querySelector('.cst-button')!);
    expect(outside).not.toHaveBeenCalled();
    cleanup();
    mount();
    expect(screen.queryByRole('button', { name: '解组' })).toBeNull();
  });
});
