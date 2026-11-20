// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasBatchConnectDialog } from './CanvasBatchConnectDialog';

afterEach(cleanup);

const TARGETS = [{ id: 'vid', label: '成片', inputs: 0 }, { id: 'vid2', label: '镜头 2 视频', inputs: 3 }];

function open(overrides: Partial<Parameters<typeof CanvasBatchConnectDialog>[0]> = {}) {
  const props = { count: 4, targets: TARGETS, onConfirm: vi.fn(), onClose: vi.fn(), ...overrides };
  render(<CanvasBatchConnectDialog {...props} />);
  return props;
}

describe('picking the video node for a batch connect', () => {
  it('lists the board\'s video nodes by name, the first one picked, and a new one last', () => {
    open();
    expect(screen.getByRole('dialog', { name: '连到视频节点' })).toBeTruthy();
    expect(screen.getByText(/把选中的 4 个图片 \/ 视频节点/)).toBeTruthy();
    const choices = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(choices.map(choice => choice.closest('li')!.querySelector('strong')!.textContent)).toEqual(['成片', '镜头 2 视频', '新建视频节点']);
    expect(choices.map(choice => choice.checked)).toEqual([true, false, false]);
    expect(screen.getByText('还没有输入')).toBeTruthy();
    expect(screen.getByText('已有 3 条输入')).toBeTruthy();
  });

  it('answers the picked node', () => {
    const props = open();
    fireEvent.click(screen.getByRole('radio', { name: '镜头 2 视频' }));
    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    expect(props.onConfirm).toHaveBeenCalledWith('vid2');
  });

  it('answers null for a new video node', () => {
    const props = open();
    fireEvent.click(screen.getByRole('radio', { name: '新建视频节点' }));
    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    expect(props.onConfirm).toHaveBeenCalledWith(null);
  });

  it('with no video node on the board, a new one is what is offered', () => {
    const props = open({ targets: [] });
    const choices = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(choices).toHaveLength(1);
    expect(choices[0].checked).toBe(true);
    fireEvent.submit(screen.getByRole('dialog'));
    expect(props.onConfirm).toHaveBeenCalledWith(null);
  });

  it('closes on Escape and 取消 without connecting', () => {
    const props = open();
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(props.onClose).toHaveBeenCalledTimes(2);
    expect(props.onConfirm).not.toHaveBeenCalled();
  });
});
