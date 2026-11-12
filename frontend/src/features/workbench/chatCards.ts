/**
 * 助手一轮回复里值得做成卡片的东西：捏脸改了、舞台改了、等确认的提议、这轮调了哪些工具。
 *
 * 只认 /assistant 返回的 tool_calls 与 proposal 两个字段，格式不对就当没有，不抛错：
 * 聊天气泡宁可少一张卡，也不能因为一条坏数据整屏白掉。
 * 分镜视图(storyboard_view)不在这里处理，storyboardActions.ts 负责它。
 */

export interface StageChanged {
  actors: string[];
  pieces_added: string[];
  pieces_changed: string[];
  pieces_removed: string[];
  cameras: string[];
}

export type ChatCard =
  | { kind: 'face_sculpt_changed'; name: string; before: string; after: string; revision: number; sheetStale: boolean; snapshotId?: string }
  | { kind: 'stage_changed'; sceneId: string; revision: number; snapshotId?: string; summary: string; failingChecks: string[]; changed?: StageChanged }
  | { kind: 'proposal'; tool: string; message: string; arguments: Record<string, unknown> }
  | { kind: 'tool_calls'; calls: Array<{ tool: string; ok: boolean; error?: string }> };

type Dict = Record<string, unknown>;

function isDict(value: unknown): value is Dict {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : [];
}

function stageChanged(value: unknown): StageChanged | undefined {
  if (!isDict(value)) return undefined;
  const changed: StageChanged = {
    actors: names(value.actors),
    pieces_added: names(value.pieces_added),
    pieces_changed: names(value.pieces_changed),
    pieces_removed: names(value.pieces_removed),
    cameras: names(value.cameras),
  };
  return Object.values(changed).some(list => list.length) ? changed : undefined;
}

/** 一条工具结果里的界面事件做成卡片；不是认识的事件、缺关键字段就返回 null。 */
function cardFromUiAction(action: unknown): ChatCard | null {
  if (!isDict(action)) return null;
  if (action.type === 'face_sculpt_changed') {
    const name = text(action.name);
    if (!name) return null;
    const snapshotId = text(action.snapshot_id);
    return {
      kind: 'face_sculpt_changed',
      name,
      before: text(action.before),
      after: text(action.after),
      revision: count(action.revision),
      sheetStale: action.sheet_stale === true,
      ...(snapshotId ? { snapshotId } : {}),
    };
  }
  if (action.type === 'stage_changed') {
    const sceneId = text(action.scene_id);
    if (!sceneId) return null;
    const snapshotId = text(action.snapshot_id);
    const changed = stageChanged(action.changed);
    return {
      kind: 'stage_changed',
      sceneId,
      revision: count(action.revision),
      ...(snapshotId ? { snapshotId } : {}),
      summary: text(action.summary),
      failingChecks: names(action.failing_checks),
      ...(changed ? { changed } : {}),
    };
  }
  return null;
}

/**
 * 这一轮该贴在回复下面的卡片，按顺序：每个成功工具结果里的界面事件各一张，
 * 调过工具就一张汇总，最后是等确认的提议(有的话)。
 */
export function chatCardsFrom(toolCalls: unknown, proposal: unknown): ChatCard[] {
  const cards: ChatCard[] = [];
  const calls: ChatCard & { kind: 'tool_calls' } = { kind: 'tool_calls', calls: [] };
  if (Array.isArray(toolCalls)) {
    for (const call of toolCalls) {
      if (!isDict(call)) continue;
      const tool = text(call.tool) || '?';
      const result = isDict(call.result) ? call.result : {};
      const error = text(result.error);
      // 没写 ok 但也没报错的结果照样算成功：后端有的工具只回 result。
      const ok = result.ok === true || (result.ok === undefined && !error);
      calls.calls.push({ tool, ok, ...(error ? { error } : {}) });
      if (!ok) continue;
      const card = cardFromUiAction(isDict(result.result) ? result.result.ui_action : undefined);
      if (card) cards.push(card);
    }
  }
  if (calls.calls.length) cards.push(calls);
  if (isDict(proposal) && text(proposal.tool) && text(proposal.message)) {
    cards.push({
      kind: 'proposal',
      tool: text(proposal.tool),
      message: text(proposal.message),
      arguments: isDict(proposal.arguments) ? proposal.arguments : {},
    });
  }
  return cards;
}

/**
 * 对话记录里存下来的那一轮：服务端只存界面事件(ui_actions)和等确认的提议(proposal)，
 * 所以重开项目后仍能看到「捏脸已更新」「舞台已改」这些卡片；工具汇总只在当轮显示，不存。
 */
export function chatCardsFromHistory(uiActions: unknown, proposal: unknown): ChatCard[] {
  const cards = (Array.isArray(uiActions) ? uiActions : [])
    .map(cardFromUiAction)
    .filter((card): card is ChatCard => card !== null);
  if (isDict(proposal) && text(proposal.tool) && text(proposal.message)) {
    cards.push({
      kind: 'proposal',
      tool: text(proposal.tool),
      message: text(proposal.message),
      arguments: isDict(proposal.arguments) ? proposal.arguments : {},
    });
  }
  return cards;
}
