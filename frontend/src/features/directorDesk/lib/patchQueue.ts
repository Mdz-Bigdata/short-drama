import type { SpatialPlanResponse, StageOperation } from '../../spatial/spatialTypes';

// One PATCH in flight at a time. Whatever is queued behind it leaves as a single request pinned
// to the revision the previous answer carried, so a burst of drags costs one round trip and can
// never race itself into a 409.

export interface QueuedEdit {
  id: number;
  operations: StageOperation[];
  solve?: boolean;
  /** Flies alone: its undo is read off the plan that comes back. */
  barrier?: boolean;
}

export interface PatchQueueOptions {
  patch: (baseRevision: number, operations: StageOperation[], options: { solve?: boolean }) => Promise<SpatialPlanResponse>;
  onApplied: (response: SpatialPlanResponse, editIds: number[]) => void;
  /** Every edit that was waiting is dropped with the one that failed: they were drawn on top of it. */
  onRejected: (error: unknown, editIds: number[]) => void;
}

export interface PatchQueue {
  reset: (revision: number) => void;
  enqueue: (edit: QueuedEdit) => void;
  busy: () => boolean;
}

const MERGE_KEY: Record<string, string> = {
  move_actor: 'name', move_landmark: 'name', transform_landmark: 'name', move_camera: 'camera_id', transform_crowd: 'crowd_id',
  // Each field of a set_timeline replaces the stored one whole, so the later write of a field is the only one that counts.
  set_timeline: 'shot_id',
};

/** Back-to-back edits of one object collapse into the later one; anything else keeps its order. */
export function coalesceOperations(operations: StageOperation[]): StageOperation[] {
  const merged: StageOperation[] = [];
  operations.forEach(op => {
    const previous = merged[merged.length - 1];
    const key = MERGE_KEY[op.op];
    if (previous && key && previous.op === op.op && previous[key] === op[key]) merged[merged.length - 1] = { ...previous, ...op };
    else merged.push(op);
  });
  return merged;
}

function takeFlight(pending: QueuedEdit[]): QueuedEdit[] {
  if (pending[0].barrier) return pending.splice(0, 1);
  const stop = pending.findIndex(edit => edit.barrier);
  return pending.splice(0, stop === -1 ? pending.length : stop);
}

export function createPatchQueue(options: PatchQueueOptions): PatchQueue {
  let revision = 0;
  let inFlight = false;
  // A reset while a request is out orphans it: its edits were already dropped from the desk.
  let epoch = 0;
  const pending: QueuedEdit[] = [];

  const pump = () => {
    if (inFlight || !pending.length) return;
    const flight = takeFlight(pending);
    const ids = flight.map(edit => edit.id);
    const started = epoch;
    inFlight = true;
    // The user is looking through the lens they drag: only re-solve when every edit allows it.
    const solve = flight.every(edit => edit.solve === false) ? false : undefined;
    options.patch(revision, coalesceOperations(flight.flatMap(edit => edit.operations)), { solve }).then(
      response => {
        inFlight = false;
        // An orphaned request still moved the server on, so its plan is the newest there is.
        revision = Math.max(revision, response.plan.revision);
        options.onApplied(response, started === epoch ? ids : []);
        pump();
      },
      error => {
        inFlight = false;
        if (started !== epoch) { pump(); return; }
        const dropped = [...ids, ...pending.splice(0).map(edit => edit.id)];
        options.onRejected(error, dropped);
      },
    );
  };

  return {
    reset(next) {
      revision = next;
      epoch += 1;
      pending.length = 0;
    },
    enqueue(edit) {
      pending.push(edit);
      pump();
    },
    busy: () => inFlight || pending.length > 0,
  };
}
