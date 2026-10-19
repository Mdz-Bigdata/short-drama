/** Types and pure helpers for the visual-stage shot workspace (运镜 / 景别 / 时长). */

export interface ShotVisualSettings {
  camera_motion: string;
  shot_type: string;
  duration_seconds: number;
  action: string;
  ambiance_audio: string;
  lighting: string;
  ambiance: string;
  seed?: number | null;
  candidates?: number;
}

export interface VocabularyEntry {
  value: string;
  label: string;
}

export interface ShotRouteDecision {
  mode?: string;
  provider_family?: string;
  reasons?: string[];
  fallbacks?: string[];
  unused_assets?: string[];
}

export interface ShotVisualRecord {
  shot_id: number;
  scene_id: string;
  desc: string;
  dialogue: string;
  sound: string;
  settings: ShotVisualSettings;
  settings_source: 'edited' | 'derived';
  derived_notes: string[];
  image_url?: string | null;
  end_frame_url?: string | null;
  video_url?: string | null;
  candidate_urls?: string[];
  image_prompt: string;
  video_prompt: string;
  contract_fingerprint: string;
  route?: ShotRouteDecision | null;
  stale: boolean;
  stale_reason: string;
  /** 视频提示词是人工改过的版本(下次重做本镜时用它)。 */
  video_prompt_edited?: boolean;
  /** 提示词里 @[名字] 对应的资产类型，供编辑器着色。 */
  mention_kinds?: Record<string, string>;
  /** @[名字] 对应本镜随请求上传的第几张参考图。 */
  reference_numbers?: Record<string, number>;
}

export interface RecipeCategory {
  value: string;
  label: string;
  purpose: string;
}

export interface CameraRecipe {
  category: string;
  category_label: string;
  intensity: 'strong' | 'medium' | 'soft';
  camera_motion: string;
  camera_motion_label: string;
  angle_label: string;
  rhythm_label: string;
  prompt_zh: string;
  prompt_en: string;
  negative: string;
  provider_phrase: string;
}

/** 一镜翻车后的修正方案（backend app/core/generation_feedback.py）。 */
export interface ShotFixPlan {
  category: string;
  category_name: string;
  diagnosis: string;
  attempt: number;
  steps: string[];
  negatives: string[];
  escalation: string;
  give_up: boolean;
}

export interface ShotVisualWorkspace {
  task_id: string;
  current_stage: number;
  running: boolean;
  video_model: string;
  provider_family: string;
  duration_options: number[];
  camera_motions: VocabularyEntry[];
  shot_types: VocabularyEntry[];
  recipe_categories?: RecipeCategory[];
  shots: ShotVisualRecord[];
}

export function vocabularyLabel(entries: VocabularyEntry[], value: string): string {
  return entries.find(entry => entry.value === value)?.label ?? value;
}

/** Same three-way judgement as the project default duration: empty range, in range, out of range. */
export function durationWarning(seconds: number, options: number[]): string {
  if (options.length === 0) return '当前模型未配置可用时长，无法修改';
  if (options.includes(seconds)) return '';
  return `当前秒数 ${seconds} 不在模型支持范围 [${options[0]}-${options[options.length - 1]}] 内`;
}

/** Chips read better for a handful of durations; a continuous run of many seconds becomes a slider. */
export function useSliderForDurations(options: number[]): boolean {
  if (options.length < 8) return false;
  return options.every((value, index) => index === 0 || value === options[index - 1] + 1);
}

export function shotStatus(shot: ShotVisualRecord): { key: 'stale' | 'ready' | 'partial' | 'pending'; label: string } {
  if (shot.stale) return { key: 'stale', label: '需重跑' };
  if (shot.video_url) return { key: 'ready', label: '已生成' };
  if (shot.image_url) return { key: 'partial', label: '仅首帧' };
  return { key: 'pending', label: '待生成' };
}

export function settingsEqual(left: ShotVisualSettings, right: ShotVisualSettings): boolean {
  return (Object.keys(left) as Array<keyof ShotVisualSettings>).every(key => left[key] === right[key]);
}

