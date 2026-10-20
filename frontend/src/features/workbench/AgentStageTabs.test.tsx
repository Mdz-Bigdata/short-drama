// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AgentStageTabs } from './AgentStageTabs';


describe('AgentStageTabs', () => {
  afterEach(cleanup);

  it('renders all eight agents with one shared background treatment', () => {
    const onChange = vi.fn();
    render(<AgentStageTabs activeStage={3} onChange={onChange} />);

    const tabs = screen.getAllByRole('button');
    expect(tabs).toHaveLength(8);
    expect(tabs.every(tab => tab.classList.contains('agent-stage-tab'))).toBe(true);
    expect(screen.getByRole('button', { name: '3.角色' }).getAttribute('aria-current')).toBe('step');

    fireEvent.click(screen.getByRole('button', { name: '4.分镜' }));
    expect(onChange).toHaveBeenCalledWith(4);
  });
});
