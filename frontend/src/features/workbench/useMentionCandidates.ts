import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { useAssetsChanged } from '../elements/assetEvents';
import { MENTION_NAME_MAX, type MentionCandidate } from './mentionAutocomplete';

/**
 * 项目里能 @ 的人物、场景、道具：GET /api/drama/{taskId}/mentionable。
 *
 * 同一个项目 60 秒内只读一次(多个输入框共用一份)；资产改名、换图、删除时
 * (novara:assets-changed)丢掉缓存重读。
 */

const TTL_MS = 60_000;
const FETCH_LIMIT = 200;

interface CacheEntry { at: number; items: MentionCandidate[] }

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<MentionCandidate[]>>();

/** 测试用：清掉所有项目的缓存。 */
export function clearMentionCandidatesCache(): void {
  cache.clear();
  inflight.clear();
}

function freshEntry(taskId: string): CacheEntry | undefined {
  const entry = cache.get(taskId);
  return entry && Date.now() - entry.at < TTL_MS ? entry : undefined;
}

interface RawItem {
  name?: unknown;
  kind?: unknown;
  element_id?: unknown;
  aliases?: unknown;
  description?: unknown;
  thumb_url?: unknown;
}

const text = (value: unknown) => (typeof value === 'string' ? value : '');

/** 后端返回的 items 转成 MentionCandidate；名字不合 @[名字] 写法的丢掉。 */
export function toMentionCandidates(data: unknown): MentionCandidate[] {
  const raw = data && typeof data === 'object' ? (data as { items?: unknown }).items : undefined;
  if (!Array.isArray(raw)) return [];
  const items: MentionCandidate[] = [];
  for (const entry of raw as RawItem[]) {
    if (!entry || typeof entry !== 'object') continue;
    const name = text(entry.name).trim();
    if (!name || name.length > MENTION_NAME_MAX || /[[\]\n]/.test(name)) continue;
    const aliases = Array.isArray(entry.aliases) ? entry.aliases.filter((alias): alias is string => typeof alias === 'string' && Boolean(alias)) : [];
    items.push({
      name,
      kind: text(entry.kind) || 'unknown',
      elementId: text(entry.element_id) || undefined,
      aliases,
      description: text(entry.description) || undefined,
      thumbUrl: text(entry.thumb_url) || undefined,
    });
  }
  return items;
}

function loadCandidates(taskId: string): Promise<MentionCandidate[]> {
  const running = inflight.get(taskId);
  if (running) return running;
  const path = `/api/drama/${encodeURIComponent(taskId)}/mentionable?q=&limit=${FETCH_LIMIT}`;
  const request = apiRequest<unknown>(path)
    .then(data => {
      const items = toMentionCandidates(data);
      cache.set(taskId, { at: Date.now(), items });
      return items;
    })
    .finally(() => { inflight.delete(taskId); });
  inflight.set(taskId, request);
  return request;
}

export interface MentionCandidatesState {
  items: MentionCandidate[];
  loading: boolean;
  error: string;
}

const EMPTY: MentionCandidate[] = [];

export function useMentionCandidates(taskId?: string): MentionCandidatesState {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ key: string; items: MentionCandidate[]; error: string } | null>(null);
  const key = taskId ? `${taskId}#${version}` : '';

  useAssetsChanged(() => {
    if (!taskId) return;
    // 只标成过期：重读回来之前菜单先用旧的一份，不闪空。
    const entry = cache.get(taskId);
    if (entry) cache.set(taskId, { ...entry, at: 0 });
    setVersion(current => current + 1);
  });

  useEffect(() => {
    if (!taskId || freshEntry(taskId)) return;
    let alive = true;
    loadCandidates(taskId).then(
      items => { if (alive) setResult({ key, items, error: '' }); },
      (caught: unknown) => {
        if (alive) setResult({ key, items: [], error: caught instanceof Error ? caught.message : t('读取可引用的资产失败') });
      },
    );
    return () => { alive = false; };
  }, [taskId, key]);

  if (!taskId) return { items: EMPTY, loading: false, error: '' };
  const fresh = freshEntry(taskId);
  if (fresh) return { items: fresh.items, loading: false, error: '' };
  if (result?.key === key) return { items: result.items, loading: false, error: result.error };
  return { items: cache.get(taskId)?.items ?? EMPTY, loading: true, error: '' };
}
