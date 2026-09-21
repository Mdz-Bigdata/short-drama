import type { LandmarkShape, StageActor, StageLandmark } from '../../spatial/spatialTypes';
import { posePosture } from '../lib/poses';

// How much of a standing body each posture keeps (mirrors the backend's POSTURE_HEIGHT).
export const POSTURE_HEIGHT: Record<string, number> = {
  stand: 1, walk: 1, run: 0.96, fight: 0.94, lean: 0.97, bow: 0.8, sit: 0.74, crouch: 0.6, kneel: 0.68, lie: 0.22,
};
export const ROLE_COLOR: Record<StageActor['role'], string> = { principal: '#00f2fe', supporting: '#9b8af4', crowd: '#5f6b7a' };
export const LANDMARK_COLOR: Record<StageLandmark['kind'], string> = {
  prop: '#f2cc8f', furniture: '#8d99ae', architecture: '#52606d', light: '#ffb454',
};
export const SELECTION_COLOR = '#ffd166';

export const SHAPE_LABELS: Record<LandmarkShape, string> = {
  box: '立方体', cylinder: '圆柱', sphere: '球体', cone: '圆锥', wedge: '楔形', plane: '平面',
};
export const KIND_LABELS: Record<StageLandmark['kind'], string> = {
  prop: '道具', furniture: '家具', architecture: '建筑', light: '灯具',
};

export const BODY_TYPES: Array<{ id: string; label: string }> = [
  { id: 'standard', label: '标准' }, { id: 'slim', label: '纤瘦' }, { id: 'heavy', label: '魁梧' }, { id: 'child', label: '儿童' },
];

const HEX = /^#[0-9a-f]{6}$/i;

export function actorColor(actor: Pick<StageActor, 'color' | 'role'>): string {
  return actor.color && HEX.test(actor.color) ? actor.color : ROLE_COLOR[actor.role];
}

export function landmarkColor(landmark: Pick<StageLandmark, 'color' | 'kind'>): string {
  return landmark.color && HEX.test(landmark.color) ? landmark.color : LANDMARK_COLOR[landmark.kind];
}

/** Mirrors the backend's `posture_height`: a pose preset that implies a posture decides the height before the plan's posture does. */
export function standingHeight(actor: Pick<StageActor, 'height_m' | 'posture' | 'pose'>): number {
  return actor.height_m * (POSTURE_HEIGHT[posePosture(actor.pose?.preset) || actor.posture] ?? 1);
}

export const FIGURE_LABELS: Record<NonNullable<StageActor['figure']>, string> = { standin: '白模柱体', mannequin: '关节人偶', humanoid: '蒙皮人形' };

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch {
    return false;
  }
}
