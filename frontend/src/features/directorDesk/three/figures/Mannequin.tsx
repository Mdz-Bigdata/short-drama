// The jointed white model: nested groups of spheres, cylinders and boxes, one group per bone of
// lib/mannequinRig.ts, turned by StagePose.joints.
//
// The build (a proportions table feeding nested joint groups of primitives) follows
//   lkhxxx123/jlmlh-3d-director (MIT, © 2026 YZ) src/editor/runtime/mannequin/{ProceduralMannequin,mannequinParts}.tsx
// What changed: the bone tree, axes and offsets come from the desk's own rig data (shared with
// the IK and ground maths); hands, feet and fingers are articulated; geometry is shared between
// figures; the figure is one unit tall, scaled to the actor's height and grounded by its contacts.

import { useMemo, type ReactNode } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import { BoxGeometry, CylinderGeometry, SphereGeometry } from 'three';

import type { StageActor } from '../../../spatial/spatialTypes';
import { boneLocals, figureTop, groundLift, proportionsOf, type BoneLocal, type Proportions, type Triple } from '../../lib/mannequinRig';
import { jointsOf } from '../../lib/poses';
import { SELECTION_COLOR, actorColor } from '../stageLook';
import { FigureMarks } from './FigureMarks';

interface Props {
  actor: StageActor;
  subject: boolean;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

// One of each for every figure on stage; meshes only differ by scale.
const SPHERE = new SphereGeometry(1, 16, 12);
const TUBE = new CylinderGeometry(1, 1, 1, 12);
const BOX = new BoxGeometry(1, 1, 1);

interface Paint { color: string; glow: string; intensity: number }

function Part({ geometry, position, scale, paint, rotation }: {
  geometry: typeof SPHERE | typeof TUBE | typeof BOX; position: Triple; scale: Triple; paint: Paint; rotation?: Triple;
}) {
  return (
    <mesh geometry={geometry} position={position} scale={scale} rotation={rotation}>
      <meshStandardMaterial color={paint.color} roughness={0.55} emissive={paint.glow} emissiveIntensity={paint.intensity} />
    </mesh>
  );
}

/** A limb segment hanging from the bone's origin along −Y, with the joint ball at its top. */
function limb(length: number, radius: number, joint: number, paint: Paint): ReactNode {
  return (
    <>
      <Part geometry={SPHERE} position={[0, 0, 0]} scale={[joint, joint, joint]} paint={paint} />
      <Part geometry={TUBE} position={[0, -length / 2, 0]} scale={[radius, length, radius]} paint={paint} />
    </>
  );
}

function shapesOf(bone: BoneLocal, p: Proportions, paint: Paint): ReactNode {
  const g = p.girth;
  const part = bone.id.replace(/^(left|right)/, '');
  const chestY = p.shoulderY - p.hipY - p.waist;
  switch (part) {
    case 'body':
      return <Part geometry={SPHERE} position={[0, 0, 0]} scale={[p.hipX + 0.06 * g, 0.075, 0.08 * g]} paint={paint} />;
    case 'torso':
      return (
        <>
          <Part geometry={SPHERE} position={[0, 0.045, 0]} scale={[0.085 * g, 0.085, 0.068 * g]} paint={paint} />
          <Part geometry={SPHERE} position={[0, chestY * 0.62, 0]} scale={[p.shoulderX * 0.98, chestY * 0.52, 0.082 * g]} paint={paint} />
          <Part geometry={TUBE} position={[0, chestY + 0.03, 0]} scale={[0.026 * g, 0.07, 0.026 * g]} paint={paint} />
        </>
      );
    case 'head':
      return (
        <>
          <Part geometry={SPHERE} position={[0, p.headLift, 0]} scale={[p.headRadius * 0.86, p.headRadius, p.headRadius * 0.92]} paint={paint} />
          {/* The nose: which way the character faces is the whole point of the figure. */}
          <mesh position={[0, p.headLift - 0.005, p.headRadius * 0.95]} rotation={[Math.PI / 2, 0, 0]}>
            <coneGeometry args={[0.014, 0.04, 8]} />
            <meshStandardMaterial color="#ffffff" />
          </mesh>
        </>
      );
    case 'Shoulder': return limb(p.upperArm, 0.024 * g, 0.032 * g, paint);
    case 'Elbow': return limb(p.forearm, 0.02 * g, 0.024 * g, paint);
    case 'Hand':
      return (
        <>
          <Part geometry={SPHERE} position={[0, 0, 0]} scale={[0.019 * g, 0.019 * g, 0.019 * g]} paint={paint} />
          <Part geometry={BOX} position={[0, -p.palm / 2, 0]} scale={[0.02 * g, p.palm, p.palm * 0.95]} paint={paint} />
        </>
      );
    case 'Hip': return limb(p.thigh, 0.036 * g, 0.042 * g, paint);
    case 'Knee': return limb(p.calf, 0.028 * g, 0.034 * g, paint);
    case 'Foot':
      return (
        <>
          <Part geometry={SPHERE} position={[0, 0, 0]} scale={[0.026 * g, 0.026 * g, 0.026 * g]} paint={paint} />
          <Part geometry={BOX} position={[0, -p.ankle + 0.018, (p.footFront - p.footBack) / 2]} scale={[0.05 * g, 0.036, p.footFront + p.footBack]} paint={paint} />
        </>
      );
    default: {
      // Finger phalanges: `leftHand.index` and `leftHand.index.tip`.
      const length = p.finger * (bone.id.endsWith('.tip') ? 0.45 : 0.55);
      return <Part geometry={TUBE} position={[0, -length / 2, 0]} scale={[0.0058 * g, length, 0.0058 * g]} paint={paint} />;
    }
  }
}

function Bone({ bone, children, p, paint }: { bone: BoneLocal; children: Map<string, BoneLocal[]>; p: Proportions; paint: Paint }) {
  return (
    <group name={bone.id} position={bone.offset} rotation={[bone.rotation[0], bone.rotation[1], bone.rotation[2], bone.order]}>
      {shapesOf(bone, p, paint)}
      {(children.get(bone.id) || []).map(child => <Bone key={child.id} bone={child} children={children} p={p} paint={paint} />)}
    </group>
  );
}

export function Mannequin({ actor, subject, selected, labelled, onPick }: Props) {
  const joints = useMemo(() => jointsOf(actor), [actor]);
  const rig = useMemo(() => {
    const bones = boneLocals(joints, actor.body_type);
    const children = new Map<string, BoneLocal[]>();
    bones.forEach(bone => { if (bone.parent) children.set(bone.parent, [...(children.get(bone.parent) || []), bone]); });
    return { root: bones[0], children, lift: groundLift(joints, actor.body_type), top: figureTop(joints, actor.body_type) };
  }, [actor.body_type, joints]);
  const color = actorColor(actor);
  const paint: Paint = { color, glow: selected ? SELECTION_COLOR : subject ? color : '#000000', intensity: selected ? 0.45 : subject ? 0.25 : 0 };
  const offsetY = joints['body.offsetY'] ?? 0;
  return (
    <group position={[actor.position[0], 0, actor.position[1]]} rotation={[0, (actor.yaw_deg * Math.PI) / 180, 0]} onClick={onPick}>
      <group position={[0, rig.lift * actor.height_m + offsetY, 0]} scale={actor.height_m}>
        <Bone bone={rig.root} children={rig.children} p={proportionsOf(actor.body_type)} paint={paint} />
      </group>
      <FigureMarks name={actor.name} top={rig.top * actor.height_m + offsetY} selected={selected} labelled={labelled} />
    </group>
  );
}
