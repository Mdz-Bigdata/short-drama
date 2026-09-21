import { apiRequest } from '../../api/client';

export interface ScreenwritingLedgerEntry {
  episode: number;
  title: string;
  hook: string;
  storyBeats: string[];
  nextEpisodeTeaser?: string | null;
  ledgerStatus: string;
}

export interface ScreenwritingEpisodeSummary {
  episode: number;
  title: string;
  sceneCount: number;
  durationSeconds: number;
  planRevision: string;
  violationCount: number;
  needsReplan: string[];
  writtenAt: string;
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
