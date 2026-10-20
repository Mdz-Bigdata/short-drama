// The skinned figure: the CC0 Quaternius humanoid (see public/models/director-desk/NOTICE.txt)
// showing one frame of one of its ten clips. The clip is scrubbed by `clip_phase`, never played
// against the wall clock: a still and a frame of an exported blockout must be reproducible.

import { useEffect, useMemo, useState } from 'react';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import { AnimationMixer, Box3, LoopOnce, LoopRepeat, type AnimationClip, type Mesh, type MeshStandardMaterial, type Object3D } from 'three';
// three-stdlib's loaders do not embed `new URL` decoder fallbacks (see ElementModelViewport).
import { GLTFLoader, SkeletonUtils } from 'three-stdlib';

import type { StageActor } from '../../../spatial/spatialTypes';
import { disposeModelResources } from '../../../elements/three/disposeModelResources';
import { HELPER_FLAG } from '../../lib/capture';
import { HUMANOID_MODEL_URL, clipForPosture, humanoidClip } from '../../lib/humanoidClips';
import { SELECTION_COLOR, actorColor, standingHeight } from '../stageLook';
import { FigureMarks } from './FigureMarks';
import { StandIn } from './StandIn';

interface Props {
  actor: StageActor;
  subject: boolean;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

interface Source { scene: Object3D; clips: AnimationClip[]; height: number; floor: number }

// One download and one parse for every figure on stage; freed when the last of them leaves.
let pending: Promise<Source> | null = null;
let loaded: Source | null = null;
let users = 0;

function free(source: Source) {
  disposeModelResources(source.scene);
  pending = null;
  loaded = null;
}

function acquire(): Promise<Source> {
  users += 1;
  pending ??= new GLTFLoader().loadAsync(HUMANOID_MODEL_URL).then(gltf => {
    const box = new Box3().setFromObject(gltf.scene);
    const source = { scene: gltf.scene, clips: gltf.animations, height: Math.max(0.1, box.max.y - box.min.y), floor: box.min.y };
    // Everyone who asked may have left while it was downloading.
    if (users > 0) loaded = source;
    else free(source);
    return source;
  }).catch(error => {
    // A failed download is not remembered: the next figure tries again.
    pending = null;
    throw error;
  });
  return pending;
}

function release() {
  users -= 1;
  if (users <= 0 && loaded) free(loaded);
}

const WHITE = '#31262b';

export function Humanoid({ actor, subject, selected, labelled, onPick }: Props) {
  const invalidate = useThree(state => state.invalidate);
  const [source, setSource] = useState<Source | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    acquire().then(result => { if (alive) setSource(result); }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; release(); };
  }, []);

  // The material is R3F's to make, colour and dispose; the clone only borrows it.
  const [material, setMaterial] = useState<MeshStandardMaterial | null>(null);

  const figure = useMemo(() => {
    if (!source) return null;
    // A plain clone would share the skeleton: every figure would strike the same pose.
    const scene = SkeletonUtils.clone(source.scene);
    scene.traverse(object => {
      const mesh = object as Mesh;
      if (!mesh.isMesh) return;
      // The bind-pose bounds say nothing about where a posed limb is.
      mesh.frustumCulled = false;
      // Picking goes through the proxy below; ray-testing skinned triangles on every move is wasted work.
      mesh.raycast = () => {};
    });
    return { scene, mixer: new AnimationMixer(scene) };
  }, [source]);

  useEffect(() => () => {
    figure?.mixer.stopAllAction();
    figure?.mixer.uncacheRoot(figure.scene);
  }, [figure]);

  useEffect(() => {
    if (!figure || !material) return;
    figure.scene.traverse(object => { if ((object as Mesh).isMesh) (object as Mesh).material = material; });
    invalidate();
  }, [figure, invalidate, material]);

  const clipId = actor.pose?.clip || clipForPosture(actor.posture);
  const phase = actor.pose?.clip_phase ?? 0;
  useEffect(() => {
    if (!figure || !source) return;
    const spec = humanoidClip(clipId);
    const clip = source.clips[spec.index];
    if (!clip) return;
    figure.mixer.stopAllAction();
    const action = figure.mixer.clipAction(clip);
    action.setLoop(spec.loop ? LoopRepeat : LoopOnce, spec.loop ? Infinity : 1);
    action.clampWhenFinished = true;
    action.play();
    // Just short of the end: at exactly `duration` a looping clip wraps to its first frame.
    figure.mixer.setTime(Math.min(Math.max(phase, 0), 0.9999) * clip.duration);
    invalidate();
  }, [clipId, figure, invalidate, phase, source]);

  // Until the model is in (or when it cannot be fetched) the stage still shows who stands where.
  if (!figure || !source || failed) return <StandIn actor={actor} subject={subject} selected={selected} labelled={labelled} onPick={onPick} />;

  const scale = actor.height_m / source.height;
  const top = standingHeight(actor);
  return (
    <group position={[actor.position[0], 0, actor.position[1]]} rotation={[0, (actor.yaw_deg * Math.PI) / 180, 0]} onClick={onPick}>
      <meshStandardMaterial
        ref={setMaterial} color={actor.color ? actorColor(actor) : WHITE} roughness={0.6}
        emissive={selected ? SELECTION_COLOR : subject ? actorColor(actor) : '#fcebee'} emissiveIntensity={selected ? 0.35 : subject ? 0.18 : 0}
      />
      <primitive object={figure.scene} position={[0, -source.floor * scale, 0]} scale={scale} />
      <mesh position={[0, top / 2, 0]} userData={{ [HELPER_FLAG]: true }}>
        <cylinderGeometry args={[0.24, 0.24, top, 10]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      <FigureMarks name={actor.name} top={top} selected={selected} labelled={labelled} />
    </group>
  );
}
