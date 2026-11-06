import { apiRequest } from '../../api/client';
import type {
  NodeKind, Bookmark, CanvasBoard, CanvasDoc, CanvasOutputs, CanvasRecord, CanvasVersion, CommitPreview, CommitResult, NodeHistory, NodeOutput, ProjectShot,
  RunAssessment, RunOptions, RunStart, TierConfirmation,
} from './canvasTypes';

const project = (projectId: string) => `/api/studio/projects/${encodeURIComponent(projectId)}`;
const board = (canvasId: string) => `canvas_id=${encodeURIComponent(canvasId)}`;
const json = (body: unknown) => JSON.stringify(body);

export function openTaskCanvas(taskId: string, signal?: AbortSignal) {
  return apiRequest<{ project_id: string; task_id: string; canvases: CanvasBoard[] }>(`/api/studio/tasks/${encodeURIComponent(taskId)}/canvas-project`, { method: 'POST', signal });
}

export function createBoard(projectId: string, title: string) {
  return apiRequest<CanvasBoard>(`${project(projectId)}/canvases`, { method: 'POST', body: json({ title }) });
}

export function patchBoard(projectId: string, canvasId: string, patch: { title?: string; bookmarks?: Bookmark[] }) {
  return apiRequest<CanvasBoard>(`${project(projectId)}/canvases/${encodeURIComponent(canvasId)}`, { method: 'PATCH', body: json(patch) });
}

export function deleteBoard(projectId: string, canvasId: string) {
  return apiRequest<{ id: string }>(`${project(projectId)}/canvases/${encodeURIComponent(canvasId)}`, { method: 'DELETE' });
}

export function fetchCanvas(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<CanvasRecord>(`${project(projectId)}/canvas?${board(canvasId)}`, { signal });
}

export function saveCanvas(projectId: string, canvasId: string, expectedVersion: number, doc: CanvasDoc) {
  return apiRequest<CanvasRecord>(`${project(projectId)}/canvas?${board(canvasId)}`, {
    method: 'PUT', body: json({ expected_version: expectedVersion, nodes: doc.nodes, edges: doc.edges }),
  });
}

export function listVersions(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<{ versions: CanvasVersion[] }>(`${project(projectId)}/canvas/versions?${board(canvasId)}`, { signal }).then(data => data.versions);
}

export function restoreVersion(projectId: string, canvasId: string, version: number, expectedVersion: number) {
  return apiRequest<CanvasRecord>(`${project(projectId)}/canvas/versions/${version}/restore?${board(canvasId)}`, {
    method: 'POST', body: json({ expected_version: expectedVersion }),
  });
}

export function uploadMedia(projectId: string, file: File) {
  const form = new FormData();
  form.append('file', file, file.name);
  return apiRequest<NodeOutput>(`${project(projectId)}/canvas/uploads`, { method: 'POST', body: form });
}

export function fetchRunOptions(projectId: string, signal?: AbortSignal) {
  return apiRequest<RunOptions>(`${project(projectId)}/canvas/run-options`, { signal });
}

export function fetchShots(projectId: string, signal?: AbortSignal) {
  return apiRequest<{ shots: ProjectShot[] }>(`${project(projectId)}/canvas/shots`, { signal }).then(data => data.shots);
}

export function assessRun(projectId: string, canvasId: string, nodeIds: string[], confirmed: TierConfirmation[] = []) {
  return apiRequest<RunAssessment>(`${project(projectId)}/canvas/runs/assess?${board(canvasId)}`, {
    method: 'POST', body: json({ node_ids: nodeIds, confirmed_request_durations: confirmed.map(tierPair) }),
  });
}

function tierPair(item: TierConfirmation) {
  return { scripted_seconds: item.scripted_seconds, requested_seconds: item.requested_seconds };
}

export function startRun(
  projectId: string, canvasId: string,
  request: { nodeIds: string[]; expectedVersion: number; operationId: string; confirm: boolean; confirmed: TierConfirmation[] },
) {
  return apiRequest<RunStart>(`${project(projectId)}/canvas/runs?${board(canvasId)}`, {
    method: 'POST',
    body: json({
      node_ids: request.nodeIds, expected_version: request.expectedVersion, operation_id: request.operationId, confirm: request.confirm,
      confirmed_request_durations: request.confirmed.map(tierPair),
    }),
  });
}

export function cancelRun(projectId: string, batchId: string, key: string | null) {
  return apiRequest<unknown>(`${project(projectId)}/canvas/runs/${encodeURIComponent(batchId)}/cancel`, { method: 'POST', body: json({ key }) });
}

