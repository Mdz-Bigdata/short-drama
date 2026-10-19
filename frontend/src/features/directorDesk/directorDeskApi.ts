import { apiRequest } from '../../api/client';
import type { StagePose } from '../spatial/spatialTypes';

/** `backdrop` is the scene's framing underlay: it is never handed to a shot. */
export type CaptureKind = 'still' | 'clip' | 'backdrop';

export interface DeskCapture {
  id: string;
  kind: CaptureKind;
  shotId: number;
  cameraId: string;
  url: string;
  width: number;
  height: number;
  durationS: number;
  fps: number;
  planRevision: number;
  showsLimbs: boolean;
  monochrome: boolean;
  labelled: boolean;
  /** A grayscale depth picture: layers, blocking and camera motion only. A depth still cannot be applied. */
  depth: boolean;
  createdAt: string;
  stale: boolean;
  /** What the server has to say about this capture (a limbed white model needs its motion spelled out). */
  warning: string;
}

export interface DeskCaptureList {
  captures: DeskCapture[];
  /** shot id → the capture ids currently written into that shot's generation slots. */
  applied: Record<string, { still: string; clip: string }>;
}

export interface CaptureUpload {
  blob: Blob;
  /** Omitted means a still. */
  kind?: CaptureKind;
  shotId: number;
  cameraId: string;
  width: number;
  height: number;
  planRevision: number;
  showsLimbs: boolean;
  monochrome: boolean;
  labelled: boolean;
  /** Rendered as linear depth (near bright, far dark). Refused on a backdrop. */
  depth?: boolean;
  /** Clips only. */
  durationS?: number;
  fps?: number;
}

/** What the server accepts (director_desk_service.validate_upload); refused here first, before 60 MB leave the machine. */
export const CAPTURE_LIMITS = {
  stillBytes: 10 * 1024 * 1024, clipBytes: 60 * 1024 * 1024, clipSeconds: 30, clipFrameRates: [24, 25, 30],
  stillTypes: ['image/png', 'image/jpeg', 'image/webp'], clipTypes: ['video/mp4', 'video/webm'],
};

/** Why this upload would be refused, or '' when it is fine. */
export function uploadRefusal(upload: CaptureUpload): string {
  const type = upload.blob.type.split(';')[0];
  if (!upload.blob.size) return '上传的文件是空的';
  if (upload.kind === 'clip') {
    if (!CAPTURE_LIMITS.clipTypes.includes(type)) return '白模视频只支持 MP4、WebM';
    if (upload.blob.size > CAPTURE_LIMITS.clipBytes) return '白模视频不能超过 60 MB';
    if (!(Number(upload.durationS) > 0) || Number(upload.durationS) > CAPTURE_LIMITS.clipSeconds) return '白模视频时长必须在 0 到 30 秒之间';
    if (!CAPTURE_LIMITS.clipFrameRates.includes(Number(upload.fps))) return 'fps 只能是 24 / 25 / 30（与时间线的帧率一致）';
    return '';
  }
  const what = upload.kind === 'backdrop' ? '背景图' : '静帧';
  if (!CAPTURE_LIMITS.stillTypes.includes(type)) return `${what}只支持 PNG、JPEG、WebP`;
  if (upload.blob.size > CAPTURE_LIMITS.stillBytes) return `${what}不能超过 10 MB`;
  return '';
}

const IMAGE_EXTENSIONS: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' };

const base = (taskId: string, sceneId: string) =>
  `/api/drama/${encodeURIComponent(taskId)}/director-desk/scenes/${encodeURIComponent(sceneId)}/captures`;

type Loose = Record<string, unknown>;

// A Capture is stored snake_case under the task's assets while the API envelope is camelCase;
// reading both spellings keeps the desk working whichever side of that line the record is served from.
function field(source: Loose, camel: string, snake: string): unknown {
  return source[camel] ?? source[snake];
}

export function normalizeCapture(raw: unknown): DeskCapture {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Loose;
  return {
    id: String(source.id ?? ''),
    kind: source.kind === 'clip' || source.kind === 'backdrop' ? source.kind : 'still',
    shotId: Number(field(source, 'shotId', 'shot_id')) || 0,
    cameraId: String(field(source, 'cameraId', 'camera_id') ?? ''),
    url: String(source.url ?? ''),
    width: Number(source.width) || 0,
    height: Number(source.height) || 0,
    durationS: Number(field(source, 'durationS', 'duration_s')) || 0,
    fps: Number(source.fps) || 0,
    planRevision: Number(field(source, 'planRevision', 'plan_revision')) || 0,
    showsLimbs: Boolean(field(source, 'showsLimbs', 'shows_limbs')),
    monochrome: Boolean(source.monochrome),
    labelled: Boolean(source.labelled),
    depth: Boolean(source.depth),
    createdAt: String(field(source, 'createdAt', 'created_at') ?? ''),
    stale: Boolean(source.stale),
    warning: String(source.warning ?? ''),
  };
}

