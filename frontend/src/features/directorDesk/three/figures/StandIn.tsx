import { Text } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';

import type { StageActor } from '../../../spatial/spatialTypes';
import { HELPER_FLAG } from '../../lib/capture';
import { SELECTION_COLOR, actorColor, standingHeight } from '../stageLook';

interface Props {
  actor: StageActor;
  subject: boolean;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

/**
 * The white-model-safe figure: proportions and a nose, no limbs. A model copies a stand-in's
 * pose as the character's, so the default figure must not have one.
 */
export function StandIn({ actor, subject, selected, labelled, onPick }: Props) {
  const height = standingHeight(actor);
  const head = 0.11;
  const body = Math.max(0.2, height - head * 2);
  const color = actorColor(actor);
  const lying = actor.posture === 'lie';
  const glow = selected ? SELECTION_COLOR : subject ? color : '#fcebee';
  return (
    <group position={[actor.position[0], 0, actor.position[1]]} rotation={[0, (actor.yaw_deg * Math.PI) / 180, 0]} onClick={onPick}>
      <group rotation={lying ? [-Math.PI / 2, 0, 0] : [0, 0, 0]} position={lying ? [0, 0.2, 0] : [0, 0, 0]}>
        <mesh position={[0, body / 2, 0]}>
          <capsuleGeometry args={[0.2, Math.max(0.05, body - 0.4), 6, 14]} />
          <meshStandardMaterial color={color} roughness={0.55} emissive={glow} emissiveIntensity={selected ? 0.45 : subject ? 0.25 : 0} />
        </mesh>
        <mesh position={[0, body + head, 0]}>
          <sphereGeometry args={[head, 18, 14]} />
          <meshStandardMaterial color={color} roughness={0.5} />
        </mesh>
        {/* The nose: which way the character faces is the whole point of the figure. */}
        <mesh position={[0, body + head, head + 0.05]} rotation={[Math.PI / 2, 0, 0]}>
          <coneGeometry args={[0.04, 0.12, 10]} />
          <meshStandardMaterial color="#221b1e" />
        </mesh>
      </group>
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]} userData={{ [HELPER_FLAG]: true }}>
          <ringGeometry args={[0.34, 0.4, 40]} />
          <meshBasicMaterial color={SELECTION_COLOR} />
        </mesh>
      )}
      {labelled && (
        <Text
          position={[0, height + 0.28, 0]} fontSize={0.16} color="#e87084" anchorX="center" anchorY="bottom"
          outlineWidth={0.012} outlineColor="#fcedef" userData={{ [HELPER_FLAG]: true }}
        >
          {actor.name}
        </Text>
      )}
    </group>
  );
}
