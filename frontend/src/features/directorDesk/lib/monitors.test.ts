import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import { clockText, locateInScene, monitorsOf, nextShotId, sceneDuration, sceneSegments, sceneTimeOf } from './monitors';

const ALT = { ...PLAN.cameras[0], id: 'alt-01', label: '01 建立 · 俯拍', lens_mm: 35 };
const CUT = { ...PLAN.cameras[0], id: 'cut-01', label: '01 建立 · 反打', lens_mm: 50 };
const SCENE: StagePlan = {
  ...PLAN,
  cameras: [...PLAN.cameras, ALT, CUT],
  shots: [{ ...PLAN.shots[0], alt_camera_ids: ['alt-01'] }, PLAN.shots[1]],
  timelines: {
    1: { duration_s: 4, fps: 24, camera: [], actors: {}, cuts: [{ id: 'c1', start: 2, end: 4, camera_id: 'cut-01' }] },
    2: { duration_s: 2.5, fps: 24, camera: [], actors: {} },
  },
} as StagePlan;

describe('monitorsOf', () => {
  it('shows every shot through its lens, and the current shot’s other lenses under it', () => {
    const monitors = monitorsOf(SCENE, 1, 0, []);
    expect(monitors.map(monitor => [monitor.key, monitor.role, monitor.cameraId, monitor.title])).toEqual([
      ['shot:1', 'shot', 'cam-01', '第 1 镜｜建立 · 林夏、周教授'],
      ['lens:1:cut-01', 'cut', 'cut-01', '01 建立 · 反打'],
      ['lens:1:alt-01', 'candidate', 'alt-01', '01 建立 · 俯拍'],
      ['shot:2', 'shot', 'cam-02', '第 2 镜｜单人 · 林夏'],
    ]);
  });

  it('follows a cut at the playhead, and lists the filming lens it took off screen', () => {
    const monitors = monitorsOf(SCENE, 1, 3, []);
    expect(monitors.slice(0, 3).map(monitor => [monitor.role, monitor.cameraId])).toEqual([['shot', 'cut-01'], ['filming', 'cam-01'], ['candidate', 'alt-01']]);
    // Another shot is not the current one: it shows its first frame and no other lenses.
    expect(monitorsOf(SCENE, 2, 0, []).map(monitor => monitor.key)).toEqual(['shot:1', 'shot:2']);
  });

  it('changes a monitor’s signature only when its picture changes', () => {
    const before = monitorsOf(SCENE, 1, 0, []);
    const moved = { ...SCENE, landmarks: [{ ...SCENE.landmarks[0], position: [2, 2] as [number, number] }] };
    const after = monitorsOf(moved, 1, 0, []);
    expect(after[0].signature).not.toBe(before[0].signature);
    expect(monitorsOf({ ...SCENE }, 1, 0, [])[0].signature).toBe(before[0].signature);
    // Hiding someone changes what the lens sees.
    expect(monitorsOf(SCENE, 1, 0, ['actor:林夏'])[0].signature).not.toBe(before[0].signature);
  });
});

describe('the scene clock', () => {
  const segments = sceneSegments(SCENE);

  it('lays the shots end to end', () => {
    expect(segments.map(segment => [segment.shotId, segment.start, segment.duration])).toEqual([[1, 0, 4], [2, 4, 2.5]]);
    expect(sceneDuration(segments)).toBe(6.5);
    expect(sceneTimeOf(segments, 2, 1)).toBe(5);
  });

  it('finds the shot a time falls in, the very end belonging to the last', () => {
    expect(locateInScene(segments, 0)).toEqual({ shotId: 1, time: 0 });
    expect(locateInScene(segments, 4)).toEqual({ shotId: 2, time: 0 });
    expect(locateInScene(segments, 5.25)).toEqual({ shotId: 2, time: 1.25 });
    expect(locateInScene(segments, 99)).toEqual({ shotId: 2, time: 2.5 });
    expect(locateInScene([], 1)).toBeNull();
  });

  it('knows the next shot and reads as a clock', () => {
    expect(nextShotId(segments, 1)).toBe(2);
    expect(nextShotId(segments, 2)).toBeUndefined();
    expect(clockText(67.9)).toBe('01:07');
  });
});
