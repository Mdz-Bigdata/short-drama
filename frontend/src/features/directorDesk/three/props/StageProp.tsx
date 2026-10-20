import type { ThreeEvent } from '@react-three/fiber';

import type { StageLandmark } from '../../../spatial/spatialTypes';
import { ElementModelProp } from './ElementModelProp';
import { PrimitiveProp } from './PrimitiveProp';

/** One set piece, drawn as its bound element-library model when it has one and as its shape otherwise. */
export function StageProp(props: { landmark: StageLandmark; selected: boolean; labelled: boolean; onPick?: (event: ThreeEvent<MouseEvent>) => void }) {
  return props.landmark.element_id ? <ElementModelProp {...props} /> : <PrimitiveProp {...props} />;
}
