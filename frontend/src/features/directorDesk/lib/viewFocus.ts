import { actorsInShot, type SpacePoint, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import type { SelectionRef } from '../deskTypes';
import { crowdMembers } from './stageMath';

// What "look at the selection" means: one ball around everything picked, for the view to stand back from.

export interface ViewFocus {
  center: SpacePoint;
  radius: number;
}

/** A lens or its look-at point is a dot; this much around it is worth seeing. */
const HANDLE_REACH_M = 1.5;
const SMALLEST_ACTOR_REACH_M = 1.2;
const SMALLEST_PIECE_REACH_M = 0.6;

function ballOf(plan: StagePlan, shot: StageShot | undefined, ref: SelectionRef): ViewFocus[] {
  switch (ref.kind) {
    case 'actor': {
      const actor = actorsInShot(plan, shot).find(item => item.name === ref.name);
      return actor ? [{ center: [actor.position[0], actor.height_m / 2, actor.position[1]], radius: Math.max(SMALLEST_ACTOR_REACH_M, actor.height_m * 0.75) }] : [];
    }
    case 'landmark': {
      const piece = plan.landmarks.find(item => item.name === ref.name);
      if (!piece) return [];
      // Size is width / depth / height; the piece stands on its mark, lifted by its elevation.
      return [{
        center: [piece.position[0], (piece.elevation_m ?? 0) + piece.size[2] / 2, piece.position[1]],
        radius: Math.max(SMALLEST_PIECE_REACH_M, Math.hypot(piece.size[0], piece.size[1], piece.size[2]) / 2),
      }];
    }
    case 'crowd':
      return crowdMembers({ actors: actorsInShot(plan, shot) }, ref.id).map(actor => ({
        center: [actor.position[0], actor.height_m / 2, actor.position[1]] as SpacePoint, radius: SMALLEST_ACTOR_REACH_M,
      }));
    default: {
      const camera = plan.cameras.find(item => item.id === ref.id);
      return camera ? [{ center: ref.kind === 'camera' ? camera.position : camera.target, radius: HANDLE_REACH_M }] : [];
    }
  }
}

/** The ball that holds everything in `refs`, or `null` when none of it is on stage in this shot. */
export function focusOf(plan: StagePlan, shot: StageShot | undefined, refs: SelectionRef[]): ViewFocus | null {
  const balls = refs.flatMap(ref => ballOf(plan, shot, ref));
  if (!balls.length) return null;
  if (balls.length === 1) return balls[0];
  const low: SpacePoint = [Infinity, Infinity, Infinity];
  const high: SpacePoint = [-Infinity, -Infinity, -Infinity];
  balls.forEach(ball => {
    for (let axis = 0; axis < 3; axis += 1) {
      low[axis] = Math.min(low[axis], ball.center[axis] - ball.radius);
      high[axis] = Math.max(high[axis], ball.center[axis] + ball.radius);
    }
  });
  // Half the longest side of the box around the balls; the view adds its own margin when it frames it.
  return {
    center: [(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, (low[2] + high[2]) / 2],
    radius: Math.max(high[0] - low[0], high[1] - low[1], high[2] - low[2]) / 2,
  };
}
