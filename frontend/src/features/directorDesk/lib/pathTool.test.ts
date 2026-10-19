import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { GroundPoint, StagePlan } from '../../spatial/spatialTypes';
import {
  appendStrokePoint, MAX_PATH_POINTS, pathEdit, pathLabel, pathOperation, pathRefusal, pathTargetOf, strokeFull, strokeIsRoute,
} from './pathTool';

const CROWDED: StagePlan = {
  ...PLAN,
  crowds: [{ id: 'crowd-01', label: '围观', rows: 1, columns: 2, spacing: 1, center: [4, 4], yaw_deg: 0, body_type: 'standard', seed: 7 }],
  actors: [
    ...PLAN.actors,
    { ...PLAN.actors[2], id: 'crowd-01-001', name: '围观-01', position: [3.5, 4], role: 'crowd', crowd_id: 'crowd-01' },
  ],
  cameras: [...PLAN.cameras, { ...PLAN.cameras[0], id: 'alt-01-01', label: '01 建立 · 候选1' }],
  shots: [{ ...PLAN.shots[0], alt_camera_ids: ['alt-01-01'] }, PLAN.shots[1]],
};
const SHOT = CROWDED.shots[0];

describe('appendStrokePoint', () => {
  it('keeps a point only once the pointer has moved 5 cm, rounded to the centimetre', () => {
    let points: GroundPoint[] = [];
    points = appendStrokePoint(points, [0.004, 0.006]);
    expect(points).toEqual([[0, 0.01]]);
    const jitter = appendStrokePoint(points, [0.03, 0.02]);
    expect(jitter).toBe(points);
    points = appendStrokePoint(points, [0.05, 0.01]);
    expect(points).toEqual([[0, 0.01], [0.05, 0.01]]);
  });

  it('ignores a hit off the stage or with no number in it', () => {
    const points: GroundPoint[] = [[0, 0]];
    expect(appendStrokePoint(points, [600, 0])).toBe(points);
    expect(appendStrokePoint(points, [0, -500.5])).toBe(points);
    expect(appendStrokePoint(points, [Number.NaN, 1])).toBe(points);
    expect(appendStrokePoint(points, [500, 1])).toEqual([[0, 0], [500, 1]]);
  });

  it('stops at 400 points and says so', () => {
    let points: GroundPoint[] = [];
    for (let index = 0; index < MAX_PATH_POINTS + 20; index += 1) points = appendStrokePoint(points, [index * 0.1, 0]);
    expect(points).toHaveLength(MAX_PATH_POINTS);
    expect(points[MAX_PATH_POINTS - 1]).toEqual([39.9, 0]);
    expect(strokeFull(points)).toBe(true);
    expect(appendStrokePoint(points, [100, 100])).toBe(points);
  });

  it('needs two points before a stroke is a route', () => {
    expect(strokeIsRoute([])).toBe(false);
    expect(strokeIsRoute([[0, 0]])).toBe(false);
    expect(strokeIsRoute([[0, 0], [1, 0]])).toBe(true);
    expect(strokeFull([[0, 0], [1, 0]])).toBe(false);
  });
});

describe('pathTargetOf / pathRefusal', () => {
  it('takes a principal actor who is on stage in the shot', () => {
    expect(pathTargetOf(CROWDED, SHOT, { kind: 'actor', name: '林夏' })).toEqual({ kind: 'actor', name: '林夏' });
    expect(pathRefusal(CROWDED, SHOT, { kind: 'actor', name: '林夏' })).toBe('');
    // 助手 is offstage in shot 2.
    expect(pathRefusal(CROWDED, CROWDED.shots[1], { kind: 'actor', name: '助手' })).toContain('不在场');
  });

  it('refuses a crowd, a crowd member, a prop and the look-at handle', () => {
    expect(pathTargetOf(CROWDED, SHOT, { kind: 'crowd', id: 'crowd-01' })).toBeNull();
    expect(pathRefusal(CROWDED, SHOT, { kind: 'crowd', id: 'crowd-01' })).toContain('群演');
    expect(pathRefusal(CROWDED, SHOT, { kind: 'actor', name: '围观-01' })).toBe('群演成员不能单独画走位');
    expect(pathRefusal(CROWDED, SHOT, { kind: 'landmark', name: '录音笔' })).toContain('道具');
    expect(pathRefusal(CROWDED, SHOT, { kind: 'camera-target', id: 'cam-01' })).toContain('机位本身');
  });

  it('takes only the camera that films the shot, aiming at its first subject', () => {
    expect(pathTargetOf(CROWDED, SHOT, { kind: 'camera', id: 'cam-01' })).toEqual({ kind: 'camera', id: 'cam-01', lookAt: '林夏' });
    expect(pathRefusal(CROWDED, SHOT, { kind: 'camera', id: 'alt-01-01' })).toContain('候选机位');
    expect(pathRefusal(CROWDED, SHOT, { kind: 'camera', id: 'cam-02' })).toContain('不拍摄本镜');
    expect(pathRefusal(CROWDED, SHOT, { kind: 'camera', id: 'nope' })).toContain('不在方案里');
    const empty: StagePlan = { ...CROWDED, cameras: CROWDED.cameras.map(camera => ({ ...camera, subjects: [] })) };
    expect(pathTargetOf(empty, SHOT, { kind: 'camera', id: 'cam-01' })).toEqual({ kind: 'camera', id: 'cam-01', lookAt: 'ahead' });
  });

  it('needs a plan, a shot and a selection', () => {
    expect(pathRefusal(undefined, SHOT, { kind: 'actor', name: '林夏' })).toContain('镜头');
    expect(pathRefusal(CROWDED, undefined, { kind: 'actor', name: '林夏' })).toContain('镜头');
    expect(pathRefusal(CROWDED, SHOT, undefined)).toContain('先选择');
  });
});

describe('pathOperation / pathEdit', () => {
  const ROUTE: GroundPoint[] = [[-1.3, 0], [0, 1], [1.2, 1.1]];

  it('sends an actor route under the actor’s name', () => {
    expect(pathOperation(1, { kind: 'actor', name: '林夏' }, ROUTE)).toEqual({ op: 'set_path', shot_id: 1, target: '林夏', points: ROUTE });
    expect(pathLabel({ kind: 'actor', name: '林夏' })).toBe('手绘走位：林夏');
  });

  it('sends a camera route as 2-D points with the look-at it was given', () => {
    expect(pathOperation(1, { kind: 'camera', id: 'cam-01', lookAt: '林夏' }, ROUTE)).toEqual({ op: 'set_path', shot_id: 1, target: 'camera', points: ROUTE, look_at: '林夏' });
    expect(pathOperation(2, { kind: 'camera', id: 'cam-02', lookAt: 'ahead' }, ROUTE)).toMatchObject({ target: 'camera', look_at: 'ahead' });
    expect(pathLabel({ kind: 'camera', id: 'cam-01', lookAt: 'ahead' })).toBe('手绘机位路径');
  });

  it('goes to the server alone, since only its answer holds the keys', () => {
    expect(pathEdit(1, { kind: 'actor', name: '林夏' }, ROUTE)).toEqual({
      operations: [{ op: 'set_path', shot_id: 1, target: '林夏', points: ROUTE }], label: '手绘走位：林夏', barrier: true,
    });
  });
});
