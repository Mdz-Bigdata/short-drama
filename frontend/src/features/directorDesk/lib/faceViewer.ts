import { Quaternion, type Object3D } from 'three';

const PARENT_TURN = new Quaternion();

/**
 * Turn `node` to face the way `viewer` faces, whichever way its parents are turned. The parents are
 * read as they stand now, not as they were last drawn: a figure that has just been turned must not
 * leave its name a frame behind. `viewer` sits at the top of its scene, as every desk camera does.
 */
export function faceViewer(node: Object3D, viewer: Object3D): void {
  if (node.parent) node.quaternion.copy(node.parent.getWorldQuaternion(PARENT_TURN).invert()).multiply(viewer.quaternion);
  else node.quaternion.copy(viewer.quaternion);
}
