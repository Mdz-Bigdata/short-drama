/**
 * 剪辑合成师 is one tab for two pipeline stages: 6 makes the sound, 7 renders the film.
 * The stage numbers stay as the backend counts them; the workbench treats 6 and 7 as one page.
 */

export const EDITOR_STAGES = [6, 7] as const;

export const isEditorStage = (stage: number | null | undefined): boolean => stage === 6 || stage === 7;

/** Whether two stages open the same workbench tab. */
export const sameStageTab = (a: number | null | undefined, b: number | null | undefined): boolean =>
  a === b || (isEditorStage(a) && isEditorStage(b));

/** The tab before this one: from the editor back to stage 5, from stage 8 back to the editor. */
export const previousStageTab = (stage: number): number => (isEditorStage(stage) ? 5 : stage - 1);

/** The tab after this one: from the editor on to stage 8. */
export const nextStageTab = (stage: number): number => (isEditorStage(stage) ? 8 : stage + 1);

/** The QC log a tab shows: the editor shows the film's (stage 7) once there is one, else the sound's. */
export function stageLog(logs: Record<string, unknown> | null | undefined, stage: number): string {
  const read = (key: number) => (logs?.[String(key)] ? String(logs[String(key)]) : '');
  return isEditorStage(stage) ? read(7) || read(6) : read(stage);
}

/** Steps a person sees: 1–5 as they are, 6 and 7 (剪辑合成师) are step 6, 8 (宣发) is step 7. Mirrors workflow_guide.display_step. */
export const DISPLAY_STEPS = 7;
export const displayStep = (stage: number): number => (stage <= 6 ? stage : stage - 1);
