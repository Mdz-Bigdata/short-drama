import type { WorkflowSnapshot } from '../../types';
import './WorkflowGuide.css';

interface WorkflowActionsProps {
  workflow?: WorkflowSnapshot;
  busy: boolean;
  onAction: (message: string) => void;
}

export function WorkflowActions({ workflow, busy, onAction }: WorkflowActionsProps) {
  if (!workflow) return null;
  return (
    <div className="workflow-guide__actions" aria-label="当前流程可用操作">
      {workflow.actions.map(action => (
        <button key={`${action.kind}:${action.message}`} type="button" className="capsule-btn"
          disabled={busy} onClick={() => onAction(action.message)}>
          {action.label}
        </button>
      ))}
    </div>
  );
}
