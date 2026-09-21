import type { Camera, Scene, WebGLRenderer } from 'three';

import type { SpacePoint, StageOperation } from '../spatial/spatialTypes';
import type { CaptureFigure, CaptureLabel } from './lib/capture';

export type DeskTool = 'select' | 'move' | 'rotate' | 'scale' | 'pose' | 'measure';
export type DeskLayout = 'director' | 'split' | 'lens';

/** `camera-target` is the look-at handle of a rig: it selects and drags on its own. */
export type SelectionRef =
  | { kind: 'actor'; name: string }
  | { kind: 'landmark'; name: string }
  | { kind: 'crowd'; id: string }
  | { kind: 'camera'; id: string }
  | { kind: 'camera-target'; id: string };

export function refKey(ref: SelectionRef): string {
  return `${ref.kind}:${'name' in ref ? ref.name : ref.id}`;
}

export interface SnapSettings {
  grid: boolean;
  gridSize: number;
  faces: boolean;
  angle: boolean;
}

export interface MeasurePoint {
  label: string;
  point: SpacePoint;
}

export interface GuideSettings {
  /** '' follows the delivery aspect of the plan. */
  aspect: string;
  frame: boolean;
  thirds: boolean;
  safe: boolean;
  cross: boolean;
}

export interface ViewPose {
  position: SpacePoint;
  target: SpacePoint;
}

export interface CaptureOptions {
  monochrome: boolean;
  labels: boolean;
}

export interface CaptureResult {
  blob: Blob;
  width: number;
  height: number;
  /** A limbed white model is in the picture. */
  showsLimbs: boolean;
}

/** Who is in front of the lens at one instant: what burned-in names and the limbs flag are worked out from. */
export interface LensFrameInfo {
  labels: CaptureLabel[];
  figures: CaptureFigure[];
}

export interface LensHandle {
  capture: (options: CaptureOptions) => Promise<CaptureResult>;
  /** The lens canvas itself, for a clip export to render into. */
  renderer: () => { gl: WebGLRenderer; scene: Scene; camera: Camera };
}

export interface DeskViewHandle {
  viewPose: () => ViewPose;
}

export interface EditRequest {
  operations: StageOperation[];
  label: string;
  /** Sent alone: its inverse can only be read off the plan the server returns (new ids). */
  barrier?: boolean;
  /** Cannot be taken back (the server would not rebuild the same thing). */
  irreversible?: boolean;
}
