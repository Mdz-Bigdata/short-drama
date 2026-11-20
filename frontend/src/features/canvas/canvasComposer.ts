// Idea from AID Studio's workflow canvas (MIT, © 光子讯息(杭州)科技有限公司): the selected node carries a dock
// under it with the prompt, the model, the parameters, what a run would cost and the button that runs it.
// Written for this canvas: its nodes, its run options and its own admission quote.
import { t } from '../../i18n';
import type { CanvasNode, Medium, NodeKind, NodeParams, RunAssessment, RunOptions, Viewport } from './canvasTypes';

/** The kinds a dock is drawn for: the ones that turn a prompt into a picture, a clip or a sound. */
export const COMPOSER_MEDIUM: Partial<Record<NodeKind, Medium>> = { image_gen: 'image', video_gen: 'video', audio_gen: 'audio' };

export function hasComposer(node: Pick<CanvasNode, 'kind'>) {
  return node.kind in COMPOSER_MEDIUM;
}

export const DOCK_WIDTH = 560;
/** Room kept for the dock's own height when it is held inside the view. */
export const DOCK_HEIGHT = 176;
export const DOCK_GAP = 12;
export const DOCK_MARGIN = 12;

export interface DockPlacement { left: number; top: number; width: number }

/**
 * Where the dock goes, in the viewport's own pixels: centred under the node, pulled back inside
 * the view when the node sits near an edge, and nowhere when the node is out of sight.
 */
export function dockPlacement(
  node: Pick<CanvasNode, 'x' | 'y' | 'width' | 'height'>, view: Viewport, viewport: { width: number; height: number },
): DockPlacement | null {
  const left = node.x * view.zoom + view.x;
  const top = node.y * view.zoom + view.y;
  const right = left + node.width * view.zoom;
  const bottom = top + node.height * view.zoom;
  if (right < 0 || bottom < 0 || left > viewport.width || top > viewport.height) return null;
  const width = Math.max(0, Math.min(DOCK_WIDTH, viewport.width - DOCK_MARGIN * 2));
  if (width < 240) return null;
  const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(value, Math.max(low, high)));
  return {
    width,
    left: Math.round(clamp((left + right) / 2 - width / 2, DOCK_MARGIN, viewport.width - width - DOCK_MARGIN)),
    top: Math.round(clamp(bottom + DOCK_GAP, DOCK_MARGIN, viewport.height - DOCK_HEIGHT - DOCK_MARGIN)),
  };
}

/** The models a node of this kind may pick, the project's own first among them. */
export function modelChoices(node: Pick<CanvasNode, 'kind'>, options: RunOptions | null): { fallback: string; models: string[] } | null {
  const medium = COMPOSER_MEDIUM[node.kind];
  if (!medium || !options) return null;
  const fallback = options.models[medium];
  return { fallback, models: [...new Set([...options.enabled[medium], ...(fallback ? [fallback] : [])])] };
}

/** How many results one run may make for this kind: 1 when the server offers no more, or does not say. */
export function countCeiling(node: Pick<CanvasNode, 'kind'>, options: RunOptions | null): number {
  const versions = options?.versions;
  if (!versions || !versions.kinds.includes(node.kind)) return 1;
  return Math.max(1, Math.floor(versions.max));
}

/** The count a node asks for, held between 1 and the ceiling. */
export function countOf(params: NodeParams | undefined, ceiling: number): number {
  const asked = Math.floor(Number(params?.count ?? 1));
  return Number.isFinite(asked) ? Math.max(1, Math.min(ceiling, asked)) : 1;
}

/** `params` with one value set, or dropped when it is back at its default: an untouched node stays untouched. */
export function withParam(params: NodeParams | undefined, key: string, value: unknown, fallback?: unknown): NodeParams {
  const next: NodeParams = { ...params };
  if (value === fallback || value === '' || value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

export interface QuoteLine { text: string; tone: 'cost' | 'free' | 'blocked' }

/** One line for what a run of this node would cost, or the first thing that stops it. */
export function quoteLine(assessment: RunAssessment, nodeId: string): QuoteLine {
  const row = assessment.nodes.find(item => item.node_id === nodeId);
  const stop = row?.problems.find(problem => problem.blocking);
  if (stop) return { text: stop.message, tone: 'blocked' };
  const { totals, paid_items: paid, unpriced_items: unpriced } = assessment.estimate;
  if (!paid) return { text: t('本机处理，不调用付费模型。'), tone: 'free' };
  const priced = totals.map(item => `${item.cost} ${item.currency}`).join(' + ');
  const seconds = row && row.requested_seconds > 0 ? ` · ${t('{0} 秒', [row.requested_seconds])}` : '';
  const several = row?.versions && row.versions > 1 ? ` · ${t('{0} 个结果', [row.versions])}` : '';
  if (priced && !unpriced) return { text: `${t('参考费用约 {0}', [priced])}${seconds}${several}`, tone: 'cost' };
  return { text: `${t('未定价')}${seconds}${several}`, tone: 'cost' };
}
