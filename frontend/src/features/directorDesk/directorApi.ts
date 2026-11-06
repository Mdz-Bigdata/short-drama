import { apiRequest, apiUrl } from '../../api/client';
import type { LandmarkPart, SpatialPlanResponse, StagePlan } from '../spatial/spatialTypes';
import type { BlockoutProposal } from './directorDeskApi';

const base = (taskId: string, sceneId: string) =>
  `/api/drama/${encodeURIComponent(taskId)}/director-desk/scenes/${encodeURIComponent(sceneId)}`;

export interface StageMeasure {
  score: number;
  errors: number;
  warnings: number;
  failing: string[];
  notes: string[];
}

export interface StagePlanCandidate {
  id: string;
  title: string;
  rationale: string;
  source: 'model' | 'rules';
  score: number;
  measured: StageMeasure;
  errors: string[];
  plan: StagePlan;
}

export interface StageChange {
  actors: string[];
  pieces_added: string[];
  pieces_changed: string[];
  pieces_removed: string[];
  cameras: string[];
}

export interface StageChatRow {
  role: 'user' | 'assistant';
  text: string;
  at?: string;
  scope?: string;
  changed?: StageChange;
  compare?: string;
  errors?: string[];
  snapshot_id?: string;
}

export interface StageDirectorState {
  chat: StageChatRow[];
  snapshots: Array<{ id: string; label: string; at: string; revision: number }>;
  candidates: StagePlanCandidate[];
  measured: StageMeasure;
  planner: 'rules' | 'model';
  planner_note: string;
  pipeline_planner: 'model' | 'rules';
}

export interface StagePlanResult {
  candidates: StagePlanCandidate[];
  recommended: string;
  used_model: boolean;
  note: string;
  current: StageMeasure;
}

export interface StageTurnResult extends Partial<SpatialPlanResponse> {
  message: StageChatRow;
  changed: boolean;
  measured: StageMeasure;
  failing: string[];
}

export interface ModelProposal {
  name: string;
  kind: 'prop' | 'furniture' | 'architecture' | 'light';
  kit: string;
  size: [number, number, number];
  summary: string;
  parts: LandmarkPart[];
  dropped: number;
  model: string;
}

export interface ModelKit {
  id: string;
  name: string;
  group: string;
  kind: ModelProposal['kind'];
  size: [number, number, number];
  aliases: string[];
}

interface Scope {
  names?: string[];
  shotId?: number;
}

const scopeBody = (scope: Scope = {}) => ({ names: scope.names ?? [], shot_id: scope.shotId ?? null });

export function fetchDirectorState(taskId: string, sceneId: string, signal?: AbortSignal) {
  return apiRequest<StageDirectorState>(`${base(taskId, sceneId)}/director`, { signal });
}

export function planStage(taskId: string, sceneId: string, baseRevision: number, options: { count: number; goal: string }) {
  return apiRequest<StagePlanResult>(`${base(taskId, sceneId)}/director/plan`, {
    method: 'POST', body: JSON.stringify({ base_revision: baseRevision, count: options.count, goal: options.goal }),
  });
}

export function adoptStagePlan(taskId: string, sceneId: string, baseRevision: number, candidateId: string) {
  return apiRequest<SpatialPlanResponse>(`${base(taskId, sceneId)}/director/adopt`, {
    method: 'POST', body: JSON.stringify({ base_revision: baseRevision, candidate_id: candidateId }),
  });
}

export function chatWithDirector(taskId: string, sceneId: string, baseRevision: number, message: string, scope?: Scope) {
  return apiRequest<StageTurnResult>(`${base(taskId, sceneId)}/director/chat`, {
    method: 'POST', body: JSON.stringify({ base_revision: baseRevision, message, ...scopeBody(scope) }),
  });
}

export function optimizeStage(taskId: string, sceneId: string, baseRevision: number, goal: string, scope?: Scope) {
  return apiRequest<StageTurnResult>(`${base(taskId, sceneId)}/director/optimize`, {
    method: 'POST', body: JSON.stringify({ base_revision: baseRevision, message: goal, ...scopeBody(scope) }),
  });
}

export function revertStageStep(taskId: string, sceneId: string, baseRevision: number, snapshotId: string) {
  return apiRequest<SpatialPlanResponse>(`${base(taskId, sceneId)}/director/revert`, {
    method: 'POST', body: JSON.stringify({ base_revision: baseRevision, snapshot_id: snapshotId }),
  });
}

export function clearDirectorChat(taskId: string, sceneId: string) {
  return apiRequest<unknown>(`${base(taskId, sceneId)}/director/chat`, { method: 'DELETE' });
}

export function setPipelinePlanner(taskId: string, mode: 'model' | 'rules') {
  return apiRequest<{ pipeline_planner: 'model' | 'rules' }>(`/api/drama/${encodeURIComponent(taskId)}/director-desk/planner`, {
    method: 'PUT', body: JSON.stringify({ mode }),
  });
}

export function proposeModel(taskId: string, sceneId: string, description: string, file?: File | null) {
  const form = new FormData();
  form.append('description', description);
  if (file) form.append('file', file, file.name);
  return apiRequest<ModelProposal>(`${base(taskId, sceneId)}/models/propose`, { method: 'POST', body: form });
}

export function describeBlockout(taskId: string, sceneId: string, description: string, widthM?: number) {
  return apiRequest<BlockoutProposal>(`${base(taskId, sceneId)}/blockout/describe`, {
    method: 'POST', body: JSON.stringify({ description, width_m: widthM ?? null }),
  });
}

export function fetchModelKits(signal?: AbortSignal) {
  return apiRequest<{ kits: ModelKit[] }>('/api/director-desk/kits', { signal });
}

export function stageModelUrl(taskId: string, sceneId: string, landmarkId: string) {
  return apiUrl(`${base(taskId, sceneId)}/models/${encodeURIComponent(landmarkId)}.glb`);
}
