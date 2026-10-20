// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WorkflowSnapshot } from '../../types';
import { WorkflowActions } from './WorkflowGuide';

const workflow: WorkflowSnapshot = {
  stages: Array.from({ length: 8 }, (_, index) => ({ stage: index + 1, label: `Agent ${index + 1}`, state: index < 3 ? 'complete' : 'pending', missing: [], guidance: '按流程继续' })),
  next_stage: 4, active_stage: null, completed_stages: [1, 2, 3], production_complete: false,
  release_ready: false, mode: 'ready', hint: '继续制作分镜', event_id: 'partial-4',
  actions: [{ kind: 'continue', label: '继续第 4 阶段', message: '继续' }],
};

afterEach(cleanup);
describe('main-area WorkflowActions', () => {
  it('dispatches the server action with keyboard without rendering a stage card', async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(<WorkflowActions workflow={workflow} busy={false} onAction={onAction} />);
    expect(screen.queryByRole('region', { name: '八大 Agent 流程引导' })).toBeNull();
    const button = screen.getByRole('button', { name: '继续第 4 阶段' });
    button.focus();
    await user.keyboard('{Enter}');
    expect(onAction).toHaveBeenCalledWith('继续');
  });
  it('does not invent a continue button while review is pending', () => {
    render(<WorkflowActions workflow={{ ...workflow, mode: 'review', next_stage: null, actions: [{ kind: 'status', label: '查看验收要求', message: '进度' }] }} busy={false} onAction={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /继续/ })).toBeNull();
    expect(screen.getByRole('button', { name: '查看验收要求' })).toBeTruthy();
  });
  it('disables repeated commands while a chat request is pending', () => {
    render(<WorkflowActions workflow={workflow} busy onAction={vi.fn()} />);
    expect(screen.getByRole('button', { name: '继续第 4 阶段' }).hasAttribute('disabled')).toBe(true);
  });
});
