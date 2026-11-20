import { apiRequest } from '../../api/client';
import type { CanvasRecord } from './canvasTypes';

const drama = (taskId: string) => `/api/drama/${encodeURIComponent(taskId)}/canvas-beef`;

export type OptimizeMode = 'expand' | 'refine' | 'style' | 'fit_model' | 'references' | 'structure' | 'fight' | 'performance' | 'camera';

/** Modes that rewrite a clip's prompt around a timed script; a picture node cannot use them. */
export const CLIP_ONLY_MODES: readonly OptimizeMode[] = ['structure', 'fight'];

export interface OptimizerOptions {
  modes: { id: OptimizeMode; label: string }[];
  text_models: string[];
  default_text_model: string;
}

export interface OptimizeRequest {
  prompt: string;
  medium: 'image' | 'video';
  mode: OptimizeMode;
  targetModel?: string;
  references?: string[];
  imageReferences?: number;
  note?: string;
  textModel?: string;
  /** The clip node's length in seconds; only the fixed-layout modes read it. */
  duration?: number;
}

/** The rule check of an eight-part result: sections present, timed segments joined and adding up. */
export interface StructureCheck {
  ok: boolean;
  problems: string[];
  summary: string;
  total_s: number;
  segments: number;
}

export interface OptimizeResult {
  prompt: string;
  avoid: string[];
  changes: string[];
  assumptions: string[];
  alternatives: string[];
  mode: OptimizeMode;
  text_model: string;
  /** Only with the fixed-layout modes (structure, fight, performance): the rule check of the result. */
  structure_check?: StructureCheck;
  /** Only with the camera mode: what the rule check found in the original prompt. */
  diagnosis?: Omit<CameraDiagnosis, 'reference'>;
}

export interface CameraFinding {
  check: number;
  code: string;
  title: string;
  detail: string;
  evidence: string[];
}

export interface CameraEmotion {
  id: string;
  label: string;
  why: string;
  avoid: string;
  recipe: { dimension: string; take: string }[];
}

export interface CameraDiagnosis {
  findings: CameraFinding[];
  main: string;
  emotion: string;
  moves: string[];
  reference: {
    principle: string;
    emotions: CameraEmotion[];
    turns: { name: string; how: string }[];
    beats: { name: string; shots: string }[];
    beat_rule: string;
  };
}

export interface ReferenceLimits {
  images: number;
  videos: number;
  audios: number;
}

/** An older version's nodes and edges, read only: nothing is restored by reading it. */
export function fetchCanvasVersion(projectId: string, canvasId: string, version: number, signal?: AbortSignal) {
  return apiRequest<CanvasRecord>(
    `/api/studio/projects/${encodeURIComponent(projectId)}/canvas/versions/${version}?canvas_id=${encodeURIComponent(canvasId)}`,
    { signal },
  );
}

export const fetchReferenceLimits = (taskId: string, signal?: AbortSignal) =>
  apiRequest<ReferenceLimits>(`${drama(taskId)}/reference-limits`, { signal });

export const fetchOptimizerOptions = (taskId: string, signal?: AbortSignal) =>
  apiRequest<OptimizerOptions>(`${drama(taskId)}/prompt-optimize`, { signal });

export function optimizePrompt(taskId: string, request: OptimizeRequest, signal?: AbortSignal) {
  return apiRequest<OptimizeResult>(`${drama(taskId)}/prompt-optimize`, {
    method: 'POST', signal,
    body: JSON.stringify({
      prompt: request.prompt, medium: request.medium, mode: request.mode, target_model: request.targetModel ?? '',
      references: request.references ?? [], image_references: request.imageReferences ?? 0, note: request.note ?? '',
      text_model: request.textModel ?? '', duration: request.duration ?? 0,
    }),
  });
}

/** Why a prompt comes out flat, by rule: free, no model call, nothing changed. */
export function diagnoseCamera(taskId: string, prompt: string, medium: 'image' | 'video', signal?: AbortSignal) {
  return apiRequest<CameraDiagnosis>(`${drama(taskId)}/camera-diagnosis`, {
    method: 'POST', signal, body: JSON.stringify({ prompt, medium }),
  });
}
