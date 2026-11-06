// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as api from './canvasApi';
import type { WorkflowPlan, WorkflowStatus } from './canvasApi';
import { WorkflowPanel } from './WorkflowPanel';
import { stepTakesWords, stepTypeLabel, withoutStep } from './workflowPlan';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const PLAN: WorkflowPlan = {
  title: '雨夜追车', summary: '三步', steps: [
    { ref: 'frame', kind: 'image_gen', label: '首帧', prompt: '雨夜街道', inputs: [] },
    { ref: 'clip', kind: 'video_gen', label: '追车', prompt: '车冲出巷口', inputs: [{ source: 'frame', role: 'first_frame' }] },
  ],
};

function status(partial: Partial<WorkflowStatus>): WorkflowStatus {
  return {
    id: 'wf1', canvas_id: 'main', brief: 'b', applied: false, plan: PLAN, problems: [], state: 'draft', can_apply: true, runnable: [],
    steps: PLAN.steps.map(step => ({ ref: step.ref, state: 'draft', node_id: '', error: '' })), created_at: '', updated_at: 'u1', ...partial,
  };
}

function mount(overrides: Partial<Parameters<typeof WorkflowPanel>[0]> = {}) {
  const props = {
    projectId: 'p', canvasId: 'main', refreshKey: '0', flush: vi.fn().mockResolvedValue(true), currentVersion: () => 7,
    onApplied: vi.fn().mockResolvedValue(undefined), onRun: vi.fn(), onJump: vi.fn(), ...overrides,
  };
  render(<WorkflowPanel {...props} />);
  return props;
}

async function open(current: WorkflowStatus, props: Partial<Parameters<typeof WorkflowPanel>[0]> = {}) {
  vi.spyOn(api, 'listWorkflows').mockResolvedValue({ workflows: [{ id: 'wf1', title: PLAN.title, applied: current.applied, steps: 2, brief: 'b', updated_at: '' }] });
  vi.spyOn(api, 'fetchWorkflow').mockResolvedValue(current);
  const mounted = mount(props);
  await screen.findByRole('option', { name: /雨夜追车/ });
  fireEvent.change(screen.getByLabelText('选择工作流'), { target: { value: 'wf1' } });
  await screen.findByRole('heading', { name: /雨夜追车/ });
  return mounted;
}

describe('planning', () => {
  it('sends the brief and shows the draft, and the note says nothing is spent yet on the canvas', async () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue({ workflows: [] });
    const made = status({});
    const plan = vi.spyOn(api, 'planWorkflow').mockResolvedValue(made);
    vi.spyOn(api, 'fetchWorkflow').mockResolvedValue(made);
    mount();
    expect(screen.getByText(/只出草稿，不改画布/)).toBeTruthy();
    const button = screen.getByRole('button', { name: '规划流程' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('创作需求'), { target: { value: ' 雨夜追车 ' } });
    fireEvent.click(button);
    await screen.findByRole('heading', { name: /雨夜追车/ });
    expect(plan).toHaveBeenCalledWith('p', 'main', '雨夜追车');
  });

  it('a refused plan shows why', async () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue({ workflows: [] });
    vi.spyOn(api, 'planWorkflow').mockRejectedValue(new Error('模型连续 3 次没有给出能用的流程'));
    mount();
    fireEvent.change(screen.getByLabelText('创作需求'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: '规划流程' }));
    expect((await screen.findByRole('alert')).textContent).toContain('连续 3 次');
  });
});

