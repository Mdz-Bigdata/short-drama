import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { effectiveOutput } from './canvasGraph';
import type { CanvasDoc, CanvasNode, NodeOutput } from './canvasTypes';

/** The element library's kinds (backend `app/schema/platform.py` ElementKind), in the order the library lists them. */
export const ELEMENT_KINDS = ['actor', 'scene', 'prop', 'effect', 'product', 'extra', 'vehicle', 'stunt', 'set_dressing', 'costume', 'makeup'] as const;
export type CanvasElementKind = typeof ELEMENT_KINDS[number];

/** Kinds a new element can be saved as: the tabs the library itself offers (a costume lives on its character, special makeup is registered from the script). */
export const SAVABLE_KINDS: readonly CanvasElementKind[] = ELEMENT_KINDS.filter(kind => kind !== 'costume' && kind !== 'makeup');

export function elementKindLabel(kind: string): string {
  switch (kind) {
    case 'actor': return t('演员');
    case 'scene': return t('场景');
    case 'prop': return t('道具');
    case 'costume': return t('服装');
    case 'effect': return t('特效');
    case 'product': return t('商品');
    case 'extra': return t('群演');
    case 'vehicle': return t('车辆');
    case 'stunt': return t('特技');
    case 'set_dressing': return t('置景');
    case 'makeup': return t('化妆');
    default: return kind;
  }
}

/** One picture of a library element. `url` is the library's own authenticated address: for showing, never for storing on the canvas. */
export interface LibraryImage {
  id: string;
  slot: string;
  url: string;
}

/** A library element as the canvas's picker lists it; `images[0]` is its main picture. */
export interface LibraryElement {
  id: string;
  kind: string;
  name: string;
  images: LibraryImage[];
}

export interface LibraryPage {
  items: LibraryElement[];
  total: number;
  page: number;
  page_size: number;
  kinds: string[];
  /** How many pictures one request may take. */
  max_take: number;
}

export interface ElementPick {
  element_id: string;
  file_id: string;
}

export interface TakenElements {
  version: number;
  node_ids: string[];
  elements: Array<{ id: string; name: string; file_id: string; node_id: string }>;
}

export interface SavedElement {
  id: string;
  name: string;
  kind: string;
}

const project = (projectId: string) => `/api/studio/projects/${encodeURIComponent(projectId)}`;
const board = (canvasId: string) => `canvas_id=${encodeURIComponent(canvasId)}`;

/** The person's own library elements that have a picture, newest first. */
export function fetchLibraryElements(projectId: string, options: { kind?: string; query?: string; page?: number } = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (options.kind) params.set('kind', options.kind);
  if (options.query?.trim()) params.set('q', options.query.trim());
  if (options.page && options.page > 1) params.set('page', String(options.page));
  const query = params.toString();
  return apiRequest<LibraryPage>(`${project(projectId)}/canvas/elements${query ? `?${query}` : ''}`, { signal });
}

/** Puts the picked pictures on the canvas as media nodes holding copies, in one new canvas version. */
export function takeLibraryElements(projectId: string, canvasId: string, picks: ElementPick[], expectedVersion: number) {
  return apiRequest<TakenElements>(`${project(projectId)}/canvas/elements?${board(canvasId)}`, {
    method: 'POST', body: JSON.stringify({ picks, expected_version: expectedVersion }),
  });
}

/** Keeps a node's picture as a new element of the person's library. */
export function saveNodeAsElement(projectId: string, canvasId: string, nodeId: string, request: { name: string; kind: string }) {
  return apiRequest<SavedElement>(`${project(projectId)}/canvas/nodes/${encodeURIComponent(nodeId)}/element?${board(canvasId)}`, {
    method: 'POST', body: JSON.stringify(request),
  });
}

/** The picture a node could keep in the library: its active generation, else the file it holds; null when it shows no picture. */
export function savablePicture(node: CanvasNode | undefined, doc: CanvasDoc, outputs: Readonly<Record<string, NodeOutput>>): NodeOutput | null {
  if (!node || node.kind === 'group' || node.kind === 'note') return null;
  const output = effectiveOutput(node, doc, outputs);
  return output?.medium === 'image' && output.url ? output : null;
}
