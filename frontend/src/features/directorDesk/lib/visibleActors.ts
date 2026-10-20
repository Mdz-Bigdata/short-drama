import { actorsInShot, type StageActor, type StagePlan, type StageShot } from '../../spatial/spatialTypes';

/** The cast in front of a lens: everyone in the shot who is not hidden in the outliner. */
export function visibleActors(plan: StagePlan, shot: StageShot | undefined, hidden: string[]): StageActor[] {
  return actorsInShot(plan, shot).filter(actor => !hidden.includes(actor.crowd_id ? `crowd:${actor.crowd_id}` : `actor:${actor.name}`));
}
