// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasZoomControls, type CanvasZoomControlsProps } from './CanvasZoomControls';

afterEach(cleanup);

function setup(overrides: Partial<CanvasZoomControlsProps> = {}) {
  const props: CanvasZoomControlsProps = {
    zoom: 0.8,
    onZoomTo: vi.fn(),
    onStep: vi.fn(),
    onFitAll: vi.fn(),
    onFitSelection: vi.fn(),
    hasSelection: false,
    ...overrides,
  };
  render(<CanvasZoomControls {...props} />);
  return props;
}

describe('CanvasZoomControls', () => {
  it('shows the zoom as a percent and steps in and out', () => {
    const props = setup();
    expect(screen.getByRole('button', { name: '精确缩放' }).textContent).toBe('80%');
    fireEvent.click(screen.getByRole('button', { name: '放大' }));
    fireEvent.click(screen.getByRole('button', { name: '缩小' }));
    expect(props.onStep).toHaveBeenNthCalledWith(1, 1);
    expect(props.onStep).toHaveBeenNthCalledWith(2, -1);
  });

  it('fits the canvas, and fits the selection only when there is one', () => {
    const props = setup();
    fireEvent.click(screen.getByRole('button', { name: '适应画布' }));
    expect(props.onFitAll).toHaveBeenCalledTimes(1);
    const fitSelection = screen.getByRole('button', { name: '适应选区' }) as HTMLButtonElement;
    expect(fitSelection.disabled).toBe(true);
    cleanup();
    const withSelection = setup({ hasSelection: true });
    fireEvent.click(screen.getByRole('button', { name: '适应选区' }));
    expect(withSelection.onFitSelection).toHaveBeenCalledTimes(1);
  });

  it('opens a popover with a 5–250% slider and presets', () => {
    const props = setup();
    const toggle = screen.getByRole('button', { name: '精确缩放' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const slider = screen.getByRole('slider', { name: '缩放比例' }) as HTMLInputElement;
    expect(slider.min).toBe('5');
    expect(slider.max).toBe('250');
    expect(slider.value).toBe('80');
    fireEvent.change(slider, { target: { value: '150' } });
    expect(props.onZoomTo).toHaveBeenLastCalledWith(1.5);
    for (const label of ['25%', '50%', '100%', '200%']) screen.getByRole('button', { name: label });
    fireEvent.click(screen.getByRole('button', { name: '200%' }));
    expect(props.onZoomTo).toHaveBeenLastCalledWith(2);
  });

  it('closes the popover on Escape and on a click outside', () => {
    setup();
    const toggle = screen.getByRole('button', { name: '精确缩放' });
    fireEvent.click(toggle);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('slider')).toBeNull();
    fireEvent.click(toggle);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('disables stepping past the zoom limits and hides fit selection without a handler', () => {
    setup({ zoom: 2.5, onFitSelection: undefined });
    expect((screen.getByRole('button', { name: '放大' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: '适应选区' })).toBeNull();
  });
});
