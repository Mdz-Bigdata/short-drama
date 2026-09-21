import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { SnapSettings } from '../deskTypes';
import { anchorOf, dragOperations, gizmoMode, type AnchorTransform } from './dragOperations';

const FREE: SnapSettings = { grid: false, gridSize: 0.25, faces: false, angle: false };
const at = (x: number, y: number, z: number, yawDeg = 0, scale: [number, number, number] = [1, 1, 1]): AnchorTransform => ({ position: [x, y, z], yawDeg, scale });

const CROWDED: StagePlan = {
  ...PLAN,
  actors: [
    ...PLAN.actors,
    { id: 'actor-10', name: '路人 1', position: [4, 4], yaw_deg: 180, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
    { id: 'actor-11', name: '路人 2', position: [5, 4], yaw_deg: 180, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
  ],
};

describe('gizmoMode', () => {
  it('only offers what the object can take', () => {
    expect(gizmoMode('select', { kind: 'actor', name: '林夏' })).toBeNull();
    expect(gizmoMode('move', { kind: 'camera', id: 'cam-01' })).toBe('translate');
    expect(gizmoMode('rotate', { kind: 'camera', id: 'cam-01' })).toBeNull();
    expect(gizmoMode('scale', { kind: 'actor', name: '林夏' })).toBeNull();
    expect(gizmoMode('scale', { kind: 'landmark', name: '录音笔' })).toBe('scale');
  });
});

describe('dragOperations', () => {
  it('moves an actor on the floor and snaps to the grid', () => {
    const primary = { kind: 'actor', name: '林夏' } as const;
    const start = anchorOf(PLAN, PLAN.shots[0], primary)!;
    const result = dragOperations({ plan: PLAN, shot: PLAN.shots[0], selection: [primary], primary, mode: 'translate', snap: { ...FREE, grid: true }, start, now: at(-0.61, 0.4, 0.9) });
    expect(result.operations).toEqual([{ op: 'move_actor', name: '林夏', position: [-0.5, 1] }]);
    expect(result.anchor.position).toEqual([-0.5, 0, 1]);
  });

  it('carries the rest of the selection by the same offset', () => {
    const primary = { kind: 'actor', name: '林夏' } as const;
    const selection = [{ kind: 'landmark', name: '录音笔' } as const, { kind: 'crowd', id: 'crowd-01' } as const, primary];
    const start = anchorOf(CROWDED, undefined, primary)!;
    const { operations } = dragOperations({ plan: CROWDED, shot: undefined, selection, primary, mode: 'translate', snap: FREE, start, now: at(-0.3, 0, 0.5) });
    expect(operations).toEqual([
      { op: 'move_actor', name: '林夏', position: [-0.3, 0.5] },
      { op: 'transform_landmark', name: '录音笔', position: [1, -0.4] },
      { op: 'transform_crowd', crowd_id: 'crowd-01', center: [5.5, 4.5] },
    ]);
  });

  it('writes the shot override when that is what the viewport is showing', () => {
    const shot = { ...PLAN.shots[1], overrides: [{ name: '林夏', position: [0, 2] as [number, number], reason: '走到窗边' }] };
    const primary = { kind: 'actor', name: '林夏' } as const;
    const start = anchorOf(PLAN, shot, primary)!;
    expect(start.position).toEqual([0, 0, 2]);
    const { operations } = dragOperations({ plan: PLAN, shot, selection: [primary], primary, mode: 'translate', snap: FREE, start, now: at(1, 0, 2) });
    expect(operations).toEqual([{ op: 'set_shot_override', shot_id: 2, name: '林夏', position: [1, 2], reason: '走到窗边' }]);
  });

  it('snaps a prop against its neighbour, turning yaw only', () => {
    const plan: StagePlan = { ...PLAN, landmarks: [...PLAN.landmarks, { id: 'mark-02', name: '桌子', kind: 'furniture', position: [3, 3], size: [2, 1, 0.8] }] };
    const primary = { kind: 'landmark', name: '录音笔' } as const;
    const start = anchorOf(plan, undefined, primary)!;
    const moved = dragOperations({ plan, shot: undefined, selection: [primary], primary, mode: 'translate', snap: { ...FREE, faces: true }, start, now: at(1.65, 0, 3) });
    expect(moved.operations).toEqual([{ op: 'transform_landmark', name: '录音笔', position: [1.75, 3] }]);

    const turned = dragOperations({ plan, shot: undefined, selection: [primary], primary, mode: 'rotate', snap: { ...FREE, angle: true }, start, now: at(0, 0, -0.9, 97) });
    expect(turned.operations).toEqual([{ op: 'transform_landmark', name: '录音笔', yaw_deg: 90 }]);
  });

  it('maps the gizmo axes onto width / depth / height and clamps the size', () => {
    const primary = { kind: 'landmark', name: '录音笔' } as const;
    const start = anchorOf(PLAN, undefined, primary)!;
    const { operations } = dragOperations({ plan: PLAN, shot: undefined, selection: [primary], primary, mode: 'scale', snap: FREE, start, now: at(0, 0, -0.9, 0, [2, 3, 0.01]) });
    expect(operations).toEqual([{ op: 'transform_landmark', name: '录音笔', size: [1, 0.05, 1.5] }]);
  });

  it('moves a camera in three dimensions and its look-at handle on its own', () => {
    const camera = { kind: 'camera', id: 'cam-01' } as const;
    const moved = dragOperations({ plan: PLAN, shot: PLAN.shots[0], selection: [camera], primary: camera, mode: 'translate', snap: FREE, start: anchorOf(PLAN, undefined, camera)!, now: at(1, 2.5, 4) });
    expect(moved.operations).toEqual([{ op: 'move_camera', camera_id: 'cam-01', position: [1, 2.5, 4] }]);

    const target = { kind: 'camera-target', id: 'cam-01' } as const;
    const aimed = dragOperations({ plan: PLAN, shot: PLAN.shots[0], selection: [target], primary: target, mode: 'translate', snap: FREE, start: anchorOf(PLAN, undefined, target)!, now: at(0.5, 1.2, 0) });
    expect(aimed.operations).toEqual([{ op: 'move_camera', camera_id: 'cam-01', target: [0.5, 1.2, 0] }]);
  });

  it('turns and re-spaces a crowd as one', () => {
    const primary = { kind: 'crowd', id: 'crowd-01' } as const;
    const start = anchorOf(CROWDED, undefined, primary)!;
    expect(start).toEqual(at(4.5, 0, 4, 180));
    expect(dragOperations({ plan: CROWDED, shot: undefined, selection: [primary], primary, mode: 'rotate', snap: FREE, start, now: at(4.5, 0, 4, -135) }).operations)
      .toEqual([{ op: 'transform_crowd', crowd_id: 'crowd-01', yaw_deg: -135 }]);
    expect(dragOperations({ plan: CROWDED, shot: undefined, selection: [primary], primary, mode: 'scale', snap: FREE, start, now: at(4.5, 0, 4, 180, [1.5, 1, 1.5]) }).operations)
      .toEqual([{ op: 'transform_crowd', crowd_id: 'crowd-01', spacing: 1.5 }]);
  });
});
