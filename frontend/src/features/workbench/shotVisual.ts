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
