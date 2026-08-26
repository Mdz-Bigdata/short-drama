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

export interface TaskResponse {
  taskId: string;
  currentStage: number;
  stageName: string;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed' | 'awaiting_quality_review' | 'quality_failed';
  config: {
    titleSuggestion: string;
    scriptName?: string;
    scriptContent?: string;
    directorStyle: string;
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
}
