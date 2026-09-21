import type { PlanOperation, ScreenwritingScene } from './screenwritingApi';

export interface PlanDraft {
  duration: string;
  description: string;
}

export function draftOfScene(scene: ScreenwritingScene): PlanDraft {
  return {
    duration: String(scene.duration_seconds ?? ''),
    description: String(scene.scene_description ?? ''),
  };
}

/** Ordered edit operations for the shots whose editable fields the user changed. */
export function planOperations(scenes: ScreenwritingScene[], drafts: Record<string, PlanDraft>): PlanOperation[] {
  const operations: PlanOperation[] = [];
  scenes.forEach(scene => {
    const draft = drafts[scene.scene_id];
    if (!draft) return;
    const fields: Record<string, unknown> = {};
    const duration = Number(draft.duration);
    if (Number.isFinite(duration) && duration > 0 && duration !== scene.duration_seconds) {
      fields.duration_seconds = Math.round(duration);
    }
    if (draft.description !== String(scene.scene_description ?? '')) {
      fields.scene_description = draft.description;
    }
    if (Object.keys(fields).length > 0) operations.push({ op: 'update', id: scene.scene_id, fields });
  });
  return operations;
}
