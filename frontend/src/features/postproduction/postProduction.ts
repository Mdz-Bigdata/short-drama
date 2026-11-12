/**
 * 剪辑合成师: the data the post-production page reads from GET /timeline, and the small sums it shows.
 *
 * The backend works these out (app/core/post_production.py); this file only types them and formats them.
 */
import type { AcceptanceIssue } from '../workbench/DeliveryChecklist';
import type { BgmTrack, Timeline, TimelineClip } from '../workbench/TimelinePanel';

export type AudioSource = 'native' | 'tts' | 'none';
export type SettingKey = 'transitions' | 'dialogue' | 'subtitles' | 'title_card';
export type PostSettings = Record<SettingKey, boolean>;

export interface StudioClip extends TimelineClip {
  audio_source?: AudioSource;
  native_available?: boolean;
}

export interface StudioTimeline extends Omit<Timeline, 'clips' | 'bgm'> {
  clips: StudioClip[];
  bgm: Timeline['bgm'] & { start?: number };
  episode?: number;
}

export interface TensionRow { shot_uid: number | null; shot_id: number; scene_id: string; t: number; seconds: number; tension: number }
export interface SceneMarker { scene_id: string; t: number }
export interface FilmVersion { url: string; revision: number | null; rendered_at: string; compose_mode: string; seconds: number | null; bytes: number | null; episode?: number }
export interface MusicVersion { url: string | null; prompt?: string | null; created_at: string; episode?: number }
export interface PostShot { shot_uid: number | null; image_url: string | null; draft: boolean; audio_source: AudioSource; native_available: boolean }

export interface PostView {
  settings: PostSettings;
  tension: TensionRow[];
  scene_markers: SceneMarker[];
  estimated_bytes: number;
  film_versions: FilmVersion[];
  music_versions?: MusicVersion[];
  shots: PostShot[];
}

export interface StudioTrack extends BgmTrack { match?: number; tags?: string[] }

export interface StudioResponse {
  task_id: string;
  timeline: StudioTimeline;
  summary: { clips: number; included: number; seconds: number; revision: number; audio_sources?: Record<AudioSource, number> };
  bgm_library: StudioTrack[];
  acceptance?: AcceptanceIssue[];
  post?: PostView;
}

/** What stage 6 left that the page shows under 查看提示词. */
export interface SoundRecord {
  music_prompt?: string | null;
  ambience_prompt?: string | null;
  bgm_url?: string | null;
  voice_profile?: string;
  dialogue_directions?: Array<{ shot_id: number; speaker: string; verbatim_text?: string; emotion?: string }>;
}

export const SETTING_KEYS: SettingKey[] = ['transitions', 'dialogue', 'subtitles', 'title_card'];
export const DEFAULT_SETTINGS: PostSettings = { transitions: true, dialogue: true, subtitles: true, title_card: true };

export const clipKey = (clip: { shot_uid?: number | null; shot_id: number }) => clip.shot_uid ?? clip.shot_id;
export const clipRef = (clip: StudioClip) => (clip.shot_uid ? { shot_id: clip.shot_id, shot_uid: clip.shot_uid } : { shot_id: clip.shot_id });

/** A clip's voices in the cut; a timeline saved before the field existed reads from its old flags. */
export function audioSourceOf(clip: StudioClip & { native_audio?: boolean }): AudioSource {
  if (clip.audio_source) return clip.audio_source;
  if (clip.native_audio) return 'native';
  return clip.voice_path ? 'tts' : 'none';
}

/** The row of the running order playing at this moment of the film; before the first shot, none. */
export function rowAt(rows: TensionRow[], time: number): TensionRow | null {
  let found: TensionRow | null = null;
  for (const row of rows) {
    if (row.t <= time + 1e-6) found = row;
    else break;
  }
  if (found && time > found.t + found.seconds + 0.05) return null;
  return found;
}

export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** The tension curve as SVG polyline points: one point at the middle of each shot, plus both ends of the film. */
export function curvePoints(rows: TensionRow[], total: number, width: number, height: number): string {
  if (!rows.length || total <= 0) return '';
  const x = (time: number) => Math.round((Math.min(Math.max(time, 0), total) / total) * width * 10) / 10;
  const y = (score: number) => Math.round((1 - Math.min(Math.max(score, 0), 1)) * height * 10) / 10;
  const points = rows.map(row => `${x(row.t + row.seconds / 2)},${y(row.tension)}`);
  return [`0,${y(rows[0].tension)}`, ...points, `${width},${y(rows[rows.length - 1].tension)}`].join(' ');
}

/** Where on a 0–100% track a moment of the film sits. */
export const percentOf = (time: number, total: number) => (total > 0 ? Math.min(100, Math.max(0, (time / total) * 100)) : 0);

/**
 * Films that still carry a character's old voice (backend voice_relink marks them needs_render_for_voice).
 * Episode numbers in per-episode work; 0 is the film of a project made in one run.
 */
export function filmsNeedingVoiceRender(assets: Record<string, unknown> | null | undefined): number[] {
  const marked = (value: unknown) => Boolean(value && typeof value === 'object' && (value as Record<string, unknown>).needs_render_for_voice);
  const cycle = assets?.episode_cycle as { episodes?: Record<string, unknown> } | undefined;
  const episodes = Object.entries(cycle?.episodes ?? {})
    .filter(([, record]) => marked(record))
    .map(([number]) => Number(number))
    .filter(number => Number.isFinite(number) && number > 0);
  const film = assets?.['7'] as Record<string, unknown> | undefined;
  if (marked(film)) {
    const episode = Number(film?.episode ?? 0);
    if (!episodes.includes(episode)) episodes.push(Number.isFinite(episode) ? episode : 0);
  }
  return episodes.sort((a, b) => a - b);
}
