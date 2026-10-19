// A set piece drawn as the GLB bound to it in the element library, in place of its primitive.
//
// The model is fetched with the session cookie (the library serves it privately), parsed once per
// element however many pieces point at it, and normalised into the landmark's own size box so a
// model authored in any scale still reads as a piece of this set.

import { useEffect, useMemo, useState } from 'react';
import { Text } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { Box3, Vector3, type Object3D } from 'three';
// three-stdlib's loaders do not embed `new URL` decoder fallbacks (see ElementModelViewport).
import { GLTFLoader } from 'three-stdlib';

import { API_BASE } from '../../../../api/client';
import { disposeModelResources } from '../../../elements/three/disposeModelResources';
import type { StageLandmark } from '../../../spatial/spatialTypes';
import { modelPath } from '../../elementLibraryApi';
import { HELPER_FLAG } from '../../lib/capture';
import { SELECTION_COLOR } from '../stageLook';
import { PrimitiveProp } from './PrimitiveProp';

interface Props {
  landmark: StageLandmark;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

/** A parsed GLB plus the measurements the stage needs to stand it on the floor at the right size. */
interface Source {
  scene: Object3D;
  /** Width, height, depth of the model's own bounding box, in its own units. */
  size: [number, number, number];
  /** Centre of that box; subtracted so the piece sits over its mark. */
  center: [number, number, number];
}

interface Entry {
  pending: Promise<Source>;
  source: Source | null;
  users: number;
}

// One download and one parse per element, shared by every piece bound to it.
const cache = new Map<string, Entry>();

function acquire(elementId: string): Promise<Source> {
  const held = cache.get(elementId);
  if (held) {
    held.users += 1;
    return held.pending;
  }
  const entry: Entry = { users: 1, source: null, pending: Promise.resolve() as unknown as Promise<Source> };
  entry.pending = fetch(`${API_BASE}${modelPath(elementId)}`, { credentials: 'include', headers: { Accept: 'model/gltf-binary' } })
    .then(async response => {
      if (!response.ok) throw new Error(`模型读取失败 (${response.status})`);
      const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), '');
      const box = new Box3().setFromObject(gltf.scene);
      const span = box.getSize(new Vector3());
      const middle = box.getCenter(new Vector3());
      const source: Source = {
        scene: gltf.scene,
        size: [Math.max(span.x, 1e-4), Math.max(span.y, 1e-4), Math.max(span.z, 1e-4)],
        center: [middle.x, box.min.y, middle.z],
      };
      // Everyone who asked for it may have left while it was downloading.
      if (entry.users > 0) entry.source = source;
      else disposeModelResources(source.scene);
      return source;
    })
    .catch(error => {
      // A failed fetch is not remembered: the next piece tries again.
      cache.delete(elementId);
      throw error;
    });
  cache.set(elementId, entry);
  return entry.pending;
}

function release(elementId: string) {
  const held = cache.get(elementId);
  if (!held) return;
  held.users -= 1;
  if (held.users > 0) return;
  cache.delete(elementId);
  if (held.source) disposeModelResources(held.source.scene);
}

export function ElementModelProp({ landmark, selected, labelled, onPick }: Props) {
  const elementId = landmark.element_id || '';
  // Keyed by the element it holds, so re-binding a piece shows its box again rather than the old model.
  const [loaded, setLoaded] = useState<{ id: string; source: Source | null; failed: boolean }>({ id: elementId, source: null, failed: false });
  if (loaded.id !== elementId) setLoaded({ id: elementId, source: null, failed: false });
  const source = loaded.id === elementId ? loaded.source : null;
  const failed = loaded.id === elementId && loaded.failed;

  useEffect(() => {
    if (!elementId) return undefined;
    let alive = true;
    acquire(elementId)
      .then(result => { if (alive) setLoaded({ id: elementId, source: result, failed: false }); })
      .catch(() => { if (alive) setLoaded({ id: elementId, source: null, failed: true }); });
    return () => { alive = false; release(elementId); };
  }, [elementId]);

  const [width, depth, height] = landmark.size;
  // Uniform, so the model keeps its proportions: the piece fills its box along the tightest side.
  const scale = useMemo(() => (
    source ? Math.min(width / source.size[0], height / source.size[1], depth / source.size[2]) : 1
  ), [depth, height, source, width]);

  if (!source) {
    return (
      <group>
        <PrimitiveProp landmark={landmark} selected={selected} labelled={labelled} onPick={onPick} />
        {failed && (
          <Text
            position={[landmark.position[0], height + 0.36, landmark.position[1]]} fontSize={0.12} color="#e60000"
            anchorX="center" anchorY="bottom" userData={{ [HELPER_FLAG]: true }}
          >
            模型加载失败
          </Text>
        )}
      </group>
    );
  }

  return (
    <group position={[landmark.position[0], 0, landmark.position[1]]} rotation={[0, ((landmark.yaw_deg ?? 0) * Math.PI) / 180, 0]} onClick={onPick}>
      {/* The model's own centre goes over the mark and its lowest point onto the floor. */}
      <primitive object={source.scene} scale={scale} position={[-source.center[0] * scale, -source.center[1] * scale, -source.center[2] * scale]} />
      {/* Picking and the selection glow go through this box: ray-testing a whole GLB per move is wasted work. */}
      <mesh position={[0, (source.size[1] * scale) / 2, 0]} scale={[source.size[0] * scale, source.size[1] * scale, source.size[2] * scale]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial
          transparent opacity={selected ? 0.12 : 0} depthWrite={false}
          color={SELECTION_COLOR} emissive={selected ? SELECTION_COLOR : '#fcebee'} emissiveIntensity={selected ? 0.4 : 0}
        />
      </mesh>
      {labelled && (
        <Text position={[0, source.size[1] * scale + 0.18, 0]} fontSize={0.13} color={selected ? SELECTION_COLOR : '#46373e'} anchorX="center" anchorY="bottom" userData={{ [HELPER_FLAG]: true }}>
          {landmark.name}
        </Text>
      )}
    </group>
  );
}
