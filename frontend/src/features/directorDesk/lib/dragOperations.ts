import { actorsInShot, type GroundPoint, type SpacePoint, type StageOperation, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import { actorMoveOperation } from '../deskOperations';
import { refKey, type DeskTool, type SelectionRef, type SnapSettings } from '../deskTypes';
import { snapAngle, snapPosition, snapToGrid, type OrientedBox } from './snapping';
import { crowdOf, normalizeYaw, round2 } from './stageMath';

// What a gizmo drag means, as operations. The viewport feeds the same function on every pointer
// move (for the preview) and on pointer-up (for the PATCH), so what was shown is what is saved.

export interface AnchorTransform {
  position: SpacePoint;
  yawDeg: number;
  scale: [number, number, number];
}

export type GizmoMode = 'translate' | 'rotate' | 'scale';

const ACTOR_FOOTPRINT_M = 0.5;
const MIN_SIZE_M = 0.05;
const MAX_SIZE_M = 50;

export function gizmoMode(tool: DeskTool, ref: SelectionRef | undefined): GizmoMode | null {
  if (!ref) return null;
  if (tool === 'move') return 'translate';
  if (tool === 'rotate') return ref.kind === 'camera' || ref.kind === 'camera-target' ? null : 'rotate';
  if (tool === 'scale') return ref.kind === 'landmark' || ref.kind === 'crowd' ? 'scale' : null;
  return null;
}

/** Where the gizmo sits for `ref`, or `null` when it is not on stage in this shot. */
export function anchorOf(plan: StagePlan, shot: StageShot | undefined, ref: SelectionRef): AnchorTransform | null {
  const at = (position: SpacePoint, yawDeg = 0): AnchorTransform => ({ position, yawDeg, scale: [1, 1, 1] });
  switch (ref.kind) {
    case 'actor': {
      const actor = actorsInShot(plan, shot).find(item => item.name === ref.name);
      return actor ? at([actor.position[0], 0, actor.position[1]], actor.yaw_deg) : null;
    }
    case 'landmark': {
      const landmark = plan.landmarks.find(item => item.name === ref.name);
      return landmark ? at([landmark.position[0], 0, landmark.position[1]], landmark.yaw_deg ?? 0) : null;
    }
    case 'crowd': {
      const crowd = crowdOf(plan, ref.id);
      return crowd ? at([crowd.center[0], 0, crowd.center[1]], crowd.yaw_deg) : null;
    }
    default: {
      const camera = plan.cameras.find(item => item.id === ref.id);
      if (!camera) return null;
      return at(ref.kind === 'camera' ? camera.position : camera.target);
    }
  }
}

function boxesExcept(plan: StagePlan, names: Set<string>): OrientedBox[] {
  return plan.landmarks.filter(item => !names.has(item.name)).map(item => ({
    position: item.position, size: [item.size[0], item.size[1], item.size[2]], yawDeg: item.yaw_deg ?? 0,
  }));
}

function shifted(point: GroundPoint, delta: GroundPoint): GroundPoint {
  return [round2(point[0] + delta[0]), round2(point[1] + delta[1])];
}

function clampSize(value: number): number {
  return round2(Math.min(MAX_SIZE_M, Math.max(MIN_SIZE_M, value)));
}

function translate(plan: StagePlan, shot: StageShot | undefined, selection: SelectionRef[], primary: SelectionRef, start: AnchorTransform, now: AnchorTransform, snap: SnapSettings) {
  if (primary.kind === 'camera' || primary.kind === 'camera-target') {
    const ground = snap.grid ? snapToGrid([now.position[0], now.position[2]], snap.gridSize) : [now.position[0], now.position[2]];
    const position: SpacePoint = [round2(ground[0]), round2(Math.max(primary.kind === 'camera' ? 0.05 : -5, now.position[1])), round2(ground[1])];
    const key = primary.kind === 'camera' ? 'position' : 'target';
    return { anchor: { ...now, position }, operations: [{ op: 'move_camera', camera_id: primary.id, [key]: position } as StageOperation] };
  }

  const selectedLandmarks = new Set(selection.flatMap(ref => (ref.kind === 'landmark' ? [ref.name] : [])));
  const landmark = primary.kind === 'landmark' ? plan.landmarks.find(item => item.name === primary.name) : undefined;
  const actor = primary.kind === 'actor' ? actorsInShot(plan, shot).find(item => item.name === primary.name) : undefined;
  const moving: OrientedBox = {
    position: [now.position[0], now.position[2]],
    size: landmark ? [landmark.size[0], landmark.size[1], landmark.size[2]] : [ACTOR_FOOTPRINT_M, ACTOR_FOOTPRINT_M, actor?.height_m ?? 1.7],
    yawDeg: start.yawDeg,
  };
  // A crowd is many footprints, not one box: it takes the grid but has no face to offer.
  const ground = snapPosition(moving, boxesExcept(plan, selectedLandmarks), { ...snap, faces: snap.faces && primary.kind !== 'crowd' });
  const delta: GroundPoint = [ground[0] - start.position[0], ground[1] - start.position[2]];
  const operations: StageOperation[] = [];
  const seen = new Set<string>();
  [primary, ...selection].forEach(ref => {
    if (seen.has(refKey(ref))) return;
    seen.add(refKey(ref));
    const from = anchorOf(plan, shot, ref);
    if (!from) return;
    const to = shifted([from.position[0], from.position[2]], delta);
    if (ref.kind === 'actor') operations.push(actorMoveOperation(shot, ref.name, { position: to }));
    else if (ref.kind === 'landmark') operations.push({ op: 'transform_landmark', name: ref.name, position: to });
    else if (ref.kind === 'crowd') operations.push({ op: 'transform_crowd', crowd_id: ref.id, center: to });
    else if (ref.kind === 'camera') {
      const camera = plan.cameras.find(item => item.id === ref.id);
      // A lens carried along with its subjects keeps its framing: the look-at point travels too.
      if (camera) {
        operations.push({
          op: 'move_camera', camera_id: ref.id,
          position: [round2(camera.position[0] + delta[0]), camera.position[1], round2(camera.position[2] + delta[1])],
          target: [round2(camera.target[0] + delta[0]), camera.target[1], round2(camera.target[2] + delta[1])],
        });
      }
    }
  });
  return { anchor: { ...now, position: [round2(ground[0]), 0, round2(ground[1])] as SpacePoint }, operations };
}

export function dragOperations(input: {
  plan: StagePlan; shot: StageShot | undefined; selection: SelectionRef[]; primary: SelectionRef;
  mode: GizmoMode; snap: SnapSettings; start: AnchorTransform; now: AnchorTransform;
}): { operations: StageOperation[]; anchor: AnchorTransform } {
  const { plan, shot, selection, primary, mode, snap, start, now } = input;
  if (mode === 'translate') return translate(plan, shot, selection, primary, start, now, snap);

  if (mode === 'rotate') {
    const yaw = normalizeYaw(snap.angle ? snapAngle(now.yawDeg) : now.yawDeg);
    const anchor = { ...start, yawDeg: yaw };
    if (primary.kind === 'actor') return { anchor, operations: [actorMoveOperation(shot, primary.name, { yaw_deg: yaw })] };
    if (primary.kind === 'landmark') return { anchor, operations: [{ op: 'transform_landmark', name: primary.name, yaw_deg: yaw }] };
    if (primary.kind === 'crowd') return { anchor, operations: [{ op: 'transform_crowd', crowd_id: primary.id, yaw_deg: yaw }] };
    return { anchor: start, operations: [] };
  }

  if (primary.kind === 'landmark') {
    const landmark = plan.landmarks.find(item => item.name === primary.name);
    if (!landmark) return { anchor: start, operations: [] };
    // The gizmo's axes are X / Y / Z; a landmark's size is width / depth / height.
    const size = [clampSize(landmark.size[0] * now.scale[0]), clampSize(landmark.size[1] * now.scale[2]), clampSize(landmark.size[2] * now.scale[1])];
    return { anchor: start, operations: [{ op: 'transform_landmark', name: primary.name, size }] };
  }
  if (primary.kind === 'crowd') {
    const spacing = Math.min(10, Math.max(0.3, round2((crowdOf(plan, primary.id)?.spacing ?? 1) * Math.max(now.scale[0], now.scale[2]))));
    return { anchor: start, operations: [{ op: 'transform_crowd', crowd_id: primary.id, spacing }] };
  }
  return { anchor: start, operations: [] };
}
