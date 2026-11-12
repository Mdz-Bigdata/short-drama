import { Group, PerspectiveCamera, Quaternion, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { faceViewer } from './faceViewer';

function viewer(): PerspectiveCamera {
  const camera = new PerspectiveCamera(42, 16 / 9, 0.05, 500);
  camera.position.set(5.5, 5, 8);
  camera.lookAt(0, 1, 0);
  return camera;
}

function staged(yawDeg: number) {
  const set = new Group();
  const figure = new Group();
  const label = new Group();
  figure.rotation.y = (yawDeg * Math.PI) / 180;
  set.add(figure);
  figure.add(label);
  return { figure, label };
}

describe('faceViewer', () => {
  it('faces the viewer from inside a turned figure', () => {
    const camera = viewer();
    for (const yaw of [0, 90, 180, -135]) {
      const { label } = staged(yaw);
      faceViewer(label, camera);
      expect(label.getWorldQuaternion(new Quaternion()).angleTo(camera.quaternion)).toBeCloseTo(0, 6);
      // Read from the front, never mirrored: the label's own +Z points back at the lens.
      const towardViewer = new Vector3(0, 0, 1).applyQuaternion(label.getWorldQuaternion(new Quaternion()));
      expect(towardViewer.dot(camera.getWorldDirection(new Vector3()))).toBeCloseTo(-1, 6);
    }
  });

  it('follows a figure turned since the last draw', () => {
    const camera = viewer();
    const { figure, label } = staged(30);
    // What a draw leaves behind: world matrices as of the old facing.
    figure.parent?.updateMatrixWorld(true);
    figure.rotation.y = Math.PI;
    faceViewer(label, camera);
    expect(label.getWorldQuaternion(new Quaternion()).angleTo(camera.quaternion)).toBeCloseTo(0, 6);
  });

  it('takes the viewer as is when it hangs from nothing', () => {
    const camera = viewer();
    const label = new Group();
    faceViewer(label, camera);
    expect(label.quaternion.angleTo(camera.quaternion)).toBeCloseTo(0, 6);
  });
});
