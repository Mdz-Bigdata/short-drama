import { fetchCanvas, saveCanvas } from './canvasApi';
import type { CanvasDoc, CanvasRecord } from './canvasTypes';

export interface OverwritePlan {
  /** The version that is on the server now and that saving mine would replace. */
  theirs: number;
  mineNodes: number;
  theirNodes: number;
}

/** Read what is on the server now, so the person can see what an overwrite would replace. */
export async function planOverwrite(projectId: string, canvasId: string, mine: CanvasDoc): Promise<OverwritePlan & { latest: CanvasRecord }> {
  const latest = await fetchCanvas(projectId, canvasId);
  return { latest, theirs: latest.version, mineNodes: mine.nodes.length, theirNodes: latest.nodes.length };
}

/**
 * Save mine over the version the server holds, after the person confirmed it. The save names the version it
 * replaces, so if yet another save landed in between, this one is refused (409) instead of replacing that too;
 * the other version stays in the history either way and can be restored.
 */
export function overwriteWithMine(projectId: string, canvasId: string, theirs: number, mine: CanvasDoc, clientId?: string) {
  return saveCanvas(projectId, canvasId, theirs, mine, clientId);
}
