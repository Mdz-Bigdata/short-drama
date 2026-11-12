import { Mesh, type Intersection, type Raycaster } from 'three';

/**
 * `raycast` for a mesh that is drawn over everything (no depth test): the pointer hits it before
 * everything too, whatever stands nearer along the ray. Without it a handle seen through a body
 * gives its hover to the body, and the pointer says "pick" over something that is dragged.
 */
export function hitOnTop(this: Mesh, raycaster: Raycaster, intersects: Intersection[]): void {
  const first = intersects.length;
  Mesh.prototype.raycast.call(this, raycaster, intersects);
  for (let index = first; index < intersects.length; index += 1) intersects[index].distance = 0;
}

/**
 * `raycast` for something the stage hides by turning it invisible rather than unmounting it (a
 * name that gave way to a dot, and the dot while the name shows): three ray-tests invisible
 * meshes, so without this a hidden name would still take the click meant for what is behind it.
 */
export function raycastWhenShown(this: Mesh, raycaster: Raycaster, intersects: Intersection[]): void {
  if (this.visible) Object.getPrototypeOf(this).raycast.call(this, raycaster, intersects);
}