describe('the draft', () => {
  it('cannot go on the canvas while it has a blocking problem', async () => {
    await open(status({ can_apply: false, problems: [{ ref: 'clip', code: 'no_reference', message: 'clip 不做纯文生视频', blocking: true }] }));
    expect((screen.getByRole('button', { name: '铺到画布' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('clip 不做纯文生视频')).toBeTruthy();
  });

  it('saves the canvas first, then applies against that version and reloads the canvas', async () => {
    const applied = vi.spyOn(api, 'applyWorkflow').mockResolvedValue(status({ applied: true, state: 'ready', runnable: ['n1', 'n2'] }));
    const props = await open(status({}));
    fireEvent.click(screen.getByRole('button', { name: '铺到画布' }));
    await waitFor(() => expect(props.onApplied).toHaveBeenCalled());
    expect(props.flush).toHaveBeenCalled();
    expect(applied).toHaveBeenCalledWith('p', 'wf1', 7);
  });

  it('does not apply when the canvas could not be saved', async () => {
    const applied = vi.spyOn(api, 'applyWorkflow');
    await open(status({}), { flush: vi.fn().mockResolvedValue(false) });
    fireEvent.click(screen.getByRole('button', { name: '铺到画布' }));
    expect((await screen.findByRole('alert')).textContent).toContain('没保存成功');
    expect(applied).not.toHaveBeenCalled();
  });

  it('an edit is sent when it is finished, not on every key', async () => {
    const update = vi.spyOn(api, 'updateWorkflow').mockResolvedValue(status({}));
    await open(status({}));
    const box = screen.getByLabelText('首帧 的内容');
    fireEvent.change(box, { target: { value: '雪夜街道' } });
    expect(update).not.toHaveBeenCalled();
    fireEvent.blur(box);
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][2].steps[0].prompt).toBe('雪夜街道');
  });

  it('taking a step out takes it out of what read from it', () => {
    const next = withoutStep(PLAN, 'frame');
    expect(next.steps.map(step => step.ref)).toEqual(['clip']);
    expect(next.steps[0].inputs).toEqual([]);
  });
});

describe('after it is on the canvas', () => {
  const steps = (first: string, second: string, error = '') => [
    { ref: 'frame', state: first, node_id: 'n1', error: '' }, { ref: 'clip', state: second, node_id: 'n2', error },
  ];

  it('runs what is runnable through the canvas', async () => {
    const props = await open(status({ applied: true, state: 'ready', runnable: ['n1', 'n2'], steps: steps('pending', 'pending') }));
    fireEvent.click(screen.getByRole('button', { name: '运行全部 2 步' }));
    expect(props.onRun).toHaveBeenCalledWith(['n1', 'n2']);
  });

  it('after a failure offers to retry only what did not finish, and says finished steps cost nothing twice', async () => {
    const props = await open(status({ applied: true, state: 'failed', runnable: ['n2'], steps: steps('done', 'failed', '供应商超时') }));
    expect(screen.getByText('供应商超时')).toBeTruthy();
    expect(screen.getByText(/不会重复计费/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试 1 步' }));
    expect(props.onRun).toHaveBeenCalledWith(['n2']);
  });

  it('says when it is waiting on an upload', async () => {
    await open(status({ applied: true, state: 'needs_input', runnable: ['n2'], steps: steps('waiting_input', 'pending') }));
    expect(screen.getByText(/1 个素材等你上传/)).toBeTruthy();
  });

  it('a step can be found on the canvas', async () => {
    const props = await open(status({ applied: true, state: 'done', steps: steps('done', 'done') }));
    fireEvent.click(screen.getAllByRole('button', { name: '定位' })[1]);
    expect(props.onJump).toHaveBeenCalledWith('n2');
  });

  it('progress is read again when a run moves on', async () => {
    const read = vi.spyOn(api, 'fetchWorkflow').mockResolvedValue(status({ applied: true, state: 'running', steps: steps('running', 'pending') }));
    vi.spyOn(api, 'listWorkflows').mockResolvedValue({ workflows: [{ id: 'wf1', title: PLAN.title, applied: true, steps: 2, brief: 'b', updated_at: '' }] });
    const props = { projectId: 'p', canvasId: 'main', flush: vi.fn(), currentVersion: () => 1, onApplied: vi.fn(), onRun: vi.fn(), onJump: vi.fn() };
    const { rerender } = render(<WorkflowPanel {...props} refreshKey="a" />);
    await screen.findByRole('option', { name: /雨夜追车/ });
    fireEvent.change(screen.getByLabelText('选择工作流'), { target: { value: 'wf1' } });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    rerender(<WorkflowPanel {...props} refreshKey="b" />);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  });
});

describe('labels', () => {
  it('only steps with words to write get a box', () => {
    expect(stepTakesWords({ ref: 'a', kind: 'tool', tool: 'frame_extract' })).toBe(false);
    expect(stepTakesWords({ ref: 'a', kind: 'tool', tool: 'redraw' })).toBe(true);
    expect(stepTakesWords({ ref: 'a', kind: 'media' })).toBe(false);
    expect(stepTakesWords({ ref: 'a', kind: 'image_gen' })).toBe(true);
  });

  it('a tool step says which tool', () => {
    expect(stepTypeLabel({ ref: 'a', kind: 'tool', tool: 'frame_extract' })).toBe('抽帧');
    expect(stepTypeLabel({ ref: 'a', kind: 'video_gen' })).toBe('视频生成');
  });
});
