// The project's models seen and set from the canvas, and the one-click film
// (backend/app/service/canvas_models.py, backend/app/core/canvas_film.py).
import { apiRequest } from '../../api/client';

export type ModelCategory = 'text' | 'image' | 'video' | 'audio';
export const MODEL_CATEGORIES: readonly ModelCategory[] = ['text', 'image', 'video', 'audio'];

export interface ModelSlot {
  /** What the project names; empty means the model centre's first of this kind. */
  chosen: string;
  /** What would actually run. */
  effective: string;
  /** Enabled in the model centre. */
  choices: string[];
}

export interface ProjectModels {
  models: Record<ModelCategory, ModelSlot>;
  extras: { music: boolean; sfx: boolean };
  /** A pipeline stage is running: models cannot change now. */
  running: boolean;
}

export interface FilmShot {
  node_id: string;
  label: string;
  scene: string;
  shot: number;
  seconds: number;
  lines: string;
}

export interface FilmMissing {
  frames: number;
  /** Other pictures drawn on the way, such as a character's look sheet (absent from older servers). */
  pictures?: number;
  clips: number;
  voices: number;
  music: number;
}

export interface FilmPreview {
  version: number;
  shots: FilmShot[];
  voiced: number;
  music: boolean;
  music_available: boolean;
  missing: FilmMissing;
  to_run: number;
  /** The film already has a music node: kept on unless turned off. */
  had_music?: boolean;
}

export interface FilmBuild {
  version: number;
  compose: string;
  /** Node ids to run together, the compose node last. */
  run: string[];
  shots: number;
  voiced: number;
  music: boolean;
  missing: FilmMissing;
  created: string[];
}

export interface FilmRequest {
  nodeIds: string[];
  voices: boolean;
  music: boolean;
  musicPrompt: string;
}

const project = (projectId: string) => `/api/studio/projects/${encodeURIComponent(projectId)}`;
const board = (canvasId: string) => `canvas_id=${encodeURIComponent(canvasId)}`;
const body = (request: FilmRequest, extra: Record<string, unknown> = {}) => JSON.stringify({
  node_ids: request.nodeIds, voices: request.voices, music: request.music, music_prompt: request.musicPrompt, ...extra,
});

export function fetchProjectModels(projectId: string, signal?: AbortSignal) {
  return apiRequest<ProjectModels>(`${project(projectId)}/canvas/models`, { signal });
}

/** Only the categories given change; an empty string goes back to the model centre's default (not allowed for video). */
export function saveProjectModels(projectId: string, models: Partial<Record<ModelCategory, string>>) {
  return apiRequest<ProjectModels>(`${project(projectId)}/canvas/models`, { method: 'PUT', body: JSON.stringify(models) });
}

export function previewFilm(projectId: string, canvasId: string, request: FilmRequest, signal?: AbortSignal) {
  return apiRequest<FilmPreview>(`${project(projectId)}/canvas/film/preview?${board(canvasId)}`, { method: 'POST', body: body(request), signal });
}

/** Puts the film's nodes in place; `clientId` keeps this window from hearing about its own change as news. */
export function buildFilm(projectId: string, canvasId: string, request: FilmRequest, expectedVersion: number, clientId?: string) {
  return apiRequest<FilmBuild>(`${project(projectId)}/canvas/film?${board(canvasId)}`, {
    method: 'POST', body: body(request, { expected_version: expectedVersion }),
    ...(clientId ? { headers: { 'X-Canvas-Client': clientId } } : {}),
  });
}
