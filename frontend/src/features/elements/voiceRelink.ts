/**
 * Changing a character's voice redubs every line they already said (the backend's voice_relink).
 * The preview says how much that touches, so the panel can ask before money is spent.
 */
import { ApiError, apiRequest } from '../../api/client';
import { t } from '../../i18n';

export interface VoiceRelinkPreview {
  name: string;
  lines: number;
  /** Episodes with dubbed lines; 0 stands for a project made in one run. */
  episodes: number[];
  /** Shots that use the clip's own sound and will switch to a dub. */
  native_shots: number;
  billed: boolean;
  provider: string;
  films_to_rerender: number[];
  /** Another character already uses this voice: the cast will be refused. */
  taken_by?: string;
}

export async function fetchRelinkPreview(base: string, name: string, voice: string): Promise<VoiceRelinkPreview | null> {
  try {
    const preview = await apiRequest<VoiceRelinkPreview>(
      `${base}/characters/${encodeURIComponent(name)}/voice-relink-preview?voice=${encodeURIComponent(voice)}`,
    );
    return preview && typeof preview.lines === 'number' ? preview : null;
  } catch (error) {
    // A backend without the preview does not redub either: nothing to warn about.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const episodeList = (episodes: number[]) => {
  const named = episodes.filter(episode => episode > 0);
  return named.length ? t('第 {0} 集', [named.join('、')]) : t('全片');
};

/** The question to ask before the change, or '' when nothing needs asking. */
export function relinkQuestion(preview: VoiceRelinkPreview | null): string {
  if (!preview) return '';
  const parts: string[] = [];
  if (preview.lines > 0) {
    parts.push(preview.billed
      ? t('会自动重配「{0}」在{1}里的 {2} 句台词，由 {3} 配音，会产生费用。', [preview.name, episodeList(preview.episodes), preview.lines, preview.provider])
      : t('会自动重配「{0}」在{1}里的 {2} 句台词。', [preview.name, episodeList(preview.episodes), preview.lines]));
  }
  if (preview.native_shots > 0) parts.push(t('{0} 个用原声的镜头会改成配音，口型可能对不上。', [preview.native_shots]));
  if (preview.films_to_rerender.length) parts.push(t('{0}的成片要重新合成后才会换成新声音。', [episodeList(preview.films_to_rerender)]));
  if (!preview.billed && preview.native_shots === 0) return '';
  return `${t('换成这个声音？')}\n${parts.join('\n')}`;
}

/** How a relink went: done or failed right away, or queued and finished later in the background. */
export interface VoiceRelinkResult {
  status: 'done' | 'failed' | 'queued' | 'running';
  message?: string;
  error?: string;
  films_to_rerender?: number[];
}

export const RELINK_POLL_MS = 3000;
const RELINK_POLL_LIMIT = 300;

/** Poll the preview's relink record until the background redub finishes; null if it never reports back. */
export async function waitForRelink(base: string, name: string, wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))): Promise<VoiceRelinkResult | null> {
  for (let attempt = 0; attempt < RELINK_POLL_LIMIT; attempt += 1) {
    await wait(RELINK_POLL_MS);
    const preview = await apiRequest<{ relink?: VoiceRelinkResult | null }>(
      `${base}/characters/${encodeURIComponent(name)}/voice-relink-preview`,
    ).catch(() => null);
    const relink = preview?.relink;
    if (relink && (relink.status === 'done' || relink.status === 'failed')) return relink;
  }
  return null;
}

/** The line to show for a finished relink. */
export function relinkOutcome(result: VoiceRelinkResult): { ok: boolean; text: string } {
  const ok = result.status === 'done';
  return { ok, text: result.message || result.error || (ok ? t('重配完成。') : t('重配没有完成。')) };
}
