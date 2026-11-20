import type { SpacePoint, StageCamera, StageShot } from '../../spatial/spatialTypes';
import type { ViewPose } from '../deskTypes';

// The director view's own arithmetic: how far to stand back, how big a helper must be drawn to stay
// readable, how the floor grid is ruled. Kept free of three so each rule can be pinned by a test.

const HALF_DEGREE = Math.PI / 360;
/** Where the view stands, relative to what it frames, when it has no direction of its own yet. */
const DEFAULT_BEARING: SpacePoint = [0.45, 0.75, 0.6];
/** Framing a single object leaves air around it; framing the whole set already has its own margin. */
const FOCUS_MARGIN = 1.25;
/** The orbit never comes closer than this (OrbitControls' minDistance). */
const NEAREST_M = 0.5;

/** Metres that one screen pixel covers, `distance` in front of a perspective camera. */
export function metresPerPixel(distance: number, fovDeg: number, viewportHeightPx: number): number {
  return (2 * Math.max(distance, 0) * Math.tan(fovDeg * HALF_DEGREE)) / Math.max(viewportHeightPx, 1);
}

/** The scale that keeps something `worldSize` metres across at least `minPixels` on screen. Never under 1: up close it is its real size. */
export function screenScale(worldSize: number, minPixels: number, distance: number, fovDeg: number, viewportHeightPx: number): number {
  if (!(worldSize > 0)) return 1;
  return Math.max(1, (minPixels * metresPerPixel(distance, fovDeg, viewportHeightPx)) / worldSize);
}

/** How high something rides above a helper that `screenScale` keeps readable: `lift` metres up close, and as much further as the helper has grown. */
export function screenLift(lift: number, worldSize: number, minPixels: number, distance: number, fovDeg: number, viewportHeightPx: number): number {
  return lift * screenScale(worldSize, minPixels, distance, fovDeg, viewportHeightPx);
}

/** How far back the view stands to hold `radius` metres around its target. A pane narrower than tall needs more room for the same width. */
export function fitDistance(radius: number, fovDeg: number, aspect: number): number {
  return radius / Math.tan(fovDeg * HALF_DEGREE) / Math.min(1, Math.max(aspect, 0.1));
}

/** The view that takes in the whole set: from the front right, above. */
export function wholeSetPose(center: [number, number], radius: number, fovDeg: number, aspect: number): ViewPose {
  const distance = fitDistance(radius, fovDeg, aspect);
  return {
    position: [center[0] + distance * DEFAULT_BEARING[0], distance * DEFAULT_BEARING[1], center[1] + distance * DEFAULT_BEARING[2]],
    target: [center[0], 0, center[1]],
  };
}

/** The view turned onto one thing: it keeps the direction it was looking from and only changes what it looks at and from how far. */
export function focusPose(view: ViewPose, focus: { center: SpacePoint; radius: number }, fovDeg: number, aspect: number): ViewPose {
  let bearing: SpacePoint = [view.position[0] - view.target[0], view.position[1] - view.target[1], view.position[2] - view.target[2]];
  let length = Math.hypot(...bearing);
  if (length < 1e-6) {
    bearing = DEFAULT_BEARING;
    length = Math.hypot(...bearing);
  }
  const distance = Math.max(NEAREST_M, fitDistance(focus.radius, fovDeg, aspect) * FOCUS_MARGIN);
  return {
    position: [
      focus.center[0] + (bearing[0] / length) * distance,
      focus.center[1] + (bearing[1] / length) * distance,
      focus.center[2] + (bearing[2] / length) * distance,
    ],
    target: focus.center,
  };
}

/**
 * The floor grid's ruling. A cell is four snap steps (one metre at the finest), and a section is
 * always five cells, so the heavy lines land on cell lines whatever the snap step is.
 */
export function gridCells(gridSize: number): { cell: number; section: number } {
  const cell = gridSize >= 0.25 ? gridSize * 4 : 1;
  return { cell, section: cell * 5 };
}

const FRUSTUM_STUB_M = 0.7;
const FRUSTUM_ACTIVE_M = 2.4;
const FRUSTUM_SELECTED_M = 8;

/**
 * How far a lens's field of view is drawn out. Only the lens being worked on reaches to what it
 * looks at; the one filming the shot shows its angle without fencing off the stage, the rest a stub.
 */
export function frustumReach(lookDistance: number, state: 'selected' | 'active' | 'idle'): number {
  if (state === 'idle') return FRUSTUM_STUB_M;
  return Math.min(Math.max(lookDistance, 0.5), state === 'selected' ? FRUSTUM_SELECTED_M : FRUSTUM_ACTIVE_M);
}

/** What a lens is called over its body: every shot it films, or its own name while it films none. */
export function lensLabel(camera: Pick<StageCamera, 'id' | 'label'>, shots: Array<Pick<StageShot, 'shot_id' | 'camera_id'>>): string {
  const filmed = shots.filter(shot => shot.camera_id === camera.id).map(shot => shot.shot_id);
  return filmed.length ? filmed.join('、') : camera.label || camera.id;
}
