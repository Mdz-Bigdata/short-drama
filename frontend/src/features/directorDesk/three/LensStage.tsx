// What a lens sees of the stage: the floor, the props and the cast of the shot, with none of the
// director-view helpers. The camera view and the comparison thumbnails both draw exactly this, so
// a candidate's thumbnail is a small picture of what promoting it would put on screen.

import type { StageActor, StagePlan } from '../../spatial/spatialTypes';
import { ActorFigure } from './figures/ActorFigure';
import { StageProp } from './props/StageProp';
import { FLOOR_COLOR } from './stageLook';

const NOTHING_SELECTED: ReadonlySet<string> = new Set();

interface Props {
  plan: StagePlan;
  actors: StageActor[];
  hidden: string[];
  /**
   * Selection keys (`refKey`) to mark, for a pane that is read rather than filmed: the plan and
   * elevation views. The camera view and the thumbnails leave it out, so what they draw stays
   * exactly what a capture exports.
   */
  selection?: ReadonlySet<string>;
}

export function LensStage({ plan, actors, hidden, selection = NOTHING_SELECTED }: Props) {
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]} receiveShadow>
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial color={FLOOR_COLOR} roughness={1} />
      </mesh>
      {plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`)).map(item => (
        <StageProp key={item.id} landmark={item} labelled={false} selected={selection.has(`landmark:${item.name}`)} />
      ))}
      {actors.map(actor => (
        <ActorFigure
          key={actor.id} actor={actor} labelled={false} subject={false}
          selected={selection.has(actor.crowd_id ? `crowd:${actor.crowd_id}` : `actor:${actor.name}`)}
        />
      ))}
    </>
  );
}
