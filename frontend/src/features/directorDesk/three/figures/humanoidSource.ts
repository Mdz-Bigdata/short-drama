// The humanoid model every skinned figure on a stage shares: one download and one parse, held for
// as long as anyone uses it. A figure holds it while it is on stage; the monitor wall holds it while
// it draws, so its pictures wait for the model instead of catching the stand-ins.

import { Box3, type AnimationClip, type Object3D } from 'three';
// three-stdlib's loaders do not embed `new URL` decoder fallbacks (see ElementModelViewport).
import { GLTFLoader } from 'three-stdlib';

import { disposeModelResources } from '../../../elements/three/disposeModelResources';
import { HUMANOID_MODEL_URL } from '../../lib/humanoidClips';

export interface Source { scene: Object3D; clips: AnimationClip[]; height: number; floor: number }

// One download and one parse for every figure on stage; freed when the last of them leaves.
let pending: Promise<Source> | null = null;
let loaded: Source | null = null;
let users = 0;

function free(source: Source) {
  disposeModelResources(source.scene);
  pending = null;
  loaded = null;
}

export function acquire(): Promise<Source> {
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

export function release() {
  users -= 1;
  if (users <= 0 && loaded) free(loaded);
}

/** Keeps the model loaded while held; `ready` settles once it is in, or once it could not be fetched. */
export function holdHumanoidModel(): { ready: Promise<void>; release: () => void } {
  let held = true;
  const ready = acquire().then(() => undefined, () => undefined);
  return {
    ready,
    release: () => {
      if (!held) return;
      held = false;
      release();
    },
  };
}
