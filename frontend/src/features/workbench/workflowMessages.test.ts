import { describe, expect, it } from 'vitest';
import type { TaskResponse, WorkflowSnapshot } from '../../types';
import { appendWorkflowHint, canAcceptTaskResponse, mergeWorkflowHistory, restoreWorkflowHistory, shouldPollWorkflow, workflowBoardStage, workflowIntroMessage } from './workflowMessages';

const workflow: WorkflowSnapshot = {
  stages: [], next_stage: 4, active_stage: null, completed_stages: [1, 2, 3],
  production_complete: false, release_ready: false, mode: 'ready',
  hint: '第 4 阶段还有未完成的分镜。回复「继续」，接着制作第 2 集。',
  actions: [{ kind: 'continue', label: '继续制作分镜', message: '继续' }], event_id: 'partial-4',
};
const task = { taskId: 'task-a', currentStage: 4, status: 'running', workflow } as TaskResponse;

describe('authoritative workflow messages', () => {
  it('uses the server partial-stage hint without claiming stage 5 is next', () => {
    expect(appendWorkflowHint([], task)[0].text).toBe(workflow.hint);
  });
  it('deduplicates repeated completion snapshots by event ID', () => {
    const messages = appendWorkflowHint([], task);
    expect(appendWorkflowHint(messages, { ...task, workflow: { ...workflow } })).toBe(messages);
  });
  it('keeps stage 8 review separate from release completion', () => {
    const review = { ...task, currentStage: 8, workflow: {
      ...workflow, next_stage: null, mode: 'review' as const, production_complete: true,
      hint: '八个阶段的产物已生成，仍需提交真实成片验收。', event_id: 'awaiting-review',
    } };
    expect(appendWorkflowHint([], review)[0].text).toBe(review.workflow.hint);
    expect(shouldPollWorkflow(review)).toBe(false);
  });
  it('does not keep polling a completed single-stage run with legacy running status', () => {
    expect(shouldPollWorkflow(task)).toBe(false);
    expect(shouldPollWorkflow({ ...task, workflow: { ...workflow, mode: 'running', active_stage: 4 } })).toBe(true);
  });
  it('restores durable user and assistant history once', () => {
    const withHistory = { ...task, chatHistory: [
      { id: 'u1', role: 'user' as const, content: '先完成第 2 集分镜' },
      { id: 'a1', role: 'assistant' as const, content: '好的，我们接着做。' },
      { id: 'a1', role: 'assistant' as const, content: '好的，我们接着做。' },
    ] };
    const restored = restoreWorkflowHistory(withHistory);
    expect(restored.map(message => message.sender)).toEqual(['user', 'ai']);
    expect(mergeWorkflowHistory(restored, withHistory)).toEqual(restored);
  });
  it('keeps existing stage events in chronological order when new replies arrive', () => {
    const existing = appendWorkflowHint([], task);
    const merged = mergeWorkflowHistory(existing, { ...task, chatHistory: [{ id: 'next', role: 'assistant', content: '已继续第 4 阶段。' }] });
    expect(merged.map(message => message.text)).toEqual([workflow.hint, '已继续第 4 阶段。']);
  });
  it('never renders the same guidance twice when a stage event quotes it', () => {
    const durable = { ...task, chatHistory: [
      { id: 'stage-4-done', role: 'assistant' as const, content: `第 4/8 步的产物已生成。\n${workflow.hint}` },
    ] };
    expect(appendWorkflowHint(restoreWorkflowHistory(durable), durable)).toHaveLength(1);
  });
  it('drops a live hint once the durable stage event carrying it arrives', () => {
    const live = appendWorkflowHint([], task);
    const merged = mergeWorkflowHistory(live, { ...task, chatHistory: [
      { id: 'stage-4-done', role: 'assistant', content: `第 4/8 步的产物已生成。\n${workflow.hint}` },
    ] });
    expect(merged.map(message => message.id)).toEqual(['history:stage-4-done']);
  });
  it('follows the running stage, then the next one the server asks for', () => {
    expect(workflowBoardStage({ ...task, workflow: { ...workflow, active_stage: 1, next_stage: 1 } })).toBe(1);
    expect(workflowBoardStage({ ...task, currentStage: 1, workflow: { ...workflow, active_stage: null, next_stage: 2 } })).toBe(2);
    expect(workflowBoardStage({ ...task, currentStage: 8, workflow: { ...workflow, active_stage: null, next_stage: null } })).toBe(8);
    expect(workflowBoardStage({ taskId: 'a', currentStage: 3 } as TaskResponse)).toBe(3);
  });
  it('shows the current project transcript once, however often a step was restarted', () => {
    // 真实项目 e4094e02 的形状：阶段三被打断五次，「继续 → 开始第 3/8 步」原样重复五轮。
    const restart = (round: number) => ([
      { id: `u${round}`, role: 'user' as const, content: '继续' },
      { id: `a${round}`, role: 'assistant' as const, content: '开始第 3/8 步：角色设计师造型。' },
    ]);
    const restored = restoreWorkflowHistory({ ...task, chatHistory: [
      { id: 'u0', role: 'user', content: '进度' },
      { id: 'a0', role: 'assistant', content: '正在进行第 3/8 步。' },
      ...restart(1), ...restart(2), ...restart(3), ...restart(4), ...restart(5),
      { id: 'done', role: 'assistant', content: '第 3/8 步的产物已生成。' },
    ] });
    expect(restored.map(message => message.text)).toEqual([
      '进度',
      '正在进行第 3/8 步。',
      '继续',
      '开始第 3/8 步：角色设计师造型。',
      '第 3/8 步的产物已生成。',
    ]);
  });
  it('keeps every distinct exchange and every unpaired stage event', () => {
    const restored = restoreWorkflowHistory({ ...task, chatHistory: [
      { id: 'u1', role: 'user', content: '继续' },
      { id: 'a1', role: 'assistant', content: '开始第 1/8 步。' },
      { id: 'a2', role: 'assistant', content: '第 1/8 步的产物已生成。' },
      { id: 'u2', role: 'user', content: '继续' },
      { id: 'a3', role: 'assistant', content: '开始第 2/8 步。' },
      { id: 'u3', role: 'user', content: '暂停' },
      { id: 'a4', role: 'assistant', content: '已收到暂停请求。' },
    ] });
    expect(restored).toHaveLength(7);
    expect(restored.filter(message => message.sender === 'user')).toHaveLength(3);
  });
  it('opens a transcript-less project with the whole eight-agent route and where it stands', () => {
    const stages = Array.from({ length: 8 }, (_, index) => ({
      stage: index + 1, label: `第${index + 1}个Agent`, state: 'pending' as const, missing: [], guidance: '',
    }));
    const intro = workflowIntroMessage({ ...task, workflow: { ...workflow, stages } })!;
    expect(intro.text).toContain('1.第1个Agent → 2.第2个Agent');
    expect(intro.text).toContain('8.第8个Agent');
    expect(intro.text).toContain('已完成 3/8 步，下一步是第 4/8 步：第4个Agent。');
    const running = workflowIntroMessage({ ...task, workflow: { ...workflow, stages, active_stage: 4 } })!;
    expect(running.text).toContain('正在执行第 4/8 步：第4个Agent。');
    const review = workflowIntroMessage({ ...task, workflow: { ...workflow, stages, next_stage: null } })!;
    expect(review.text).toContain('只剩成片验收与发布终审');
  });
  it('invents no orientation for a project the server has not described', () => {
    expect(workflowIntroMessage({ taskId: 'a', currentStage: 0 } as TaskResponse)).toBeNull();
  });
  it('rejects a late task response after switching or closing the project', () => {
    expect(canAcceptTaskResponse('task-b', 'task-a')).toBe(false);
    expect(canAcceptTaskResponse('', 'task-a')).toBe(false);
    expect(canAcceptTaskResponse('task-b', 'task-b')).toBe(true);
  });
});
