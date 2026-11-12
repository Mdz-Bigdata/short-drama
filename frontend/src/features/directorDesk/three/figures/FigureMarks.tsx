import { HELPER_FLAG } from '../../lib/capture';
import { StageLabel } from '../StageLabel';
import { SELECTION_COLOR } from '../stageLook';

/** The operator's marks around a figure — selection ring and name — which a capture never shows. */
export function FigureMarks({ name, top, selected, labelled }: { name: string; top: number; selected: boolean; labelled: boolean }) {
  return (
    <>
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]} userData={{ [HELPER_FLAG]: true }}>
          <ringGeometry args={[0.34, 0.4, 40]} />
          <meshBasicMaterial color={SELECTION_COLOR} />
        </mesh>
      )}
      {labelled && <StageLabel position={[0, top + 0.28, 0]} fontSize={0.16} color="#e87084" kind="actor" selected={selected}>{name}</StageLabel>}
    </>
  );
}
