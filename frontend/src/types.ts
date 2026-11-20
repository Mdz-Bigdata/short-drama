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
  /** 目标用户：男频 / 女频与年龄段，空值由总导演定 (backend app/core/target_audience.py)；只对连续剧生效。 */
  targetAudience?: TargetAudience;
  /** 剧本结构：三幕式、五幕式、英雄旅程…的代码值，空值由总导演定 (backend app/core/script_structure.py)；广告不用。 */
  scriptStructure?: string;
  /** 立项前挑中的故事方向 (backend app/core/story_direction.py)；没挑由总导演定，广告不用。 */
  storyDirection?: { title: string; logline: string; conflict: string; hook: string; appeal: string };
  /** 创作禁区：创作者明确不要出现的东西，一条一句。 */
  storyNoGo?: string[];
  /** 连载立项 (backend app/core/serial_brief.py, paywall_plan.py)：题材最多三个、第一个定基调；都可以不选，只对连续剧生效。 */
  storyGenres?: string[];
  storyTone?: string;
  endingType?: string;
  overseas?: boolean;
  /** 按集数规划付费卡点；不到起步集数的剧不规划。 */
  paywallPlan?: boolean;
  oneClick: boolean;
  episodeCount: number;
  /** 编剧可引用、化用的诗词库作者或篇名 (backend app/core/poetry_library.py)；空表示不用诗词库。 */
  poetrySources?: string[];
}

export type NarrationDelivery = 'use_tts' | 'post_production';

export type AudienceLean = '' | 'male' | 'female';

export type AudienceAge = '' | 'youth' | 'adult' | 'senior';

export interface TargetAudience {
  lean: AudienceLean;
  age: AudienceAge;
}

export const EMPTY_TARGET_AUDIENCE: TargetAudience = { lean: '', age: '' };

export type CreationMode = 'drama' | 'narration' | 'ad' | 'film';

export interface AdBrief {
  product: string;
  sellingPoints: string;
  audience: string;
  callToAction: string;
  /** 'story'：剧情带货——先讲一场小戏，产品在戏里自然出场；空着是普通广告短片。 */
  format?: '' | 'story';
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
  { id: 'film', label: '电影短片', hint: '一集讲完的完整短片：一个人、一个困境、一次回不了头的选择，结尾收住' },
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
    /** 用户看到的第几步：第 6、7 阶段同属剪辑合成师，都是第 6 步，宣发是第 7 步。 */
    step?: number;
    label: string;
    state: 'complete' | 'running' | 'pending';
    missing: string[];
    guidance: string;
  }>;
  next_stage: number | null;
  active_stage: number | null;
  completed_stages: number[];
  /** 用户看到的总步数(7)与已完成步数；旧快照没有，就按阶段数算。 */
  steps_total?: number;
  steps_done?: number;
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
  /** 助手这一轮的界面事件(捏脸已更新、舞台已改)，服务端存下来，重开项目后照样做成卡片。 */
  ui_actions?: unknown[];
  /** 助手这一轮提出、等用户确认的付费操作。 */
  proposal?: unknown;
  /** 模型随回复给出的可读思考(只在助手消息上)，界面默认折叠，仅供参考。 */
  reasoning?: string;
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
