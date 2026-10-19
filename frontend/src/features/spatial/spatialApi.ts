import { apiRequest } from '../../api/client';
import type { SpatialPlanResponse, SpatialRepairsResponse, StageOperation } from './spatialTypes';

const base = (taskId: string, sceneId: string) =>
  `/api/drama/${encodeURIComponent(taskId)}/spatial/scenes/${encodeURIComponent(sceneId)}`;

export function fetchSpatialPlan(taskId: string, sceneId: string, signal?: AbortSignal) {
  return apiRequest<SpatialPlanResponse>(base(taskId, sceneId), { signal });
}

/** `solve: false` keeps a drag from re-solving the lens the user is looking through; omitted, the server decides. */
export function patchSpatialPlan(
  taskId: string, sceneId: string, baseRevision: number, operations: StageOperation[], options: { solve?: boolean } = {},
) {
  return apiRequest<SpatialPlanResponse>(base(taskId, sceneId), {
    method: 'PATCH',
    body: JSON.stringify({ baseRevision, operations, ...(options.solve === undefined ? {} : { solve: options.solve }) }),
  });
}

/** Repairs for the checks that fail right now; the desk sends them through its own edit path so they can be undone. */
export function fetchSpatialRepairs(taskId: string, sceneId: string, signal?: AbortSignal) {
  return apiRequest<SpatialRepairsResponse>(`${base(taskId, sceneId)}/repairs`, { signal });
}

export function rebuildSpatialPlan(taskId: string, sceneId: string, baseRevision: number) {
  return apiRequest<SpatialPlanResponse>(`${base(taskId, sceneId)}/rebuild`, {
    method: 'POST',
    body: JSON.stringify({ baseRevision }),
  });
}

export function redrawSpatialScene(taskId: string, sceneId: string) {
  return apiRequest<SpatialPlanResponse>(`${base(taskId, sceneId)}/redraw`, { method: 'POST' });
}

export type SpatialExportFormat = 'director-desk' | 'costage';

export function exportSpatialPlan(taskId: string, sceneId: string, format: SpatialExportFormat) {
  return apiRequest<{ fileName: string; document: Record<string, unknown>; note?: string | null }>(
    `${base(taskId, sceneId)}/export?format=${format}`,
  );
}

export function importSpatialPlan(taskId: string, sceneId: string, baseRevision: number, document: unknown) {
  return apiRequest<SpatialPlanResponse>(`${base(taskId, sceneId)}/import`, {
    method: 'POST',
    body: JSON.stringify({ baseRevision, document }),
  });
}