export function fetchOutputs(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<CanvasOutputs>(`${project(projectId)}/canvas/outputs?${board(canvasId)}`, { signal });
}

const history = (projectId: string, nodeId: string) => `${project(projectId)}/canvas/nodes/${encodeURIComponent(nodeId)}/history`;

export function fetchNodeHistory(projectId: string, canvasId: string, nodeId: string, signal?: AbortSignal) {
  return apiRequest<NodeHistory>(`${history(projectId, nodeId)}?${board(canvasId)}`, { signal });
}

export function restoreRun(projectId: string, canvasId: string, nodeId: string, runId: string) {
  return apiRequest<NodeHistory>(`${history(projectId, nodeId)}/${encodeURIComponent(runId)}/restore?${board(canvasId)}`, { method: 'POST' });
}

export function deleteRun(projectId: string, canvasId: string, nodeId: string, runId: string) {
  return apiRequest<NodeHistory>(`${history(projectId, nodeId)}/${encodeURIComponent(runId)}?${board(canvasId)}`, { method: 'DELETE' });
}

export function previewCommit(projectId: string, canvasId: string, nodeIds: string[]) {
  return apiRequest<CommitPreview>(`${project(projectId)}/canvas/commit/preview?${board(canvasId)}`, { method: 'POST', body: json({ node_ids: nodeIds }) });
}

export function commitNodes(projectId: string, canvasId: string, nodeIds: string[], expectedVersion: number) {
  return apiRequest<CommitResult>(`${project(projectId)}/canvas/commit?${board(canvasId)}`, {
    method: 'POST', body: json({ node_ids: nodeIds, expected_version: expectedVersion }),
  });
}

export interface WorkflowStepInput { source: string; role?: string }

export interface WorkflowStep {
  ref: string;
  kind: NodeKind;
  label?: string;
  prompt?: string;
  text?: string;
  tool?: string;
  medium?: string;
  recipe?: string;
  recipe_inputs?: Record<string, unknown>;
  params?: Record<string, unknown>;
  inputs?: WorkflowStepInput[];
}

export interface WorkflowPlan {
  title: string;
  summary?: string;
  steps: WorkflowStep[];
}

export interface WorkflowSummary {
  id: string;
  title: string;
  applied: boolean;
  steps: number;
  brief: string;
  updated_at: string;
}

export interface WorkflowStatus {
  id: string;
  canvas_id: string;
  brief: string;
  applied: boolean;
  plan: WorkflowPlan;
  problems: Array<{ ref: string; code: string; message: string; blocking: boolean }>;
  /** draft / ready / needs_input / running / failed / done */
  state: string;
  steps: Array<{ ref: string; state: string; node_id: string; error: string }>;
  /** Nodes with no result yet: what a run or a retry should start. */
  runnable: string[];
  can_apply: boolean;
  created_at: string;
  updated_at: string;
}

const workflows = (projectId: string) => `${project(projectId)}/canvas/workflows`;

export function listWorkflows(projectId: string, canvasId: string, signal?: AbortSignal) {
  return apiRequest<{ workflows: WorkflowSummary[] }>(`${workflows(projectId)}?${board(canvasId)}`, { signal });
}

export function planWorkflow(projectId: string, canvasId: string, brief: string) {
  return apiRequest<WorkflowStatus>(`${workflows(projectId)}/plan?${board(canvasId)}`, { method: 'POST', body: json({ brief }) });
}

export function fetchWorkflow(projectId: string, workflowId: string, signal?: AbortSignal) {
  return apiRequest<WorkflowStatus>(`${workflows(projectId)}/${encodeURIComponent(workflowId)}`, { signal });
}

export function updateWorkflow(projectId: string, workflowId: string, plan: WorkflowPlan) {
  return apiRequest<WorkflowStatus>(`${workflows(projectId)}/${encodeURIComponent(workflowId)}`, { method: 'PUT', body: json({ plan }) });
}

export function applyWorkflow(projectId: string, workflowId: string, expectedVersion: number) {
  return apiRequest<WorkflowStatus>(`${workflows(projectId)}/${encodeURIComponent(workflowId)}/apply`, { method: 'POST', body: json({ expected_version: expectedVersion }) });
}

export function deleteWorkflow(projectId: string, workflowId: string) {
  return apiRequest<{ id: string }>(`${workflows(projectId)}/${encodeURIComponent(workflowId)}`, { method: 'DELETE' });
}
