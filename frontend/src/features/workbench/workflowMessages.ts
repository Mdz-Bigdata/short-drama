import type { TaskChatEntry, TaskResponse } from '../../types';

export interface WorkflowChatMessage {
  id: string;
  sender: 'user' | 'ai';
  text: string;
  stage?: number;
  isSystem?: boolean;
}

/**
 * 当前项目的完整对话记录，且只有当前项目的。
 *
 * 一个阶段被打断后重来，「继续 → 同一句阶段指引」这一来一回会被原样再写一遍：
 * 说的是同一件事，铺开只会把同一段话刷满整屏，真正读得出信息的消息反而被埋掉。
 * 完全相同的一轮问答只保留第一次出现的位置；落单的消息一律原样保留，
 * 所以阶段开始、完成、失败这些真正的进展一条都不会少。
 */
export function restoreWorkflowHistory(task: TaskResponse): WorkflowChatMessage[] {
  const seen = new Set<string>();
  const entries = (task.chatHistory ?? []).filter(entry => {
    if (!entry.id || seen.has(entry.id) || !entry.content) return false;
    seen.add(entry.id);
    return true;
  });
  const bubble = (entry: TaskChatEntry): WorkflowChatMessage => ({
    id: `history:${entry.id}`,
    sender: entry.role === 'user' ? 'user' : 'ai',
    text: entry.content,
  });
  const shown = new Set<string>();
  const restored: WorkflowChatMessage[] = [];
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    const reply = entries[index + 1];
    if (entry.role === 'user' && reply?.role === 'assistant') {
      const exchange = `${entry.content}\u0000${reply.content}`;
      index += 1;
      if (shown.has(exchange)) continue;
      shown.add(exchange);
      restored.push(bubble(entry), bubble(reply));
      continue;
    }
    restored.push(bubble(entry));
  }
  return restored;
}

/** Stage completion and the next action are server facts, never currentStage + 1. */
export function appendWorkflowHint(
  messages: WorkflowChatMessage[],
  task: TaskResponse,
): WorkflowChatMessage[] {
  const workflow = task.workflow;
  if (!workflow?.hint || !workflow.event_id) return messages;
  const id = `workflow:${task.taskId}:${workflow.event_id}`;
  // A durable stage event quotes the same guidance. Showing the live bubble too
  // would repeat the whole paragraph directly under it.
  if (messages.some(message => message.id === id || message.text.includes(workflow.hint))) return messages;
  return [...messages, { id, sender: 'ai', text: workflow.hint, isSystem: true }];
}

export function mergeWorkflowHistory(messages: WorkflowChatMessage[], task: TaskResponse): WorkflowChatMessage[] {
  const history = restoreWorkflowHistory(task);
  const byId = new Map(history.map(message => [message.id, message]));
  const existingIds = new Set(messages.map(message => message.id));
  return [
    ...messages
      .map(message => byId.get(message.id) ?? message)
      // A live hint shown before the server persisted the matching stage event
      // is superseded by it, not stacked on top of it.
      .filter(message => !(message.isSystem && history.some(item => item.text.includes(message.text)))),
    ...history.filter(message => !existingIds.has(message.id)),
  ];
}

/**
 * 打开一个还没有对话记录的项目时，先说清这条流水线长什么样、现在走到哪一步，
 * 用户才知道接下来该做什么。全部取自服务端快照：阶段名、已完成步数、下一步，
 * 都不是前端推算出来的。没有快照就什么也不编。
 */
export function workflowIntroMessage(task: TaskResponse): WorkflowChatMessage | null {
  const workflow = task.workflow;
  if (!workflow?.stages.length) return null;
  const sequence = workflow.stages.map(stage => `${stage.stage}.${stage.label}`).join(' → ');
  const done = workflow.completed_stages.length;
  const active = workflow.active_stage;
  const next = workflow.next_stage;
  const where = active
    ? `正在执行第 ${active}/8 步：${workflow.stages[active - 1].label}。`
    : next
      ? `已完成 ${done}/8 步，下一步是第 ${next}/8 步：${workflow.stages[next - 1].label}。`
      : `8 个阶段的产物都已生成，只剩成片验收与发布终审。`;
  return {
    id: `workflow-intro:${task.taskId}:${workflow.event_id}`,
    sender: 'ai',
    isSystem: true,
    text: [
      `这个项目由 8 个 Agent 依次完成：${sequence}。`,
      where,
      '每一步我都会说明这一阶段做了什么、产出在左侧哪个看板，再引导您确认或继续；'
      + '您也可以随时说「进度」查询、说「暂停」停下，或直接说出修改意见。',
    ].join('\n'),
  };
}

/**
 * Which agent board the project is on: the running stage, else the next one the
 * server asks for. A finished stage 1 therefore opens the writer agent instead
 * of leaving the director page up while the chat already asks for stage 2.
 */
export function workflowBoardStage(task: TaskResponse): number {
  return task.workflow?.active_stage ?? task.workflow?.next_stage ?? task.currentStage;
}

export function shouldPollWorkflow(task: TaskResponse): boolean {
  return task.workflow ? task.workflow.mode === 'running' : task.status === 'running';
}

export function canAcceptTaskResponse(selectedTaskId: string, responseTaskId: string): boolean {
  return Boolean(selectedTaskId) && selectedTaskId === responseTaskId;
}
