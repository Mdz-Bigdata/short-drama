import { apiRequest } from '../../api/client';
import type { BlockingDiagramSeries } from './lib/blockingDiagram';

/** The scene's staging beats as white-model blocking diagrams. Read-only; no model is called. */
export function fetchBlockingDiagrams(taskId: string, sceneId: string, view: string, signal?: AbortSignal) {
  const query = view ? `?view=${encodeURIComponent(view)}` : '';
  return apiRequest<BlockingDiagramSeries>(
    `/api/drama/${encodeURIComponent(taskId)}/spatial/scenes/${encodeURIComponent(sceneId)}/blocking-diagrams${query}`,
    { signal },
  );
}
