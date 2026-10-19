// The lens scene as a depth picture: near bright, far dark, nothing else.
//
// A depth still or clip is a motion-and-layering reference for the video model, so it must say
// where things are and nothing about what they look like. The whole scene is drawn with one
// override material that writes only its distance from the lens; lights, colours, textures, the
// backdrop and the sky cannot leak in because the material never reads any of them.

import { DoubleSide, ShaderMaterial, Vector3, type Object3D } from 'three';

import { actorsInShot, type StageCamera, type StagePlan, type StageShot } from '../../spatial/spatialTypes';

/** Metres from the lens that map to white (`near`) and black (`far`). */
export interface DepthRange {
  near: number;
  far: number;
}

export interface DepthOptions {
  range: DepthRange;
  /** False (the default) is near bright; true is the far-bright convention some models were trained on. */
  invert?: boolean;
}

/** When nothing in the shot says how deep it is: a conversational stage, the lens a few metres off. */
export const DEPTH_FALLBACK_RANGE: DepthRange = { near: 1, far: 20 };
/** Breathing room on either side of the nearest and farthest subject, so neither clips to pure white or black. */
export const DEPTH_PADDING_M = 1;
/** A single subject still gets a gradient across its own depth rather than one flat grey. */
export const DEPTH_MIN_SPAN_M = 2;
/** Every backdrop mesh carries this: it may be asked into an ordinary capture, but never into a depth one. */
export const BACKDROP_FLAG = 'deskBackdrop';

/** Distance along the lens axis (view-space depth, what the shader sees), or `null` behind the lens. */
function depthAlong(point: Vector3, origin: Vector3, forward: Vector3): number | null {
  const depth = point.sub(origin).dot(forward);
  return depth > 0 ? depth : null;
}

/**
 * The metre range a depth picture of this shot should span: from the nearest to the farthest
 * subject in front of the lens (actors by their feet and heads, landmarks by their footprint and
 * top), padded, never narrower than `DEPTH_MIN_SPAN_M`. Without a lens, or with everything behind
 * it, the fallback range. Pure: a clip computes it once so a standing figure keeps one shade
 * while the lens moves.
 */
export function depthRange(plan: StagePlan, camera: StageCamera | undefined, shot?: StageShot): DepthRange {
  if (!camera) return DEPTH_FALLBACK_RANGE;
  const origin = new Vector3(...camera.position);
  const forward = new Vector3(...camera.target).sub(origin);
  if (forward.lengthSq() === 0) return DEPTH_FALLBACK_RANGE;
  forward.normalize();

  const depths: number[] = [];
  actorsInShot(plan, shot).forEach(actor => {
    const [x, z] = actor.position;
    [0, actor.height_m].forEach(y => {
      const depth = depthAlong(new Vector3(x, y, z), origin, forward);
      if (depth !== null) depths.push(depth);
    });
  });
  plan.landmarks.forEach(landmark => {
    const [x, z] = landmark.position;
    [0, landmark.size[1]].forEach(y => {
      const depth = depthAlong(new Vector3(x, y, z), origin, forward);
      if (depth !== null) depths.push(depth);
    });
  });
  if (!depths.length) return DEPTH_FALLBACK_RANGE;

  const near = Math.max(0, Math.min(...depths) - DEPTH_PADDING_M);
  const far = Math.max(Math.max(...depths) + DEPTH_PADDING_M, near + DEPTH_MIN_SPAN_M);
  return { near, far };
}

// The standard chunks keep a skinned humanoid deforming and a morphed mesh morphing under the
// override: the renderer defines USE_SKINNING / USE_MORPHTARGETS per object and feeds the bone
// texture to any material that declares it. The depth itself is view-space z carried in a
// varying rather than gl_FragCoord.z linearised: it is exact for every point, needs no near/far
// uniforms, and is unaffected by the lens's 0.05 m / 500 m planes.
const VERTEX = /* glsl */ `
#include <common>
#include <skinning_pars_vertex>
#include <morphtarget_pars_vertex>
varying float vLensDepth;
void main() {
  #include <skinbase_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  #include <skinning_vertex>
  #include <project_vertex>
  vLensDepth = -mvPosition.z;
}
`;

const FRAGMENT = /* glsl */ `
uniform float nearM;
uniform float farM;
uniform float invert;
varying float vLensDepth;
void main() {
  float t = clamp((vLensDepth - nearM) / max(farM - nearM, 0.001), 0.0, 1.0);
  float shade = mix(1.0 - t, t, invert);
  gl_FragColor = vec4(vec3(shade), 1.0);
}
`;

/** The override material a depth render is drawn with. Dispose it when the render is done. */
export function createDepthMaterial({ range, invert = false }: DepthOptions): ShaderMaterial {
  return new ShaderMaterial({
    name: 'desk-depth',
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    uniforms: { nearM: { value: range.near }, farM: { value: range.far }, invert: { value: invert ? 1 : 0 } },
    // No colour, so no reason for a surface seen from behind (a plane prop, an open box) to vanish.
    side: DoubleSide,
    lights: false,
    fog: false,
  });
}

/** Whether `object` is left out of a depth picture even though an ordinary capture might show it. */
export function hiddenInDepth(object: Object3D): boolean {
  return Boolean(object.userData[BACKDROP_FLAG]);
}
