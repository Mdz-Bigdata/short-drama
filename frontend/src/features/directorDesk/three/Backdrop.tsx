// The scene's backdrop, drawn in the lens view only.
//
// It is a reference underlay for framing — a colour wash, a photograph of the real location, or an
// equirectangular panorama — so it is never part of the stage: the director view does not draw it,
// nothing measures against it, and a still or a blockout clip leaves it out unless the operator
// asks for it (the same `HELPER_FLAG` the grid and the camera rigs use).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { BackSide, SRGBColorSpace, Texture, Vector3, type Mesh, type PerspectiveCamera } from 'three';

import type { StageBackdrop } from '../../spatial/spatialTypes';
import { HELPER_FLAG } from '../lib/capture';
import { BACKDROP_FLAG } from '../lib/depthPass';

// Well beyond any stage but far inside the lens's 500 m far plane: the backdrop is depth-tested like
// everything else, so it has to be genuinely behind the set rather than merely drawn first.
const PLANE_DISTANCE_M = 120;
// A little wider than the frame, so a lens re-aspected for a delivery render finds no gap at the edge.
const PLANE_OVERSCAN = 1.15;
const PANORAMA_RADIUS_M = 200;

/**
 * The backdrop picture as a texture. It is fetched with the session cookie and handed to WebGL
 * through a blob URL, which keeps the lens canvas same-origin: a cross-origin image would make
 * `toBlob` refuse to give back the still that was just rendered. It goes through an `<img>` rather
 * than an `ImageBitmap` because the renderer ignores `flipY` on a bitmap, and a backdrop that
 * arrives upside down is not a backdrop.
 */
function useBackdropTexture(url: string): Texture | null {
  const invalidate = useThree(state => state.invalidate);
  // Keyed by the URL it holds, so a new picture shows nothing rather than the one before it.
  const [loaded, setLoaded] = useState<{ url: string; texture: Texture | null }>({ url, texture: null });
  if (loaded.url !== url) setLoaded({ url, texture: null });

  useEffect(() => {
    if (!url) return undefined;
    let alive = true;
    let made: Texture | null = null;
    let objectUrl = '';
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(url, { credentials: 'include', signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        objectUrl = URL.createObjectURL(await response.blob());
        const image = new Image();
        image.src = objectUrl;
        await image.decode();
        if (!alive) return;
        made = new Texture(image);
        made.colorSpace = SRGBColorSpace;
        made.needsUpdate = true;
        setLoaded({ url, texture: made });
        invalidate();
      } catch {
        // A picture that cannot be fetched simply does not show; the stage is still the stage.
      }
    })();
    return () => {
      alive = false;
      controller.abort();
      made?.dispose();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [invalidate, url]);

  return loaded.url === url ? loaded.texture : null;
}

export function Backdrop({ backdrop, inCapture }: {
  backdrop: StageBackdrop;
  /** False keeps it out of a delivered still or clip, the way the grid and the rigs are kept out. */
  inCapture: boolean;
}) {
  const camera = useThree(state => state.camera) as PerspectiveCamera;
  const mesh = useRef<Mesh>(null);
  const forward = useRef(new Vector3());
  const picture = useBackdropTexture(backdrop.kind === 'image' || backdrop.kind === 'panorama' ? backdrop.url : '');
  const flat = backdrop.kind === 'image' || backdrop.kind === 'color';

  // The plane fills the frustum at its own distance, so it reads as the wall behind the set.
  const plane = useMemo<[number, number]>(() => {
    const height = 2 * PLANE_DISTANCE_M * Math.tan(((camera.fov || 40) * Math.PI) / 360) * PLANE_OVERSCAN;
    return [height * (camera.aspect || 1), height];
  }, [camera.aspect, camera.fov]);

  // The lens is aimed in an effect of its own, and a still is rendered outside the frame loop, so
  // the backdrop is put where the camera is in both: after every render and on every drawn frame.
  const follow = useCallback(() => {
    const object = mesh.current;
    if (!object) return;
    if (flat) {
      object.quaternion.copy(camera.quaternion);
      object.position.copy(camera.position).add(forward.current.set(0, 0, -PLANE_DISTANCE_M).applyQuaternion(camera.quaternion));
    } else {
      object.position.copy(camera.position);
    }
  }, [camera, flat]);
  useEffect(follow);
  useFrame(follow);

  if (backdrop.kind === 'none') return null;
  if (backdrop.kind !== 'color' && !picture) return null;

  // Always a backdrop (a depth picture never shows one); a helper only when it is kept out of captures.
  const flag = inCapture ? { [BACKDROP_FLAG]: true } : { [BACKDROP_FLAG]: true, [HELPER_FLAG]: true };
  // Depth-tested and drawn first, but writing no depth: the set stands in front of it, and a
  // half-transparent underlay still shows the empty stage through itself.
  // Keyed by shape: a panorama and a flat underlay are different objects, and swapping one mesh's
  // geometry and material props under the renderer leaves it drawing the old state.
  return flat ? (
    <mesh key="flat" ref={mesh} userData={flag} renderOrder={-1} frustumCulled={false}>
      <planeGeometry args={plane} />
      <meshBasicMaterial
        map={backdrop.kind === 'image' ? picture : null} color={backdrop.kind === 'color' ? (backdrop.color || '#fdf0f2') : '#221b1e'}
        transparent opacity={backdrop.opacity} depthWrite={false} toneMapped={false}
      />
    </mesh>
  ) : (
    <mesh key="panorama" ref={mesh} rotation={[0, (backdrop.yaw_deg * Math.PI) / 180, 0]} userData={flag} renderOrder={-1} frustumCulled={false}>
      <sphereGeometry args={[PANORAMA_RADIUS_M, 48, 32]} />
      <meshBasicMaterial map={picture} side={BackSide} transparent opacity={backdrop.opacity} depthWrite={false} toneMapped={false} />
    </mesh>
  );
}
