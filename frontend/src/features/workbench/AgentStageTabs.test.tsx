// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AgentStageTabs } from './AgentStageTabs';


describe('AgentStageTabs', () => {
  afterEach(cleanup);

  it('renders the seven agent tabs with one shared background treatment', () => {
    const onChange = vi.fn();
    render(<AgentStageTabs activeStage={3} onChange={onChange} />);

    const tabs = screen.getAllByRole('button');
    expect(tabs).toHaveLength(7);
    expect(tabs.every(tab => tab.classList.contains('agent-stage-tab'))).toBe(true);
    expect(screen.getByRole('button', { name: '3.角色' }).getAttribute('aria-current')).toBe('step');

    fireEvent.click(screen.getByRole('button', { name: '4.分镜' }));
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it('shows sound and final cut as one 剪辑合成师 tab, current on either stage', () => {
    const onChange = vi.fn();
    const { rerender } = render(<AgentStageTabs activeStage={6} onChange={onChange} />);
    const editor = screen.getByRole('button', { name: '6.剪辑合成师' });
    expect(editor.getAttribute('aria-current')).toBe('step');
    rerender(<AgentStageTabs activeStage={7} onChange={onChange} />);
    expect(editor.getAttribute('aria-current')).toBe('step');
    expect(screen.queryByRole('button', { name: /音频|合成$/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '7.宣发' }));
    expect(onChange).toHaveBeenCalledWith(8);
    fireEvent.click(editor);
    expect(onChange).toHaveBeenLastCalledWith(6);
  });

  describe('when the strip is too narrow for all the tabs', () => {
    // jsdom lays nothing out: the strip is 300px wide and each tab 80px, side by side.
    function layOutNarrowStrip() {
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        if (this.classList.contains('agent-stage-tabs')) return new DOMRect(100, 0, 300, 26);
        const index = [...(this.parentElement?.children ?? [])].indexOf(this);
        const scrolled = this.parentElement?.scrollLeft ?? 0;
        return new DOMRect(100 + index * 80 - scrolled, 0, 80, 26);
      });
    }

    afterEach(() => vi.restoreAllMocks());

    it('scrolls only the strip to bring the active tab into view', () => {
      layOutNarrowStrip();
      const scrollIntoView = vi.fn();
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });

      const { rerender } = render(<AgentStageTabs activeStage={1} onChange={vi.fn()} />);
      const strip = screen.getByRole('navigation', { name: '制作 Agent' });
      expect(strip.scrollLeft).toBe(0);

      // The last tab (stage 8) spans 580..660 against a strip ending at 400.
      rerender(<AgentStageTabs activeStage={8} onChange={vi.fn()} />);
      expect(strip.scrollLeft).toBeGreaterThanOrEqual(260);

      rerender(<AgentStageTabs activeStage={1} onChange={vi.fn()} />);
      expect(strip.scrollLeft).toBeLessThanOrEqual(0);
      // The surrounding page must not move with it.
      expect(scrollIntoView).not.toHaveBeenCalled();
    });

    it('leaves the strip where it is when the active tab is already visible', () => {
      layOutNarrowStrip();

      const { rerender } = render(<AgentStageTabs activeStage={1} onChange={vi.fn()} />);
      rerender(<AgentStageTabs activeStage={3} onChange={vi.fn()} />);

      expect(screen.getByRole('navigation', { name: '制作 Agent' }).scrollLeft).toBe(0);
    });
  });
});
