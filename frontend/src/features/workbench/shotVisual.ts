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

/** 供应商没给这张看板出片(backend app/core/video_failures.py)；看板出片后清除。 */
export interface ShotVideoFailure {
  kind: 'input_image_sensitive' | 'provider_error';
  kind_label?: string;
  code?: string;
  /** 供应商原话。 */
  message: string;
  hint?: string;
  /** 本看板发出去的分镜画面。 */
  panels?: string[];
  scene_id?: string;
  at?: number | null;
}

export interface ShotVisualRecord {
  shot_id: number;
  scene_id: string;
  /** 全剧唯一的镜头编号(集·场·镜)；各场镜号都从 1 起。 */
  shot_uid?: number;
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
  /** 本镜所在看板最近一次没出片的原因。 */
  failure?: ShotVideoFailure | null;
}

/** 一镜在工作区里的键：各场镜号都从 1 起，只用镜号会把不同场的「镜头 1」混成一个。 */
export function shotKey(shot: Pick<ShotVisualRecord, 'shot_id' | 'scene_id'>): string {
  return `${shot.scene_id}#${shot.shot_id}`;
}

/** 单镜接口的地址：带上场号，后端据此找到这一镜和它所在的那段片段视频。 */
export function shotPath(taskId: string, shot: Pick<ShotVisualRecord, 'shot_id' | 'scene_id'>, action: string): string {
  const scope = shot.scene_id ? `?scene_id=${encodeURIComponent(shot.scene_id)}` : '';
  return `/api/drama/${encodeURIComponent(taskId)}/shots/${shot.shot_id}/${action}${scope}`;
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
  /** 本轮只改的那一类变量（动作 / 镜头 / 参考素材 / 声音）；连续两轮没改善会换一类。 */
  variable?: string;
  variable_name?: string;
  reconsidered?: string[];
}

/** The clip made before the batch (backend app/core/pilot_shot.py). */
export interface ShotPilot {
  state: 'requested' | 'running' | 'ready' | 'failed';
  shot_id?: number;
  shot_uid?: number;
  label?: string;
  reason?: string;
  error?: string;
  video_url?: string;
  others_left?: number;
  checks?: string[];
}

export interface ShotVisualWorkspace {
  task_id: string;
  current_stage: number;
  running: boolean;
  pilot?: ShotPilot | null;
  video_model: string;
  provider_family: string;
  /** 模型配置中心启用的视频模型。 */
  enabled_video_models?: string[];
  /** 项目当前视频模型不能用的原因(如未在模型配置中心启用)；空串表示可用。 */
  video_model_issue?: string;
  /** 项目原选的视频模型被模型配置中心的型号替换时的说明(不阻断)。 */
  video_model_note?: string;
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

export type ShotStatusKey = 'refused' | 'failed' | 'stale' | 'ready' | 'partial' | 'pending';

export function shotStatus(shot: ShotVisualRecord): { key: ShotStatusKey; label: string } {
  // 供应商拒单要一眼看出来：看板最近一次没出片时，它压过其他状态。
  if (shot.failure) {
    return shot.failure.kind === 'input_image_sensitive' ? { key: 'refused', label: '被拒' } : { key: 'failed', label: '失败' };
  }
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

/** 还在等人看的项(排队 / 运行 / 失败)和已经结束的项(完成 / 取消 / 跳过)；结束的默认折叠起来。 */
export function splitQueueItems(items: QueueItem[]): { active: QueueItem[]; settled: QueueItem[] } {
  const settled = new Set<QueueItem['status']>(['done', 'cancelled', 'skipped']);
  return {
    active: items.filter(item => !settled.has(item.status)),
    settled: items.filter(item => settled.has(item.status)),
  };
}

/** 受阻的镜头按「同一句原因」归并：第 5 阶段运行中时每一镜都是同一句话，不必逐镜重复。 */
export function groupBlockedShots(admission: BatchAdmission): Array<{ message: string; shots: ShotAdmission[] }> {
  const groups = new Map<string, ShotAdmission[]>();
  for (const shot of admission.shots) {
    if (shot.quote !== 'blocked') continue;
    for (const problem of shot.problems) {
      if (!problem.blocking) continue;
      const bucket = groups.get(problem.message) ?? [];
      if (!bucket.includes(shot)) bucket.push(shot);
      groups.set(problem.message, bucket);
    }
  }
  return [...groups].map(([message, shots]) => ({ message, shots }));
}

/** 一组镜头的简短写法：覆盖全部时说「全部 N 镜」，否则按场列镜号(各场镜号都从 1 起)。 */
export function describeShots(shots: Array<Pick<ShotAdmission, 'shot_id' | 'scene_id'>>, total: number): string {
  if (total > 0 && shots.length === total) return `全部 ${total} 镜`;
  const byScene = new Map<string, number[]>();
  for (const shot of shots) {
    byScene.set(shot.scene_id, [...(byScene.get(shot.scene_id) ?? []), shot.shot_id]);
  }
  const parts: string[] = [];
  let listed = 0;
  for (const [scene, ids] of byScene) {
    if (listed >= 12) {
      parts.push(`等共 ${shots.length} 镜`);
      break;
    }
    parts.push(`${scene ? `${scene} ` : ''}镜头 ${ids.join('、')}`);
    listed += ids.length;
  }
  return parts.join(' · ');
}


/** 工作区左栏的分集卡：从镜头推出来的进度，加上外层给的标题与成片状态。 */
export interface EpisodeMeta {
  number: number;
  title?: string;
  /** 这一集已出成片。 */
  filmDone?: boolean;
}

export interface EpisodeSummary extends EpisodeMeta {
  shotCount: number;
  generated: number;
  seconds: number;
  thumbnail: string | null;
  /** 第一镜的键，点卡片时选中它。 */
  firstKey: string;
}

export function episodeNumberOf(sceneId: string): number {
  const match = /^E(\d+)/.exec(sceneId || '');
  return match ? Number(match[1]) : 0;
}

export function episodeSummaries(shots: ShotVisualRecord[], meta: EpisodeMeta[] = []): EpisodeSummary[] {
  const byNumber = new Map<number, EpisodeSummary>();
  for (const shot of shots) {
    const number = episodeNumberOf(shot.scene_id);
    const entry = byNumber.get(number) ?? {
      number, shotCount: 0, generated: 0, seconds: 0, thumbnail: null, firstKey: shotKey(shot),
      ...(meta.find(item => item.number === number) ?? {}),
    };
    entry.shotCount += 1;
    if (shot.video_url && !shot.stale) entry.generated += 1;
    entry.seconds += Number(shot.settings?.duration_seconds) || 0;
    if (!entry.thumbnail && shot.image_url) entry.thumbnail = shot.image_url;
    byNumber.set(number, entry);
  }
  return [...byNumber.values()].sort((a, b) => a.number - b.number);
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}
