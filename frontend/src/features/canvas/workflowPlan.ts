import type { WorkflowPlan, WorkflowStep } from './canvasApi';
import { kindLabel } from './canvasLabels';
import { toolById } from './canvasTools';

export function stepTypeLabel(step: WorkflowStep) {
  return step.kind === 'tool' ? toolById(step.tool)?.label() ?? step.tool : kindLabel(step.kind);
}

/** Whether there is anything to write for this step: a local tool that only has settings has no words to edit. */
export function stepTakesWords(step: WorkflowStep) {
  if (step.kind === 'media' || step.kind === 'video_compose') return false;
  return step.kind !== 'tool' || Boolean(toolById(step.tool)?.prompt);
}

/** Taking a step out also takes it out of whatever was reading from it, so the plan stays valid or says clearly why not. */
export function withoutStep(plan: WorkflowPlan, ref: string): WorkflowPlan {
  return {
    ...plan,
    steps: plan.steps.filter(step => step.ref !== ref).map(step => ({ ...step, inputs: (step.inputs ?? []).filter(input => input.source !== ref) })),
  };
}
