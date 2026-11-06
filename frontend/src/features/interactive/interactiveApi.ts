import { API_BASE, ApiError, apiRequest } from '../../api/client';
import { getLocale } from '../../i18n';
import { isBatchAdmission, shotPath, type BatchAdmission } from '../workbench/shotVisual';
import type {
  ExportPreview, LibraryShot, MediaLibrary, PlanDraft, PlaytestRun, PlaytestStats, StoryAnalysis, StoryGraph, StoryRecord,
} from './storyTypes';

const base = (taskId: string) => `/api/drama/${encodeURIComponent(taskId)}/interactive-story`;
const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export function fetchStory(taskId: string, signal?: AbortSignal) {
  return apiRequest<StoryRecord>(base(taskId), { signal });
}

export function saveStory(taskId: string, baseRevision: number, graph: StoryGraph) {
  return apiRequest<StoryRecord>(base(taskId), { method: 'PUT', ...json({ base_revision: baseRevision, graph }) });
}

export function analyzeDraft(taskId: string, graph: StoryGraph, signal?: AbortSignal) {
  return apiRequest<StoryAnalysis>(`${base(taskId)}/analyze`, { method: 'POST', signal, ...json({ graph }) });
}

export interface PlanOptions { brief: string; endings: number; minutes: number; useProject: boolean }

export function planStory(taskId: string, options: PlanOptions) {
  const locale = getLocale();
  return apiRequest<PlanDraft>(`${base(taskId)}/plan`, {
    method: 'POST',
    ...json({
      brief: options.brief, endings: options.endings, minutes: options.minutes, use_project: options.useProject,
      language: locale === 'zh-CN' ? 'zh' : locale,
    }),
  });
}

export function fetchMediaLibrary(taskId: string) {
  return apiRequest<MediaLibrary>(`${base(taskId)}/media`);
}

export async function uploadMedia(taskId: string, file: File, durationSeconds: number) {
  const form = new FormData();
  form.append('file', file);
  form.append('duration_s', String(durationSeconds));
  return apiRequest<MediaLibrary['uploads'][number]>(`${base(taskId)}/media`, { method: 'POST', body: form });
}

export function deleteUpload(taskId: string, uploadId: string) {
  return apiRequest<MediaLibrary>(`${base(taskId)}/media/${encodeURIComponent(uploadId)}`, { method: 'DELETE' });
}

/** How long a video file runs, read by the browser; 0 when it cannot tell (the estimate then comes from the text). */
export function measureVideoSeconds(file: File): Promise<number> {
  if (!file.type.startsWith('video/') || typeof URL.createObjectURL !== 'function') return Promise.resolve(0);
  return new Promise(resolve => {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    const finish = (seconds: number) => {
      URL.revokeObjectURL(url);
      resolve(Number.isFinite(seconds) && seconds > 0 ? seconds : 0);
    };
    video.preload = 'metadata';
    video.onloadedmetadata = () => finish(video.duration);
    video.onerror = () => finish(0);
    video.src = url;
  });
}

export function recordPlaytest(taskId: string, run: PlaytestRun) {
  return apiRequest<PlaytestStats>(`${base(taskId)}/playtest`, { method: 'POST', ...json(run) });
}

export function resetPlaytests(taskId: string) {
  return apiRequest<PlaytestStats>(`${base(taskId)}/playtest`, { method: 'DELETE' });
}

export function fetchExportPreview(taskId: string, signal?: AbortSignal) {
  return apiRequest<ExportPreview>(`${base(taskId)}/export/preview`, { signal });
}

/** Fetched rather than linked: a refused export has to come back as a message, not as a downloaded error page. */
export async function downloadExport(taskId: string, format: 'html' | 'zip', filenameBase: string): Promise<void> {
  const response = await fetch(`${API_BASE}${base(taskId)}/export.${format}?lang=${encodeURIComponent(getLocale())}`, { credentials: 'include' });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const data = await response.json() as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // Keep the generic message when the body is not JSON.
    }
    throw new ApiError(detail, response.status);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${filenameBase}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** The project's own video gate: how many shots a stage-5 run would make, and roughly what that costs. Spends nothing. */
export async function fetchAdmission(taskId: string): Promise<BatchAdmission | null> {
  const assessed = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/shots/admission`, { method: 'POST', ...json({}) });
  return isBatchAdmission(assessed) ? assessed : null;
}

export interface CanvasHandoff { project_id: string; canvas_id: string; nodes: Record<string, string>; bound: boolean; version: number }

/** Two nodes on the canvas for one segment: a first frame to draw and the video it feeds. Nothing runs yet. */
export function sendSegmentToCanvas(taskId: string, segmentId: string) {
  return apiRequest<CanvasHandoff>(`${base(taskId)}/segments/${encodeURIComponent(segmentId)}/canvas`, { method: 'POST' });
}

/** The existing per-shot redo: it only marks the clip stale, and the next stage-5 run is what generates (and charges). */
export function markShotForRedo(taskId: string, shot: Pick<LibraryShot, 'shot_id' | 'scene_id'>) {
  return apiRequest<unknown>(shotPath(taskId, shot, 'regenerate'), { method: 'POST', ...json({ reason: '' }) });
}
