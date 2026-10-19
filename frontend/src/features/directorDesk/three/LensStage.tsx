// What a lens sees of the stage: the floor, the props and the cast of the shot, with none of the
// director-view helpers. The camera view and the comparison thumbnails both draw exactly this, so
// a candidate's thumbnail is a small picture of what promoting it would put on screen.

import type { StageActor, StagePlan } from '../../spatial/spatialTypes';
import { ActorFigure } from './figures/ActorFigure';
import { StageProp } from './props/StageProp';

export function LensStage({ plan, actors, hidden }: { plan: StagePlan; actors: StageActor[]; hidden: string[] }) {
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial color="#fdeff1" roughness={1} />
      </mesh>
      {plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`)).map(item => (
        <StageProp key={item.id} landmark={item} labelled={false} selected={false} />
      ))}
      {actors.map(actor => (
        <ActorFigure key={actor.id} actor={actor} labelled={false} selected={false} subject={false} />
      ))}
    </>
  );
}
