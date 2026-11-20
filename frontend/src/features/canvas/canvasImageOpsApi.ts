import { apiRequest } from '../../api/client';
import type { CropRect } from './canvasCropMath';

/** What cropping or splitting answers: the new canvas version and the media nodes it added, in reading order. */
export interface ImagePieces {
  version: number;
  node_ids: string[];
  source_node_id: string;
  /** Always false: a media node takes no input, so a piece notes its source instead of being wired to it. */
  connected: boolean;
}

const project = (projectId: string) => `/api/studio/projects/${encodeURIComponent(projectId)}`;
const board = (canvasId: string) => `canvas_id=${encodeURIComponent(canvasId)}`;

/** Cuts `rect` (0–1 units of the picture) out of a node's picture into a new media node beside it: one canvas version. */
export function cropNode(projectId: string, canvasId: string, nodeId: string, rect: CropRect, expectedVersion: number) {
  return apiRequest<ImagePieces & { width: number; height: number }>(`${project(projectId)}/canvas/nodes/${encodeURIComponent(nodeId)}/crop?${board(canvasId)}`, {
    method: 'POST', body: JSON.stringify({ x: rect.x, y: rect.y, w: rect.w, h: rect.h, expected_version: expectedVersion }),
  });
}

/** Cuts a node's picture into rows × columns media nodes beside it: one canvas version. */
export function splitNode(projectId: string, canvasId: string, nodeId: string, grid: { rows: number; columns: number }, expectedVersion: number) {
  return apiRequest<ImagePieces & { rows: number; columns: number }>(`${project(projectId)}/canvas/nodes/${encodeURIComponent(nodeId)}/grid-split?${board(canvasId)}`, {
    method: 'POST', body: JSON.stringify({ rows: grid.rows, columns: grid.columns, expected_version: expectedVersion }),
  });
}