function normalizeList(raw: unknown): DeskCaptureList {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Loose;
  const applied: DeskCaptureList['applied'] = {};
  Object.entries((source.applied && typeof source.applied === 'object' ? source.applied : {}) as Record<string, Loose | null>).forEach(([shotId, slot]) => {
    applied[shotId] = { still: String(slot?.still ?? ''), clip: String(slot?.clip ?? '') };
  });
  const captures = (Array.isArray(source.captures) ? source.captures : []).map(normalizeCapture);
  // Newest first, whatever order they were stored in.
  captures.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return { captures, applied };
}

export function isApplied(list: DeskCaptureList, capture: DeskCapture): boolean {
  // A backdrop has no slot on a shot, so it is never "applied".
  if (capture.kind === 'backdrop') return false;
  const held = list.applied[String(capture.shotId)]?.[capture.kind];
  return Boolean(held) && held === capture.id;
}

export function listCaptures(taskId: string, sceneId: string, signal?: AbortSignal) {
  return apiRequest<unknown>(base(taskId, sceneId), { signal }).then(normalizeList);
}

export function uploadCapture(taskId: string, sceneId: string, upload: CaptureUpload) {
  const refusal = uploadRefusal(upload);
  if (refusal) return Promise.reject(new Error(refusal));
  const clip = upload.kind === 'clip';
  const extension = clip
    ? (upload.blob.type.startsWith('video/webm') ? 'webm' : 'mp4')
    : (IMAGE_EXTENSIONS[upload.blob.type.split(';')[0]] || 'png');
  const name = upload.kind === 'backdrop' ? 'backdrop' : `shot-${upload.shotId}-${upload.cameraId || 'lens'}`;
  const form = new FormData();
  form.append('file', upload.blob, `${name}.${extension}`);
  form.append('kind', upload.kind || 'still');
  form.append('shot_id', String(upload.shotId));
  form.append('camera_id', upload.cameraId);
  form.append('width', String(upload.width));
  form.append('height', String(upload.height));
  form.append('plan_revision', String(upload.planRevision));
  form.append('shows_limbs', String(upload.showsLimbs));
  form.append('monochrome', String(upload.monochrome));
  form.append('labelled', String(upload.labelled));
  // A backdrop is a picture of a place, never a depth map; the server refuses the field on one.
  if (upload.kind !== 'backdrop') form.append('depth', String(Boolean(upload.depth)));
  if (clip) {
    form.append('duration_s', String(upload.durationS));
    form.append('fps', String(upload.fps));
  }
  return apiRequest<unknown>(base(taskId, sceneId), { method: 'POST', body: form })
    .then(raw => normalizeCapture((raw as Loose | null)?.capture ?? raw));
}

// Every change answers with the scene's whole capture state, so the panel never has to ask again.
export function applyCapture(taskId: string, sceneId: string, captureId: string) {
  return apiRequest<unknown>(`${base(taskId, sceneId)}/${encodeURIComponent(captureId)}/apply`, { method: 'POST' }).then(normalizeList);
}

export function unapplyCapture(taskId: string, sceneId: string, captureId: string) {
  return apiRequest<unknown>(`${base(taskId, sceneId)}/${encodeURIComponent(captureId)}/unapply`, { method: 'POST' }).then(normalizeList);
}

export function deleteCapture(taskId: string, sceneId: string, captureId: string) {
  return apiRequest<unknown>(`${base(taskId, sceneId)}/${encodeURIComponent(captureId)}`, { method: 'DELETE' }).then(normalizeList);
}

/** Captures are served by absolute URL behind the session cookie, so a plain link cannot save them. */
export async function downloadCapture(capture: DeskCapture): Promise<boolean> {
  try {
    const response = await fetch(capture.url, { credentials: 'include' });
    if (!response.ok) return false;
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${capture.kind === 'clip' ? 'clip' : 'still'}-shot${capture.shotId}-${capture.id}.${capture.kind === 'clip' ? (/\.webm($|\?)/i.test(capture.url) ? 'webm' : 'mp4') : 'png'}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch {
    return false;
  }
}

export interface SavedPose {
  id: string;
  name: string;
  pose: StagePose;
  createdAt: string;
}

// The pose library belongs to the signed-in person, not to the project that happens to be open.
const POSES = '/api/director-desk/poses';
export const MAX_POSE_NAME = 40;

function normalizePoses(raw: unknown): SavedPose[] {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Loose;
  return (Array.isArray(source.poses) ? source.poses : []).map(item => {
    const record = (item && typeof item === 'object' ? item : {}) as Loose;
    return {
      id: String(record.id ?? ''), name: String(record.name ?? ''),
      pose: (record.pose && typeof record.pose === 'object' ? record.pose : {}) as StagePose,
      createdAt: String(field(record, 'createdAt', 'created_at') ?? ''),
    };
  }).filter(item => item.id);
}

export function listSavedPoses(signal?: AbortSignal) {
  return apiRequest<unknown>(POSES, { signal }).then(normalizePoses);
}

/** Saving under a name that exists replaces that pose. */
export function savePose(name: string, pose: StagePose) {
  return apiRequest<unknown>(POSES, { method: 'POST', body: JSON.stringify({ name, pose }) }).then(normalizePoses);
}

export function deleteSavedPose(poseId: string) {
  return apiRequest<unknown>(`${POSES}/${encodeURIComponent(poseId)}`, { method: 'DELETE' }).then(normalizePoses);
}
