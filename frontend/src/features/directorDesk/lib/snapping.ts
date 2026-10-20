// Grid and face snapping for things that stand on the floor. Oriented-box face snapping is ported
// from mangfufu/director-desk (MIT): a face of the moving box is pulled onto a face of a
// neighbour when the two are within the threshold AND the boxes overlap on the other two axes,
// so a chair snaps to the wall it is next to, not to one across the room.

export interface OrientedBox {
  /** Centre of the footprint on the ground: [x, z]. */
  position: [number, number];
  /** Width (local X), depth (local Z), height (Y). */
  size: [number, number, number];
  yawDeg: number;
  /** Height of the underside above the floor. */
  baseY?: number;
}

export interface FaceSnap {
  position: [number, number];
  /** Index into `others` of each box that pulled, in the order applied. */
  snappedTo: number[];
}

export const FACE_SNAP_THRESHOLD_M = 0.2;
const MIN_OVERLAP_M = 0.01;
const ANGLE_EPSILON_DEG = 0.5;

export function snapValue(value: number, step: number): number {
  if (!(step > 0)) return value;
  return Math.round(Math.round(value / step) * step * 1000) / 1000;
}

export function snapToGrid(point: [number, number], step: number): [number, number] {
  return [snapValue(point[0], step), snapValue(point[1], step)];
}

export function snapAngle(degrees: number, step = 15): number {
  return snapValue(degrees, step);
}

function toLocal(point: [number, number], origin: [number, number], yawDeg: number): [number, number] {
  const radians = (yawDeg * Math.PI) / 180;
  const dx = point[0] - origin[0];
  const dz = point[1] - origin[1];
  // Inverse of the yaw rotation (+Z toward +X).
  return [dx * Math.cos(radians) - dz * Math.sin(radians), dx * Math.sin(radians) + dz * Math.cos(radians)];
}

function toWorldVector(vector: [number, number], yawDeg: number): [number, number] {
  const radians = (yawDeg * Math.PI) / 180;
  return [vector[0] * Math.cos(radians) + vector[1] * Math.sin(radians), -vector[0] * Math.sin(radians) + vector[1] * Math.cos(radians)];
}

/** Half extents of `box` measured along the axes of a frame turned `frameYawDeg`. */
function halfExtentsIn(box: OrientedBox, frameYawDeg: number): [number, number] {
  const relative = ((box.yawDeg - frameYawDeg) * Math.PI) / 180;
  const cos = Math.abs(Math.cos(relative));
  const sin = Math.abs(Math.sin(relative));
  const [w, d] = [box.size[0] / 2, box.size[1] / 2];
  return [w * cos + d * sin, w * sin + d * cos];
}

function squareTo(box: OrientedBox, frameYawDeg: number): boolean {
  const relative = Math.abs(((box.yawDeg - frameYawDeg) % 90 + 90) % 90);
  return relative < ANGLE_EPSILON_DEG || relative > 90 - ANGLE_EPSILON_DEG;
}

function overlap(minA: number, maxA: number, minB: number, maxB: number): number {
  return Math.min(maxA, maxB) - Math.max(minA, minB);
}

interface Candidate {
  delta: number;
  direction: [number, number];
  index: number;
}

function bestCandidate(moving: OrientedBox, others: OrientedBox[], threshold: number, taken: [number, number][]): Candidate | null {
  let best: Candidate | null = null;
  const bottom = moving.baseY ?? 0;
  others.forEach((other, index) => {
    const otherBottom = other.baseY ?? 0;
    if (overlap(bottom, bottom + moving.size[2], otherBottom, otherBottom + other.size[2]) < MIN_OVERLAP_M) return;
    const centre = toLocal(moving.position, other.position, other.yawDeg);
    const half = halfExtentsIn(moving, other.yawDeg);
    const otherHalf: [number, number] = [other.size[0] / 2, other.size[1] / 2];
    // A box turned against its neighbour only has corners to offer, not faces, to flush against.
    const flush = squareTo(moving, other.yawDeg);
    ([0, 1] as const).forEach(axis => {
      const across = axis === 0 ? 1 : 0;
      const shared = overlap(centre[across] - half[across], centre[across] + half[across], -otherHalf[across], otherHalf[across]);
      // Boxes that already touch side by side share no width, yet their ends can still line up.
      if (shared < -1e-6) return;
      const direction = toWorldVector(axis === 0 ? [1, 0] : [0, 1], other.yawDeg);
      if (taken.some(used => Math.abs(used[0] * direction[0] + used[1] * direction[1]) > 0.01)) return;
      const min = centre[axis] - half[axis];
      const max = centre[axis] + half[axis];
      const deltas = shared >= MIN_OVERLAP_M ? [-otherHalf[axis] - max, otherHalf[axis] - min] : []; // touching from either side
      if (flush) deltas.push(-otherHalf[axis] - min, otherHalf[axis] - max); // faces in one plane
      deltas.forEach(delta => {
        // Already in place is not a pull.
        if (Math.abs(delta) > 1e-9 && Math.abs(delta) <= threshold && (!best || Math.abs(delta) < Math.abs(best.delta))) best = { delta, direction, index };
      });
    });
  });
  return best;
}

/**
 * Pull `moving` onto the nearest faces of `others`. At most two pulls, along perpendicular
 * directions, so a box slides into a corner but is never dragged twice along one line.
 */
export function snapToFaces(moving: OrientedBox, others: OrientedBox[], threshold = FACE_SNAP_THRESHOLD_M): FaceSnap {
  let position = moving.position;
  const taken: [number, number][] = [];
  const snappedTo: number[] = [];
  for (let pass = 0; pass < 2; pass += 1) {
    const candidate = bestCandidate({ ...moving, position }, others, threshold, taken);
    if (!candidate) break;
    position = [position[0] + candidate.direction[0] * candidate.delta, position[1] + candidate.direction[1] * candidate.delta];
    taken.push(candidate.direction);
    snappedTo.push(candidate.index);
  }
  return { position: [Math.round(position[0] * 1000) / 1000, Math.round(position[1] * 1000) / 1000], snappedTo };
}

/** Grid first, faces second: a face within reach wins over the grid line it would have landed on. */
export function snapPosition(
  moving: OrientedBox, others: OrientedBox[], settings: { grid: boolean; gridSize: number; faces: boolean },
): [number, number] {
  const gridded = settings.grid ? snapToGrid(moving.position, settings.gridSize) : moving.position;
  if (!settings.faces) return gridded;
  const faces = snapToFaces({ ...moving, position: moving.position }, others);
  return faces.snappedTo.length ? faces.position : gridded;
}
