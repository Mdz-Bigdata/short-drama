import type { StageEasing } from '../../spatial/spatialTypes';

// The menu of camera moves. The list, the defaults and what each parameter means mirror
// backend camera_moves.py, which is the only place a move is actually laid out: the desk asks
// for a preset with `apply_camera_move` and gets ordinary keys back.

export type MoveSide = 'auto' | 'left' | 'right';

export interface CameraMovePreset {
  id: string;
  label: string;
  hint: string;
  /** The move turns about the subject, so `angle` means something. */
  angled?: boolean;
  /** The move goes to one side, so `side` means something. */
  sided?: boolean;
  defaultAngle?: number;
  defaultEasing?: StageEasing;
}

export const CAMERA_MOVES: CameraMovePreset[] = [
  { id: 'push', label: '推近', hint: '沿视线靠近主体' },
  { id: 'pull', label: '拉远', hint: '沿视线后退' },
  { id: 'truck', label: '横移', hint: '平行于画面侧向移动', sided: true },
  { id: 'rise', label: '升', hint: '机位升高，注视点不变' },
  { id: 'descend', label: '降', hint: '机位降低，注视点不变' },
  { id: 'arc', label: '环绕', hint: '绕注视点转过一个角度', angled: true, sided: true },
  { id: 'arc-push', label: '环绕推近', hint: '边环绕边靠近', angled: true, sided: true },
  { id: 'crane-reveal', label: '摇臂揭示', hint: '后退并升起，露出全场' },
  { id: 'ground-rise', label: '贴地升起', hint: '从贴近地面升到当前机位' },
  { id: 'whip-pan', label: '甩镜', hint: '从一侧快速甩到当前画面', angled: true, sided: true, defaultAngle: 60, defaultEasing: 'whip' },
  { id: 'push-pause', label: '推近后停顿', hint: '前六成时间推近，其余停住' },
  { id: 'dolly-zoom', label: '滑动变焦', hint: '靠近的同时拉宽焦距，主体大小不变' },
  { id: 'roll-recover', label: '失衡回正', hint: '从侧偏的位置回到当前画面', sided: true, defaultEasing: 'ease-out' },
  { id: 'reframe', label: '重新构图', hint: '机位不动，注视点移向主体中心' },
];

export const MOVE_EASINGS: StageEasing[] = ['linear', 'smooth', 'ease-in', 'ease-out', 'whip'];
export const SIDE_LABELS: Record<MoveSide, string> = { auto: '自动', left: '向左', right: '向右' };
export const AMPLITUDE_RANGE: [number, number] = [0.05, 3];
export const ANGLE_RANGE: [number, number] = [1, 180];
export const DEFAULT_MOVE_ANGLE = 45;

export function cameraMove(id: string): CameraMovePreset {
  return CAMERA_MOVES.find(item => item.id === id) ?? CAMERA_MOVES[0];
}
