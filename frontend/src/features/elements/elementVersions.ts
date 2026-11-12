/**
 * 资产的版本记录、恢复旧版本，以及哪些镜头用到了它。
 *
 * 后端每次改资产(改名、改描述、换图、恢复)都存一版；改动的响应里带 ``sync``，
 * 说哪些项目的镜头和片段因此标成了需重画 / 需重跑。
 */
import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import type { ElementItem } from './elementTypes';

export type RevisionReason = 'edit' | 'rename' | 'file' | 'file_delete' | 'variant' | 'prop_size' | 'real_person' | 'restore';

export interface ElementRevisionFile {
  slot: string;
  url: string | null;
}

export interface ElementRevision {
  revision: number;
  version: number;
  name: string;
  description: string;
  reason: RevisionReason | string;
  created_at: string;
  files: ElementRevisionFile[];
}

export interface ElementUsage {
  task_id: string;
  title: string;
  scene_id?: string | number | null;
  shot_id?: string | number | null;
  shot_uid?: string | null;
  in_storyboard: boolean;
  in_video: boolean;
}

export interface ElementSyncTask {
  task_id: string;
  shots_marked: number;
  clips_marked: number;
  boards_marked?: number;
  skipped?: boolean | string;
}

export interface ElementSync {
  tasks?: ElementSyncTask[];
  renamed?: boolean;
}

/** 改动响应里可能带着的 sync；没有或格式不对时当没有。 */
export type WithSync<T> = T & { sync?: ElementSync | null };

export function syncCounts(response: unknown): { shotsMarked: number; clipsMarked: number } {
  const sync = response && typeof response === 'object' ? (response as { sync?: unknown }).sync : undefined;
  const tasks = sync && typeof sync === 'object' && Array.isArray((sync as ElementSync).tasks) ? (sync as ElementSync).tasks! : [];
  let shotsMarked = 0;
  let clipsMarked = 0;
  for (const task of tasks) {
    if (!task || typeof task !== 'object') continue;
    shotsMarked += Number(task.shots_marked) || 0;
    clipsMarked += Number(task.clips_marked) || 0;
  }
  return { shotsMarked, clipsMarked };
}

/** 「N 个镜头需重画或重跑」里的 N：镜头和片段分开标，取大的那个，免得一镜两算。 */
export function affectedShots(counts: { shotsMarked: number; clipsMarked: number }): number {
  return Math.max(counts.shotsMarked, counts.clipsMarked);
}

const reasonLabels: Record<RevisionReason, string> = {
  edit: '改了设定',
  rename: '改名',
  file: '换了图',
  file_delete: '删了图',
  variant: '改了衍生形象',
  prop_size: '改了尺寸',
  real_person: '改了真人设置',
  restore: '恢复旧版本',
};

export function revisionReasonLabel(reason: string): string {
  return t(reasonLabels[reason as RevisionReason] ?? '改动');
}

/** 「3 分钟前」「2 天前」；读不出时间时给空串。 */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return '';
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 60) return t('刚刚');
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t('{0} 分钟前', [minutes]);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('{0} 小时前', [hours]);
  const days = Math.floor(hours / 24);
  if (days < 30) return t('{0} 天前', [days]);
  return new Date(at).toLocaleDateString('zh-CN');
}

export async function fetchRevisions(elementId: string): Promise<ElementRevision[]> {
  const data = await apiRequest<{ items?: ElementRevision[] }>(`/api/elements/${encodeURIComponent(elementId)}/revisions`);
  return Array.isArray(data?.items) ? data.items : [];
}

export function restoreRevision(elementId: string, revision: number): Promise<WithSync<ElementItem>> {
  return apiRequest<WithSync<ElementItem>>(
    `/api/elements/${encodeURIComponent(elementId)}/revisions/${encodeURIComponent(String(revision))}/restore`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export async function fetchUsages(elementId: string): Promise<ElementUsage[]> {
  const data = await apiRequest<{ items?: ElementUsage[] }>(`/api/elements/${encodeURIComponent(elementId)}/usages`);
  return Array.isArray(data?.items) ? data.items : [];
}

/** 「场景 3 · 第 12 镜」；号码是纯数字才加「第…镜」。 */
export function usageShotLabel(usage: ElementUsage): string {
  const parts: string[] = [];
  const scene = usage.scene_id === null || usage.scene_id === undefined ? '' : String(usage.scene_id).trim();
  const shot = usage.shot_id === null || usage.shot_id === undefined ? '' : String(usage.shot_id).trim();
  if (scene) parts.push(t('场景 {0}', [scene]));
  if (shot) parts.push(/^\d+$/.test(shot) ? t('第 {0} 镜', [Number(shot)]) : shot);
  return parts.join(' · ');
}
