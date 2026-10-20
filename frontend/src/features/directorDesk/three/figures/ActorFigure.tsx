import type { ThreeEvent } from '@react-three/fiber';

import type { StageActor } from '../../../spatial/spatialTypes';
import { Humanoid } from './Humanoid';
import { Mannequin } from './Mannequin';
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
  if (props.actor.figure === 'mannequin') return <Mannequin {...props} />;
  if (props.actor.figure === 'humanoid') return <Humanoid {...props} />;
  return <StandIn {...props} />;
}
