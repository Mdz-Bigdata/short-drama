import { apiRequest } from '../../api/client';

export interface ScreenwritingLedgerEntry {
  episode: number;
  title: string;
  hook: string;
  storyBeats: string[];
  nextEpisodeTeaser?: string | null;
  ledgerStatus: string;
  /** cut: a span of the whole source; own: the episode's own upload; none: planned from the outline. */
  sourceOrigin?: 'cut' | 'own' | 'none';
  sourceKind?: 'novel' | 'screenplay' | null;
  sourceName?: string | null;
}

export function ledgerOriginLabel(entry: ScreenwritingLedgerEntry): string {
  if (entry.sourceOrigin === 'own') {
    const kind = entry.sourceKind === 'screenplay' ? '成品剧本' : '小说';
    return entry.sourceName ? `自带原文 · ${entry.sourceName}（${kind}）` : `自带原文（${kind}）`;
  }
  if (entry.sourceOrigin === 'none') return '按大纲创作';
  return '切自整本源文';
}

export type ReviewStatus = 'missing' | 'draft' | 'pending' | 'changed' | 'confirmed';

export interface ScreenwritingReviewStatus {
  episode: number;
  status: ReviewStatus;
  confirmedRevision?: string | null;
  confirmedAt?: string | null;
  confirmedBy?: string | null;
  /** Present for a quarantined draft: why it still breaks a rule. */
  draft?: { reasons: string[]; origin: string; attempts: number; quarantined_at?: string } | null;
}

export interface ScreenwritingReviewSummary {
  total: number;
  confirmed: number[];
  pending: number[];
  changed: number[];
  drafts: number[];
  missing: number[];
  allConfirmed: boolean;
  message: string;
}

export const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  missing: '未写出',
  draft: '违约草稿',
  pending: '待审核',
  changed: '改动后待复审',
  confirmed: '已确认',
};

export interface ScreenwritingEpisodeSummary {
  episode: number;
  title: string;
  sceneCount: number;
  durationSeconds: number;
  planRevision: string;
  violationCount: number;
  needsReplan: string[];
  writtenAt: string;
  review?: ScreenwritingReviewStatus;
}

export interface ScreenwritingState {
  schemaVersion: 'screenwriting.v1';
  taskId: string;
  available: boolean;
  engine: string;
  sourceKind?: 'outline' | 'novel' | 'screenplay' | null;
  stale: boolean;
  staleReason?: string | null;
  title: string;
  episodeCount: number;
  overview: { title: string; synopsis: string; genre: string; theme: string; worldSetting?: string; world_setting?: string };
  inventory: Record<string, Record<string, { description?: string; voice_style?: string; position?: string }>>;
  ledger: ScreenwritingLedgerEntry[];
  durations: { supported: number[]; default?: number | null; episodeTargetSeconds?: number | null; videoModel: string };
  episodes: ScreenwritingEpisodeSummary[];
  reviewSummary?: ScreenwritingReviewSummary;
  warnings: string[];
  updatedAt: string;
}

export interface ScreenwritingUtterance {
  kind: 'dialogue' | 'voiceover';
  speaker?: string | null;
  text: string;
  delivery?: string | null;
}

export interface ScreenwritingScene {
  scene_id: string;
  duration_seconds: number;
  segment_break?: boolean;
  setting?: string;
  characters_in_scene?: string[];
  scenes?: string[];
  props?: string[];
  scene_description?: string;
  utterances?: ScreenwritingUtterance[];
  source_text?: string;
  needs_replan?: boolean;
  image_prompt?: { scene?: string; composition?: { shot_type?: string; lighting?: string; ambiance?: string } };
  video_prompt?: { action?: string; camera_motion?: string; ambiance_audio?: string };
}

export interface ScreenwritingViolation {
  code: string;
  message: string;
  label: string;
  severity: 'error' | 'warning';
  sceneId?: string | null;
}

export interface ScreenwritingEpisode {
  taskId: string;
  episode: number;
  title: string;
  hook?: string | null;
  nextEpisodeTeaser?: string | null;
  planRevision: string;
  stale: boolean;
  plan: { title?: string; scenes: ScreenwritingScene[] };
  script: { episode: number; title: string; scenes: ScreenwritingScene[] };
  screenplayText: string;
  violations: ScreenwritingViolation[];
  needsReplan: string[];
  writtenAt: string;
  rewrittenSceneIds: string[];
  review?: ScreenwritingReviewStatus;
  repair?: { episode: number; repaired: boolean; improved: boolean; before?: string[]; remaining: string[] } | null;
}

export type PlanOperation =
  | { op: 'update'; id: string; fields: Record<string, unknown> }
  | { op: 'insert_after'; after_id: string | null; item: Record<string, unknown> }
  | { op: 'move_after'; id: string; after_id: string | null }
  | { op: 'remove'; id: string }
  | { op: 'split'; id: string; parts: Record<string, unknown>[] };

const base = (taskId: string) => `/api/drama/${encodeURIComponent(taskId)}/screenwriting`;

export function fetchScreenwritingState(taskId: string, signal?: AbortSignal) {
  return apiRequest<ScreenwritingState>(base(taskId), { signal });
}

export function fetchScreenwritingEpisode(taskId: string, episode: number, signal?: AbortSignal) {
  return apiRequest<ScreenwritingEpisode>(`${base(taskId)}/episodes/${episode}`, { signal });
}

