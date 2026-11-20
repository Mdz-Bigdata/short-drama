// Idea from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors): share a canvas read-only by link.
import { API_BASE, ApiError, apiRequest } from '../../api/client';
import { acceptLanguage, getLocale, t } from '../../i18n';
import type { CanvasEdge, CanvasNode, NodeOutput } from './canvasTypes';

/** A live read-only link to one canvas. `url_path` is relative to the frontend origin (`/share/canvas/<token>`). */
export interface CanvasShare {
  token: string;
  url_path: string;
  expires_at: string | null;
  created_at: string;
}

/** How long a new link stays valid, in days; `null` never expires. */
export type ShareExpiryDays = 1 | 7 | 30 | null;

export const SHARE_EXPIRY_CHOICES: readonly ShareExpiryDays[] = [1, 7, 30, null];

/** What a visitor of a share link sees: the canvas as it was saved, and what its nodes produced. */
export interface SharedCanvas {
  title: string;
  canvas_id: string;
  version: number;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  outputs: Record<string, Pick<NodeOutput, 'medium' | 'url' | 'text' | 'filename'>>;
  expires_at: string | null;
}

const sharePath = (projectId: string, canvasId: string) =>
  `/api/studio/projects/${encodeURIComponent(projectId)}/canvases/${encodeURIComponent(canvasId)}/share`;

export function getCanvasShare(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<CanvasShare | null>(sharePath(projectId, canvasId), { signal });
}

/** Create the link; when one exists the old one stops working and a new one is returned. */
export function createCanvasShare(projectId: string, canvasId: string, expiresDays: ShareExpiryDays) {
  return apiRequest<CanvasShare>(sharePath(projectId, canvasId), { method: 'POST', body: JSON.stringify({ expires_days: expiresDays }) });
}

export function stopCanvasShare(projectId: string, canvasId: string) {
  return apiRequest<{ stopped: boolean }>(sharePath(projectId, canvasId), { method: 'DELETE' });
}

/** The link to hand out: the frontend's own origin, since the share page is a frontend route. */
export function shareUrl(share: Pick<CanvasShare, 'url_path'>, origin: string = window.location.origin): string {
  return `${origin.replace(/\/+$/, '')}${share.url_path.startsWith('/') ? '' : '/'}${share.url_path}`;
}

/** The validity period a link was created with, so a new link keeps it; the nearest offered choice. */
export function shareExpiryDays(share: Pick<CanvasShare, 'expires_at' | 'created_at'>): ShareExpiryDays {
  if (!share.expires_at) return null;
  const span = (Date.parse(share.expires_at) - Date.parse(share.created_at)) / 86_400_000;
  if (!Number.isFinite(span)) return 7;
  const offered = SHARE_EXPIRY_CHOICES.filter((item): item is 1 | 7 | 30 => item !== null);
  return offered.reduce((best, item) => (Math.abs(item - span) < Math.abs(best - span) ? item : best), offered[0]);
}

/** When a link stops working, in words. */
export function shareExpiryText(expiresAt: string | null) {
  if (!expiresAt) return t('永久有效');
  const date = new Date(expiresAt);
  // 跟随界面语言写日期，精确到分钟：中文界面就是「2026/11/18 12:07 到期」。
  const when = date.toLocaleString(getLocale(), { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  return t('{0} 到期', [Number.isNaN(date.getTime()) ? expiresAt : when]);
}

/**
 * The public, no-login read of a share. Plain fetch without cookies: a visitor has no session,
 * and an owner opening their own link must see exactly what everyone else sees.
 * Fails with `ApiError` carrying the status (404 gone, 429 too many requests), or the fetch's own error offline.
 */
export async function fetchSharedCanvas(token: string, signal?: AbortSignal): Promise<SharedCanvas> {
  const response = await fetch(`${API_BASE}/api/public/canvas-shares/${encodeURIComponent(token)}`, {
    signal,
    credentials: 'omit',
    headers: { 'Accept-Language': acceptLanguage() },
  });
  if (!response.ok) throw new ApiError(`请求失败 (${response.status})`, response.status);
  return response.json() as Promise<SharedCanvas>;
}
