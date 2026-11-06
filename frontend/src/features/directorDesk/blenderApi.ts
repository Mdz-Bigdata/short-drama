import { apiRequest } from '../../api/client';

/** Local Blender and whether an open Blender has the bridge add-on connected (backend blender_previz_service.status). */
export interface BlenderStatus {
  blender_found: boolean;
  blender_path: string;
  blender_version: string;
  live_connected: boolean;
  live_port: number;
  addon_download: string;
}

export interface PrevizSegment {
  shot_id: number;
  camera: string;
  start: number;
  end: number;
  seconds: number;
}

export interface PrevizRender {
  plan_revision: number;
  video_url: string;
  blend_url: string;
  stills: Array<{ shot_id: number; url: string }>;
  segments: PrevizSegment[];
  fps: number;
  frames: number;
  resolution: [number, number];
  blender_version: string;
  rendered_at: string;
  proxies: Array<{ id: string; name: string; kind: string; color: string }>;
  live?: boolean;
  reused?: boolean;
}

export interface ReservedSlot {
  shot_id: number;
  from_s: number;
  to_s: number;
  label: string;
}

export interface PrevizView {
  scene_id: string;
  options: { handheld_shots?: number[]; reserved?: ReservedSlot[] };
  latest: PrevizRender | null;
  stale: boolean;
  plan_revision: number | null;
}

export interface PullResult {
  operations: Array<Record<string, unknown>>;
  applied: boolean;
  revision?: number;
}

export interface AttachResult {
  attached: Array<{ shot_id: number; capture_id: string; url: string }>;
  failed: Array<{ shot_id: number; error: string }>;
}

export interface AgentReply {
  reply: string;
  tool_calls?: Array<{ tool: string; result?: { ok?: boolean; error?: string } }>;
  proposal?: { tool: string; message: string } | null;
}

const scenePath = (taskId: string, sceneId: string) =>
  `/api/drama/${encodeURIComponent(taskId)}/spatial/scenes/${encodeURIComponent(sceneId)}/blender`;

export const fetchBlenderStatus = () => apiRequest<BlenderStatus>('/api/blender/status');

export const fetchPreviz = (taskId: string, sceneId: string) => apiRequest<PrevizView>(scenePath(taskId, sceneId));

export const renderPreviz = (taskId: string, sceneId: string, longEdge: number, shotIds?: number[]) =>
  apiRequest<PrevizRender>(`${scenePath(taskId, sceneId)}/render`, {
    method: 'POST', body: JSON.stringify({ long_edge: longEdge, ...(shotIds?.length ? { shot_ids: shotIds } : {}) }),
  });

export const savePrevizOptions = (taskId: string, sceneId: string, options: { handheld_shots?: number[]; reserved?: ReservedSlot[] }) =>
  apiRequest<PrevizView>(`${scenePath(taskId, sceneId)}/options`, { method: 'PUT', body: JSON.stringify(options) });

export const attachPreviz = (taskId: string, sceneId: string, shotIds?: number[]) =>
  apiRequest<AttachResult>(`${scenePath(taskId, sceneId)}/attach`, {
    method: 'POST', body: JSON.stringify(shotIds?.length ? { shot_ids: shotIds } : {}),
  });

export const pushToBlender = (taskId: string, sceneId: string) =>
  apiRequest<{ proxies: string[]; cameras: string[] }>(`${scenePath(taskId, sceneId)}/push`, { method: 'POST', body: '{}' });

export const pullFromBlender = (taskId: string, sceneId: string, apply: boolean) =>
  apiRequest<PullResult>(`${scenePath(taskId, sceneId)}/pull`, { method: 'POST', body: JSON.stringify({ apply }) });

/** One turn with the project's tool agent, scoped to this scene so it knows which stage to edit. */
export const askPrevizAgent = (taskId: string, sceneId: string, text: string) =>
  apiRequest<AgentReply>(`/api/drama/${encodeURIComponent(taskId)}/assistant`, {
    method: 'POST', body: JSON.stringify({ message: `/agent 【当前场景 ${sceneId}，Blender 预演台】${text}` }),
  });

/** What a pulled operation does, in one short line. */
export function describeOperation(operation: Record<string, unknown>): string {
  const op = String(operation.op || '');
  if (op === 'move_actor') return `「${String(operation.name)}」移到 ${JSON.stringify(operation.position ?? '')}${operation.yaw_deg !== undefined ? `，朝向 ${String(operation.yaw_deg)}°` : ''}`;
  if (op === 'move_landmark') return `道具「${String(operation.name)}」移到 ${JSON.stringify(operation.position)}`;
  if (op === 'move_camera') return `机位 ${String(operation.camera_id)} 改为 ${String(operation.lens_mm)}mm，位置 ${JSON.stringify(operation.position)}`;
  return op;
}
