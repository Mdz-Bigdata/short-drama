// Idea from AID Studio's workflow canvas (MIT, © 光子讯息(杭州)科技有限公司): the assistant can be talked to
// from inside the canvas, and the nodes that are selected go along as what "this" means.
// Here it is the project's own assistant (the one in the workbench sidebar, same conversation, same
// tools, same confirmation before anything paid); the canvas only adds what is open and selected.
import { apiRequest } from '../../api/client';
import { chatCardsFrom, type ChatCard } from '../workbench/chatCards';
import { nodeTitle } from './canvasLabels';
import type { CanvasNode } from './canvasTypes';

/** The server lists at most this many selected nodes to the assistant; more are only counted. */
export const CHAT_NODE_LIMIT = 40;

export interface CanvasChatContext {
  canvas_id: string;
  nodes: Array<{ id: string; title: string; kind: string }>;
}

/** What the canvas tells the assistant: which board, and which nodes are selected (none when not attached). */
export function chatContext(canvasId: string, selected: readonly CanvasNode[]): CanvasChatContext {
  return {
    canvas_id: canvasId,
    nodes: selected.slice(0, CHAT_NODE_LIMIT).map(node => ({ id: node.id, title: nodeTitle(node), kind: node.kind })),
  };
}

export interface AssistantTurn {
  reply: string;
  proposal: Extract<ChatCard, { kind: 'proposal' }> | null;
  calls: Array<{ tool: string; ok: boolean; error?: string }>;
  /** The newest canvas version the assistant wrote in this turn, with the nodes it touched; null when it wrote none. */
  canvas: { canvasId: string; version: number; nodeIds: string[] } | null;
}

type Dict = Record<string, unknown>;

function isDict(value: unknown): value is Dict {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The assistant's answer as the panel shows it. A malformed field reads as absent, never as an error. */
export function readTurn(data: unknown): AssistantTurn {
  const body = isDict(data) ? data : {};
  const cards = chatCardsFrom(body.tool_calls, body.proposal);
  const proposal = cards.find((card): card is Extract<ChatCard, { kind: 'proposal' }> => card.kind === 'proposal') ?? null;
  const calls = cards.find((card): card is Extract<ChatCard, { kind: 'tool_calls' }> => card.kind === 'tool_calls')?.calls ?? [];
  let canvas = null as AssistantTurn['canvas'];
  for (const call of Array.isArray(body.tool_calls) ? body.tool_calls : []) {
    const result = isDict(call) && isDict(call.result) ? call.result : null;
    const action = result && result.ok !== false && isDict(result.result) ? result.result.ui_action : null;
    if (!isDict(action) || action.type !== 'canvas_changed' || typeof action.version !== 'number') continue;
    const nodeIds = Array.isArray(action.node_ids) ? action.node_ids.filter((id): id is string => typeof id === 'string') : [];
    canvas = {
      canvasId: typeof action.canvas_id === 'string' ? action.canvas_id : 'main',
      version: action.version,
      nodeIds: [...new Set([...(canvas?.nodeIds ?? []), ...nodeIds])],
    };
  }
  return { reply: typeof body.reply === 'string' ? body.reply : '', proposal, calls, canvas };
}

/** One turn with the project's assistant, from the canvas. This is a model call: it is only made when a person sends. */
export function sendCanvasChat(taskId: string, message: string, context: CanvasChatContext): Promise<AssistantTurn> {
  return apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/assistant`, {
    method: 'POST', body: JSON.stringify({ message, context: { canvas: context } }),
  }).then(readTurn);
}
