import type { ThreeEvent } from '@react-three/fiber';

import type { StageActor } from '../../../spatial/spatialTypes';
import { Humanoid } from './Humanoid';
import { Mannequin } from './Mannequin';
import { ACTOR_FLAG } from '../../lib/capture';
import { StandIn } from './StandIn';

interface Props {
  actor: StageActor;
  subject: boolean;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

/** Whichever of the three figures the actor is; both viewports draw the cast through this. */
export function ActorFigure(props: Props) {
  const Figure = props.actor.figure === 'mannequin' ? Mannequin : props.actor.figure === 'humanoid' ? Humanoid : StandIn;
  return <group userData={{ [ACTOR_FLAG]: true }}><Figure {...props} /></group>;
}