/** One shot's part in a batch admission (backend app/core/video_admission.py). */
export interface ShotAdmission {
  shot_id: number;
  scene_id: string;
  quote: 'generate' | 'reuse' | 'blocked';
  scripted_seconds: number;
  requested_seconds: number;
  tier_adjustment: 'exact' | 'up' | 'down';
  candidates: number;
  problems: Array<{ code: string; message: string; blocking: boolean }>;
  withheld_by: number[];
  estimate: { priced: boolean; cost: number | null; currency: string | null };
}

export interface TierConfirmation {
  scripted_seconds: number;
  requested_seconds: number;
  adjustment: 'up' | 'down' | 'exact';
  shot_ids: number[];
  shot_count: number;
  cost: number | null;
  currency: string | null;
  priced: boolean;
}

/** The whole batch's admission: every shot is submitted, or none is. */
export interface BatchAdmission {
  decision: 'admitted' | 'confirmation_required' | 'blocked';
  video_model: string;
  provider_family: string;
  counts: { generate: number; reuse: number; blocked: number; withheld: number };
  shots: ShotAdmission[];
  confirmations: TierConfirmation[];
  estimate: { shots_to_generate: number; requested_seconds: number; priced: boolean; cost: number | null; currency: string | null };
}

export interface UsageSummary {
  calls: number;
  succeeded: number;
  failed: number;
  cost_by_currency: Record<string, number>;
  primary_currency: string | null;
  unpriced_calls: number;
  unpriced_models: string[];
}

export function isBatchAdmission(value: unknown): value is BatchAdmission {
  const candidate = value as Partial<BatchAdmission> | null;
  return Boolean(candidate && typeof candidate.decision === 'string' && Array.isArray(candidate.shots) && candidate.counts);
}

export function isUsageSummary(value: unknown): value is UsageSummary {
  const candidate = value as Partial<UsageSummary> | null;
  return Boolean(candidate && typeof candidate.calls === 'number' && candidate.cost_by_currency && typeof candidate.cost_by_currency === 'object');
}

export const ADMISSION_LABELS: Record<BatchAdmission['decision'], string> = {
  admitted: '准入通过：可提交全部镜头',
  confirmation_required: '需确认时长档位后才能提交',
  blocked: '受阻：整批未提交，未产生费用',
};

/** Amount with its currency; a figure that could not be priced is said so rather than shown as zero. */
export function formatCost(cost: number | null | undefined, currency: string | null | undefined, priced = true): string {
  if (!priced || cost === null || cost === undefined || !currency) return '未定价';
  return `${cost.toFixed(2)} ${currency}`;
}

export function formatCostByCurrency(costs: Record<string, number>): string {
  const entries = Object.entries(costs);
  if (entries.length === 0) return '0';
  return entries.map(([currency, amount]) => `${amount.toFixed(2)} ${currency}`).join(' + ');
}

/** One item of the stage-5 generation queue (backend app/core/generation_queue.py). */
export interface QueueItem {
  key: string;
  label: string;
  family: string;
  medium: 'video' | 'image' | 'audio' | 'text' | string;
  bucket: string;
  depends_on: string[];
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'skipped';
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  reason?: string | null;
  meta: Record<string, unknown>;
}

export interface GenerationQueue {
  task_id: string;
  running: boolean;
  run_id?: string | null;
  updated_at?: string | null;
  counts: Partial<Record<QueueItem['status'], number>>;
  buckets: Record<string, { limit: number; running: number }>;
  items: QueueItem[];
  withdraw?: string[];
}

export function isGenerationQueue(value: unknown): value is GenerationQueue {
  const candidate = value as Partial<GenerationQueue> | null;
  return Boolean(candidate && Array.isArray(candidate.items) && candidate.buckets && typeof candidate.buckets === 'object');
}

export const QUEUE_STATUS_LABELS: Record<QueueItem['status'], string> = {
  queued: '排队中',
  running: '运行中',
  done: '完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
};