export type ScreenwritingPromptStage = 'plan' | 'prose' | 'visual';

export function fetchScreenwritingPrompt(taskId: string, episode: number, stage: ScreenwritingPromptStage, signal?: AbortSignal) {
  return apiRequest<{ taskId: string; episode: number; stage: string; prompt: string }>(
    `${base(taskId)}/episodes/${episode}/prompt?stage=${stage}`,
    { signal },
  );
}

export function patchScreenwritingPlan(
  taskId: string,
  episode: number,
  body: { baseRevision: string; operations: PlanOperation[]; confirmInvalidate?: boolean },
) {
  return apiRequest<ScreenwritingEpisode>(`${base(taskId)}/episodes/${episode}/plan`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function reviewScreenwritingEpisode(taskId: string, episode: number, action: 'confirm' | 'reopen') {
  return apiRequest<ScreenwritingEpisode>(`${base(taskId)}/episodes/${episode}/review`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

export function repairScreenwritingEpisode(taskId: string, episode: number, confirmInvalidate = false) {
  return apiRequest<ScreenwritingEpisode>(`${base(taskId)}/episodes/${episode}/repair`, {
    method: 'POST',
    body: JSON.stringify({ confirm_invalidate: confirmInvalidate }),
  });
}

// ---------------------------------------------------------------------------- episode ledger operations

export interface LedgerEntryView {
  episode: number;
  title: string;
  hook: string;
  origin: 'cut' | 'own' | 'none';
  source_kind?: 'novel' | 'screenplay' | null;
  source_name?: string | null;
  source_range?: { start: number; end: number } | null;
  units: number;
  units_noun: string;
  opening: string;
  closing: string;
  written: boolean;
  ledger_status: string;
}

export interface LedgerCandidateEntry {
  position: number;
  title: string;
  hook: string;
  source_range?: { start: number; end: number } | null;
  units: number;
  relation: 'same' | 'overlaps' | 'new';
  overlaps: number[];
}

export interface LedgerCandidate {
  from_episode: number;
  created_at?: string | null;
  adoptable: boolean;
  old_count: number;
  new_count: number;
  old_average_units: number;
  new_average_units: number;
  replaced_written: number[];
  entries: LedgerCandidateEntry[];
}

export interface LedgerView {
  task_id: string;
  entries: LedgerEntryView[];
  unsplit: { start: number; end: number }[];
  source_length: number;
  layout_revision: string;
  candidate: LedgerCandidate | null;
  /** Present after an operation: what it discarded, created and renumbered. */
  discarded?: number[];
  created?: number[];
  notes?: string[];
  renumbered?: Record<string, number>;
}

export type LedgerOperation =
  | 'split' | 'move_boundary' | 'merge_with_next' | 'cut_unsplit' | 'clear_after'
  | 'create' | 'move' | 'delete' | 'update_own_source';

export interface LedgerOperationBody {
  operation: LedgerOperation;
  episode?: number;
  offset?: number;
  start?: number;
  end?: number;
  after?: number | null;
  title?: string;
  text?: string;
  source_kind?: 'novel' | 'screenplay' | null;
  include_unsplit?: boolean;
  confirm_discard?: number[];
  confirm_invalidate?: boolean;
  write_now?: boolean;
}

export interface LedgerImpact {
  episode: number;
  title: string;
  origin: string;
  written: boolean;
  scenes: number;
  has_prose: boolean;
}

export function fetchLedger(taskId: string, signal?: AbortSignal) {
  return apiRequest<LedgerView>(`${base(taskId)}/ledger`, { signal });
}

export function fetchLedgerSource(taskId: string, start: number, end: number, signal?: AbortSignal) {
  return apiRequest<{ task_id: string; start: number; end: number; text: string }>(
    `${base(taskId)}/ledger/source?start=${start}&end=${end}`,
    { signal },
  );
}

export function fetchLedgerImpact(taskId: string, episodes: number[]) {
  const query = episodes.map(number => `episode=${number}`).join('&');
  return apiRequest<{ task_id: string; episodes: LedgerImpact[] }>(`${base(taskId)}/ledger/impact?${query}`, { method: 'POST' });
}

export function applyLedgerOperation(taskId: string, body: LedgerOperationBody) {
  return apiRequest<LedgerView>(`${base(taskId)}/ledger/ops`, { method: 'POST', body: JSON.stringify(body) });
}

export function requestReplan(taskId: string, fromEpisode: number) {
  return apiRequest<LedgerView>(`${base(taskId)}/replan`, { method: 'POST', body: JSON.stringify({ from_episode: fromEpisode }) });
}

export function adoptReplan(taskId: string, body: { delete_replaced: boolean; confirm_discard?: number[]; confirm_invalidate?: boolean }) {
  return apiRequest<LedgerView>(`${base(taskId)}/replan/adopt`, { method: 'POST', body: JSON.stringify(body) });
}

export function discardReplan(taskId: string) {
  return apiRequest<LedgerView>(`${base(taskId)}/replan/discard`, { method: 'POST' });
}

/** Episode numbers a 409 names when an operation needs them confirmed, e.g. "第 2 集、第 3 集". */
export function discardedEpisodesOf(message: string): number[] {
  if (!/confirm_discard/.test(message)) return [];
  return Array.from(message.matchAll(/第 (\d+) 集/g), match => Number(match[1]));
}
