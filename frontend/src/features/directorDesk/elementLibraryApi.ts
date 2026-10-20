// The desk borrows the element library's 3D assets: a set piece can be drawn as a GLB that lives
// under the signed-in person's library rather than as a primitive. Nothing new is stored here —
// the desk creates the element and uploads the model through the library's own endpoints, and the
// plan keeps only the element's id.

import { apiRequest } from '../../api/client';
import type { ElementItem, ElementKind } from '../elements/elementTypes';

/** Only these two kinds may carry a model (`upload_element_model` refuses the rest). */
export const MODEL_KINDS: ElementKind[] = ['prop', 'scene'];
/** What the server accepts (`inspect_glb_upload`); refused here first so 25 MB do not leave the machine. */
export const MODEL_MAX_BYTES = 25 * 1024 * 1024;

export interface ElementModelChoice {
  id: string;
  name: string;
  kind: ElementKind;
  /** The authenticated GLB path; served behind the session cookie. */
  contentUrl: string;
  triangles: number;
  sizeBytes: number;
}

function choicesOf(items: ElementItem[]): ElementModelChoice[] {
  return items.flatMap(item => (item.model3d ? [{
    id: item.id,
    name: item.name,
    kind: item.kind,
    contentUrl: item.model3d.contentUrl,
    triangles: Number(item.model3d.stats?.triangles) || 0,
    sizeBytes: Number(item.model3d.sizeBytes) || 0,
  }] : []));
}

/**
 * Every element of this project that has a GLB, prop and scene alike.
 *
 * The library page lists one kind at a time; the desk wants both, so it asks twice and joins the
 * answers. `taskId` keeps the listing to the project's own and linked assets, as the page does.
 */
export async function listModelElements(taskId: string, signal?: AbortSignal): Promise<ElementModelChoice[]> {
  const scope = taskId ? `&task_id=${encodeURIComponent(taskId)}` : '';
  const pages = await Promise.all(MODEL_KINDS.map(kind => (
    apiRequest<{ items?: ElementItem[] }>(`/api/elements?kind=${kind}&page=1&page_size=50${scope}`, { signal })
      .then(data => choicesOf(data.items || []))
  )));
  return pages.flat().sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
}

export function modelPath(elementId: string): string {
  return `/api/elements/${encodeURIComponent(elementId)}/model/content`;
}

/** Why the library would refuse this file, or '' when it would take it. */
export function modelRefusal(file: File): string {
  if (!/\.glb$/i.test(file.name)) return '3D 资产仅支持自包含的 GLB 文件；.gltf 请先在建模软件里导出为 .glb';
  if (!file.size || file.size > MODEL_MAX_BYTES) return '3D 模型为空或超过 25 MB 大小限制';
  return '';
}

/**
 * Put a local GLB into the library as a new element, the way the library page does it: create the
 * element first, then upload the model to it. A failed upload leaves the element behind on purpose
 * — it is the person's, and the library page offers the retry.
 */
export async function importModelElement(taskId: string, name: string, kind: ElementKind, file: File): Promise<ElementModelChoice> {
  const refusal = modelRefusal(file);
  if (refusal) throw new Error(refusal);
  const created = await apiRequest<ElementItem>('/api/elements', {
    method: 'POST',
    body: JSON.stringify({
      kind, name: name.trim().slice(0, 120), description: '3D 导演台导入的模型',
      // Linked to the project it was imported from, so the project-scoped listing shows it again.
      metadata: taskId ? { task_id: taskId } : {},
    }),
  });
  const form = new FormData();
  form.append('file', file);
  await apiRequest<unknown>(`/api/elements/${encodeURIComponent(created.id)}/model`, { method: 'POST', body: form });
  return { id: created.id, name: created.name, kind, contentUrl: modelPath(created.id), triangles: 0, sizeBytes: file.size };
}
