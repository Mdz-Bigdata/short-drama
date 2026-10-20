import type { StageActor } from '../../spatial/spatialTypes';
import { POSTURE_HEIGHT } from '../three/stageLook';
import { figureTop } from './mannequinRig';
import { jointsOf, posePosture } from './poses';

/** Where the top of the head is on stage: measured off the joints for a jointed figure, by posture for the others. */
export function figureHeight(actor: StageActor): number {
  if (actor.figure === 'mannequin') {
    const joints = jointsOf(actor);
    return figureTop(joints, actor.body_type) * actor.height_m + (joints['body.offsetY'] ?? 0);
  }
  return actor.height_m * (POSTURE_HEIGHT[posePosture(actor.pose?.preset) || actor.posture] ?? 1);
}
