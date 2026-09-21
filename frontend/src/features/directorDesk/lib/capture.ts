import { Color, MeshStandardMaterial, Vector2, Vector3, type Camera, type Material, type Object3D, type PerspectiveCamera, type Scene, type WebGLRenderer } from 'three';

import type { StageActor } from '../../spatial/spatialTypes';
import type { CaptureResult } from '../deskTypes';
import { poseShowsLimbs } from './poses';

export const CAPTURE_LONG_EDGE = 1920;
/** Anything that is there to help the operator, not to be filmed, carries this in `userData`. */
export const HELPER_FLAG = 'deskHelper';

export interface CaptureLabel {
  text: string;
  /** World position the label hangs over (the top of a head). */
  position: [number, number, number];
}

/** A figure the lens may see: where it stands and how tall it is on stage. */
export interface CaptureFigure {
  actor: Pick<StageActor, 'figure' | 'position'>;
  height: number;
}

/**
 * Whether the picture shows a white model with limbs. A video model copies those limbs, so the
 * capture carries the flag to stage 5. A limbed figure behind the lens or out of frame does not count.
 */
export function captureShowsLimbs(figures: CaptureFigure[], camera: Camera, width: number, height: number): boolean {
  return figures.some(({ actor, height: tall }) => poseShowsLimbs(actor)
    && [0.05, 0.5, 0.95].some(fraction => projectToImage([actor.position[0], tall * fraction, actor.position[1]], camera, width, height) !== null));
}

export interface StillRequest {
  gl: WebGLRenderer;
  scene: Scene;
  camera: Camera;
  aspect: number;
  monochrome: boolean;
  labels: CaptureLabel[];
  figures?: CaptureFigure[];
}

/** Delivery pixels: long edge 1920, both sides even (video encoders and most image models want that). */
export function captureSize(aspect: number, longEdge = CAPTURE_LONG_EDGE): { width: number; height: number } {
  const ratio = aspect > 0 && Number.isFinite(aspect) ? aspect : 9 / 16;
  const even = (value: number) => Math.max(2, Math.round(value / 2) * 2);
  return ratio >= 1
    ? { width: even(longEdge), height: even(longEdge / ratio) }
    : { width: even(longEdge * ratio), height: even(longEdge) };
}

/** Where a world point lands in a `width` × `height` image; `null` behind the lens or out of frame. */
export function projectToImage(point: [number, number, number], camera: Camera, width: number, height: number): [number, number] | null {
  const projected = new Vector3(...point).project(camera);
  if (projected.z < -1 || projected.z > 1 || Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1) return null;
  return [((projected.x + 1) / 2) * width, ((1 - projected.y) / 2) * height];
}

export function drawLabels(context: CanvasRenderingContext2D, labels: CaptureLabel[], camera: Camera, width: number, height: number) {
  const size = Math.round(Math.max(width, height) / 60);
  context.font = `600 ${size}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  context.textAlign = 'center';
  context.textBaseline = 'bottom';
  context.lineJoin = 'round';
  labels.forEach(label => {
    const spot = projectToImage(label.position, camera, width, height);
    if (!spot) return;
    context.lineWidth = size / 4;
    context.strokeStyle = 'rgba(4, 7, 13, 0.9)';
    context.strokeText(label.text, spot[0], spot[1]);
    context.fillStyle = '#ffffff';
    context.fillText(label.text, spot[0], spot[1]);
  });
}

export interface RenderSetup {
  gl: WebGLRenderer;
  scene: Scene;
  camera: Camera;
  width: number;
  height: number;
  monochrome: boolean;
}

/**
 * Put the lens canvas into delivery state — helpers hidden, optional single clay colour, drawing
 * buffer at `width` × `height` — and hand back the one call that undoes all of it. The CSS size
 * is never touched, so nothing on the page shows the intermediate size.
 */
export function enterDeliveryRender({ gl, scene, camera, width, height, monochrome }: RenderSetup): { hideHelpers: () => void; restore: () => void } {
  const hidden = new Set<Object3D>();
  const hideHelpers = () => scene.traverse(object => {
    if (object.userData[HELPER_FLAG] && object.visible) {
      object.visible = false;
      hidden.add(object);
    }
  });
  const previousOverride: Material | null = scene.overrideMaterial;
  const clay = monochrome ? new MeshStandardMaterial({ color: new Color('#d8dde3'), roughness: 0.9 }) : null;
  const previousRatio = gl.getPixelRatio();
  const previousSize = gl.getSize(new Vector2());
  const lens = camera as PerspectiveCamera;
  const previousAspect = lens.isPerspectiveCamera ? lens.aspect : 0;

  hideHelpers();
  if (clay) scene.overrideMaterial = clay;
  gl.setPixelRatio(1);
  gl.setSize(width, height, false);
  if (lens.isPerspectiveCamera) {
    lens.aspect = width / height;
    lens.updateProjectionMatrix();
  }

  return {
    hideHelpers,
    restore: () => {
      scene.overrideMaterial = previousOverride;
      clay?.dispose();
      hidden.forEach(object => { object.visible = true; });
      gl.setPixelRatio(previousRatio);
      gl.setSize(previousSize.x, previousSize.y, false);
      if (lens.isPerspectiveCamera) {
        lens.aspect = previousAspect;
        lens.updateProjectionMatrix();
      }
      gl.render(scene, camera);
    },
  };
}

/**
 * One still of what the lens sees, at delivery size. The drawing buffer is resized for a single
 * synchronous render and read back in the same task, so the image has exactly the on-screen
 * look (tone mapping, colour space).
 */
export async function captureStill({ gl, scene, camera, aspect, monochrome, labels, figures = [] }: StillRequest): Promise<CaptureResult> {
  const { width, height } = captureSize(aspect);
  const output = document.createElement('canvas');
  output.width = width;
  output.height = height;
  const context = output.getContext('2d');

  const delivery = enterDeliveryRender({ gl, scene, camera, width, height, monochrome });
  try {
    gl.render(scene, camera);
    if (!context) throw new Error('浏览器无法创建画布，截图失败。');
    context.drawImage(gl.domElement, 0, 0, width, height);
    if (labels.length) drawLabels(context, labels, camera, width, height);
  } finally {
    delivery.restore();
  }

  // The lens canvas already has the delivery aspect, so the restored camera frames what the still does.
  const showsLimbs = captureShowsLimbs(figures, camera, width, height);
  const blob = await new Promise<Blob | null>(resolve => output.toBlob(resolve, 'image/png'));
  if (!blob) throw new Error('截图编码失败，请重试。');
  return { blob, width, height, showsLimbs };
}
