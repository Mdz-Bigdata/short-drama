export type VideoReferenceMode = 'auto' | 'first_last_frame' | 'multi_reference' | 'multimodal';
export type StoredVideoReferenceMode = VideoReferenceMode | 'first_frame';

export function normalizeVideoReferenceMode(value?: StoredVideoReferenceMode | string | null): VideoReferenceMode {
  return value === 'first_last_frame' || value === 'multi_reference' || value === 'multimodal'
    ? value
    : 'auto';
}

export interface TaskConfig {
  titleSuggestion: string;
  scriptName?: string;
  scriptContent?: string;
  directorStyle: string;
  /** 全片风格锁：每一镜的图与视频提示词都按它编译 (backend app/core/style_packs.py)。 */
  stylePack?: string;
  shotStyle: string;
  llmModel: string;
  imageModel: string;
  videoModel: string;
  ttsModel: string;
  videoReferenceMode: VideoReferenceMode;
  oneClick: boolean;
  episodeCount: number;
}

export interface StageProgressCall {
  name: string;
  status: 'running' | 'done' | 'error';
  startedAt?: string;
  started_at?: string;
  completedAt?: string;
  completed_at?: string;
  durationMs?: number;
  duration_ms?: number;
}

export interface StageProgress {
  stage: number;
  stageLabel?: string;
  stage_label?: string;
  percent: number;
  label: string;
  status: 'running' | 'success' | 'error';
  error?: string | null;
  calls?: StageProgressCall[];
  startedAt?: string;
  started_at?: string;
  updatedAt?: string;
  updated_at?: string;
  elapsedMs?: number;
  elapsed_ms?: number;
}

export interface WorkflowSnapshot {
  stages: Array<{
    stage: number;
    label: string;
    state: 'complete' | 'running' | 'pending';
    missing: string[];
    guidance: string;
  }>;
  next_stage: number | null;
  active_stage: number | null;
  completed_stages: number[];
  production_complete: boolean;
  release_ready: boolean;
  mode: 'running' | 'ready' | 'paused' | 'blocked' | 'review' | 'completed';
  hint: string;
  actions: Array<{ kind: string; label: string; message: string; stage?: number }>;
  event_id: string;
}

export interface TaskChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

/** What GET /api/drama/list returns: the lobby row without generated assets.
 *  A project's assets are fetched per project through /{task_id}/status. */
export type TaskSummary = Omit<TaskResponse, 'assets' | 'logs'>;

export interface TaskResponse {
  taskId: string;
  currentStage: number;
  stageName: string;
  status: 'idle' | 'running' | 'paused' | 'stopped' | 'completed' | 'failed' | 'interrupted' | 'awaiting_quality_review' | 'quality_failed' | 'awaiting_council_review' | 'council_quality_failed';
  config: {
    titleSuggestion: string;
    scriptName?: string;
    scriptContent?: string;
    directorStyle: string;
    stylePack?: string;
    shotStyle: string;
    llmModel: string;
    imageModel: string;
    videoModel: string;
    ttsModel: string;
    videoReferenceMode?: StoredVideoReferenceMode;
    oneClick: boolean;
    episodeCount?: number;
  };
  assets: {
    // Provider/stage payloads are intentionally heterogeneous and validated by
    // the backend contracts before rendering.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    [key: string]: any;
  };
  logs: {
    [key: string]: string;
  };
  videoUrl?: string;
  shortLink?: string;
  prContent?: string;
  stageProgress?: StageProgress | null;
  failReason?: string | null;
  workflow?: WorkflowSnapshot;
  chatHistory?: TaskChatEntry[];
}
