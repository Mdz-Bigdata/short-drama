import { BoxGeometry, Mesh, MeshBasicMaterial, PerspectiveCamera, PlaneGeometry, Raycaster, Scene, SphereGeometry, Vector2, type Intersection } from 'three';
import { describe, expect, it } from 'vitest';

import { hitOnTop, raycastWhenShown } from './hitOnTop';

/** A handle behind a body, both on the lens's axis, as the pointer finds them. */
function staged() {
  const scene = new Scene();
  const body = new Mesh(new BoxGeometry(0.5, 1.6, 0.3), new MeshBasicMaterial());
  body.position.set(0, 0, 0);
  const handle = new Mesh(new SphereGeometry(0.055, 16, 12), new MeshBasicMaterial({ depthTest: false }));
  handle.position.set(0, 0, -0.6);
  handle.raycast = hitOnTop;
  scene.add(body, handle);
  const camera = new PerspectiveCamera(42, 1, 0.05, 500);
  camera.position.set(0, 0, 5);
  camera.lookAt(0, 0, 0);
  scene.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);
  const raycaster = new Raycaster();
  const hitsAt = (x: number, y: number) => {
    raycaster.setFromCamera(new Vector2(x, y), camera);
    // The order the stage's pointer events use: every hit, nearest first.
    return [body, handle].flatMap(object => raycaster.intersectObject(object, true)).sort((a, b) => a.distance - b.distance);
  };
  return { body, handle, hitsAt };
}

describe('hitOnTop', () => {
  it('puts a handle seen through a body ahead of the body', () => {
    const { body, handle, hitsAt } = staged();
    const hits = hitsAt(0, 0);
    expect(hits[0].object).toBe(handle);
    expect(hits.some(hit => hit.object === body)).toBe(true);
  });

  it('still misses a handle the pointer is not over', () => {
    const { body, handle, hitsAt } = staged();
    const hits = hitsAt(0, 0.15);
    expect(hits[0].object).toBe(body);
    expect(hits.some(hit => hit.object === handle)).toBe(false);
  });

  it('is behind the body without it', () => {
    const { body, handle, hitsAt } = staged();
    handle.raycast = Mesh.prototype.raycast;
    expect(hitsAt(0, 0)[0].object).toBe(body);
  });
});

/** A name over a figure: a flat label between the lens and the body, as a prop's name can hang in front of an actor. */
function labelled(label: Mesh) {
  const scene = new Scene();
  const body = new Mesh(new BoxGeometry(0.5, 1.6, 0.3), new MeshBasicMaterial());
  label.position.set(0, 0, 1);
  label.raycast = raycastWhenShown;
  scene.add(body, label);
  const camera = new PerspectiveCamera(42, 1, 0.05, 500);
  camera.position.set(0, 0, 5);
  camera.lookAt(0, 0, 0);
  scene.updateMatrixWorld(true);
  const raycaster = new Raycaster();
  raycaster.setFromCamera(new Vector2(0, 0), camera);
  return { body, first: () => raycaster.intersectObjects([body, label], true).sort((a, b) => a.distance - b.distance)[0]?.object };
}

describe('raycastWhenShown', () => {
  it('lets a click through a name that gave way to its dot', () => {
    const label = new Mesh(new PlaneGeometry(0.6, 0.2), new MeshBasicMaterial());
    const { body, first } = labelled(label);
    expect(first()).toBe(label);
    label.visible = false;
    expect(first()).toBe(body);
  });

  it('tests a shown name the way its own kind does', () => {
    // Troika's text tests its laid-out block rather than its glyph quads: the kind's own raycast is the one used.
    class Block extends Mesh {
      raycast(_raycaster: Raycaster, intersects: Intersection[]) {
        intersects.push({ distance: 0.1, point: this.position.clone(), object: this } as Intersection);
      }
    }
    const label = new Block(new PlaneGeometry(0.01, 0.01), new MeshBasicMaterial());
    const { first } = labelled(label);
    expect(first()).toBe(label);
  });
});
