import { useRef, type ReactNode } from 'react';
import { useFrame } from '@react-three/fiber';
import { Vector3, type Group, type PerspectiveCamera } from 'three';

import { screenLift, screenScale } from '../lib/viewHelpers';
import { LABEL_PREP_PRIORITY } from './labelLayout';

const WORLD = new Vector3();

/**
 * A handle that stays big enough to grab. Its children are drawn at their real size (`size` metres
 * across) up close and grown once the view has backed off so far that they would fall under
 * `minPixels`. The scale is set just before each frame is drawn, so what is clicked is what is seen.
 */
export function ScreenSized({ position, size, minPixels, children }: {
  position: [number, number, number] | Vector3;
  size: number;
  minPixels: number;
  children: ReactNode;
}) {
  const group = useRef<Group>(null);
  useFrame(({ camera, size: viewport }) => {
    const node = group.current;
    if (!node) return;
    const lens = camera as PerspectiveCamera;
    const scale = lens.isPerspectiveCamera
      ? screenScale(size, minPixels, lens.position.distanceTo(node.getWorldPosition(WORLD)), lens.fov, viewport.height)
      : 1;
    if (node.scale.x !== scale) node.scale.setScalar(scale);
  });
  return <group ref={group} position={position}>{children}</group>;
}

/**
 * Something that rides `lift` metres above a `ScreenSized` helper standing at the same `position`
 * with the same `size` and `minPixels`. It keeps its own size and moves up as the helper grows, so a
 * helper drawn large from far away does not cover it.
 */
export function ScreenLifted({ position, lift, size, minPixels, children }: {
  position: [number, number, number] | Vector3;
  lift: number;
  size: number;
  minPixels: number;
  children: ReactNode;
}) {
  const anchor = useRef<Group>(null);
  const rider = useRef<Group>(null);
  useFrame(({ camera, size: viewport }) => {
    const node = rider.current;
    if (!anchor.current || !node) return;
    const lens = camera as PerspectiveCamera;
    const y = lens.isPerspectiveCamera
      ? screenLift(lift, size, minPixels, lens.position.distanceTo(anchor.current.getWorldPosition(WORLD)), lens.fov, viewport.height)
      : lift;
    if (node.position.y !== y) node.position.y = y;
    // Before the labels are laid out: a lens's label is measured where it rides this frame.
  }, LABEL_PREP_PRIORITY);
  return <group ref={anchor} position={position}><group ref={rider}>{children}</group></group>;
}
