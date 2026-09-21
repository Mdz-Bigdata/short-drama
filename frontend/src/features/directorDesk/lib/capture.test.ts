import { PerspectiveCamera } from 'three';
import { describe, expect, it } from 'vitest';

import { captureShowsLimbs, captureSize, projectToImage } from './capture';

describe('captureSize', () => {
  it('puts 1920 on the long edge for every delivery aspect', () => {
    expect(captureSize(9 / 16)).toEqual({ width: 1080, height: 1920 });
    expect(captureSize(16 / 9)).toEqual({ width: 1920, height: 1080 });
    expect(captureSize(1)).toEqual({ width: 1920, height: 1920 });
    expect(captureSize(4 / 3)).toEqual({ width: 1920, height: 1440 });
    expect(captureSize(3 / 4)).toEqual({ width: 1440, height: 1920 });
  });

  it('keeps both sides even when the ratio does not divide cleanly', () => {
    expect(captureSize(2.39)).toEqual({ width: 1920, height: 804 });   // 803.3 → 804
    expect(captureSize(21 / 9)).toEqual({ width: 1920, height: 822 }); // 822.9 → 822
    [0.41, 0.5625, 1.37, 1.85, 2.2].forEach(aspect => {
      const size = captureSize(aspect);
      expect(size.width % 2).toBe(0);
      expect(size.height % 2).toBe(0);
      expect(Math.max(size.width, size.height)).toBe(1920);
    });
  });

  it('falls back to portrait delivery on nonsense and honours another long edge', () => {
    expect(captureSize(Number.NaN)).toEqual({ width: 1080, height: 1920 });
    expect(captureSize(16 / 9, 1280)).toEqual({ width: 1280, height: 720 });
  });
});

describe('projectToImage', () => {
  const camera = new PerspectiveCamera(60, 1080 / 1920, 0.1, 100);
  camera.position.set(0, 1, 5);
  camera.lookAt(0, 1, 0);
  camera.updateMatrixWorld();

  it('lands the look-at point in the middle of the image', () => {
    const spot = projectToImage([0, 1, 0], camera, 1080, 1920)!;
    expect(spot[0]).toBeCloseTo(540, 3);
    expect(spot[1]).toBeCloseTo(960, 3);
    expect(projectToImage([0, 2, 0], camera, 1080, 1920)![1]).toBeLessThan(960);
  });

  it('drops labels that are behind the lens or out of frame', () => {
    expect(projectToImage([0, 1, 9], camera, 1080, 1920)).toBeNull();
    expect(projectToImage([40, 1, 0], camera, 1080, 1920)).toBeNull();
  });
});

describe('captureShowsLimbs', () => {
  const camera = new PerspectiveCamera(40, 9 / 16, 0.05, 500);
  camera.position.set(0, 1.4, 5);
  camera.lookAt(0, 1, 0);
  camera.updateMatrixWorld();
  camera.updateProjectionMatrix();
  const figure = (kind: 'standin' | 'mannequin' | 'humanoid' | undefined, position: [number, number]) => ({ actor: { figure: kind, position }, height: 1.7 });

  it('is set by a jointed or skinned figure the lens can see', () => {
    expect(captureShowsLimbs([figure('standin', [0, 0]), figure(undefined, [0.3, 0])], camera, 1080, 1920)).toBe(false);
    expect(captureShowsLimbs([figure('standin', [0, 0]), figure('mannequin', [0.3, 0])], camera, 1080, 1920)).toBe(true);
    expect(captureShowsLimbs([figure('humanoid', [0, -1])], camera, 1080, 1920)).toBe(true);
    expect(captureShowsLimbs([], camera, 1080, 1920)).toBe(false);
  });

  it('ignores a limbed figure that is behind the lens or out of frame', () => {
    expect(captureShowsLimbs([figure('mannequin', [0, 9])], camera, 1080, 1920)).toBe(false);
    expect(captureShowsLimbs([figure('mannequin', [30, 0])], camera, 1080, 1920)).toBe(false);
  });
});
