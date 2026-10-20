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
  /** 旁白交付：合成旁白配音，或留给后期配音（旁白不进入视频提示词）。 */
  narrationDelivery?: NarrationDelivery;
  /** 创作类型 (backend app/core/creation_modes.py)。 */
  creationMode?: CreationMode;
  /** 广告短片的产品简报；其它类型忽略。 */
  adBrief?: AdBrief;
  /** 剧本内容语言：标题、钩子、台词、旁白、正文与画面描述用它来写 (backend content_language)。 */
  contentLanguage?: ContentLanguage;
  oneClick: boolean;
  episodeCount: number;
}

export type NarrationDelivery = 'use_tts' | 'post_production';

export type CreationMode = 'drama' | 'narration' | 'ad';

export interface AdBrief {
  product: string;
  sellingPoints: string;
  audience: string;
  callToAction: string;
}

export const EMPTY_AD_BRIEF: AdBrief = { product: '', sellingPoints: '', audience: '', callToAction: '' };

export type ContentLanguage = 'zh' | 'en' | 'vi';

export const CONTENT_LANGUAGE_OPTIONS: Array<{ id: ContentLanguage; label: string }> = [
  { id: 'zh', label: '中文' },
  { id: 'en', label: 'English' },
  { id: 'vi', label: 'Tiếng Việt' },
];

export const CREATION_MODE_OPTIONS: Array<{ id: CreationMode; label: string; hint: string }> = [
  { id: 'drama', label: '剧情短剧', hint: '角色在画面里说话，按集推进剧情' },
  { id: 'narration', label: '旁白解说', hint: '旁白讲述故事，角色只表演不开口' },
  { id: 'ad', label: '广告短片', hint: '按产品简报做 15–60 秒短片：开场抓人、产品清楚、结尾行动号召' },
];

export const NARRATION_DELIVERY_OPTIONS: Array<{ id: NarrationDelivery; label: string; hint: string }> = [
  { id: 'use_tts', label: '合成旁白配音', hint: '旁白与台词一起生成人声' },
  { id: 'post_production', label: '旁白留给后期', hint: '只合成角色台词，旁白由后期配音' },
];

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
