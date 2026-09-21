import type { SpatialPlanResponse, StagePlan } from './spatialTypes';

const TEXT = {
  camera_angle: '平视', composition: '全景，28mm；林夏位于画面左侧三分之一的中景，朝向画面右侧',
  action_axis: '关系轴线为林夏—周教授连线；林夏恒在画左、周教授恒在画右', eyeline: '林夏视线朝向画面右侧',
  blocking: '林夏（站立）与周教授（站立）相距2.6米面对面', camera_start: '位于林夏右前方3.4米、机高1.5米，28mm，平视', camera_end: '固定机位，机位不变',
};

export const PLAN: StagePlan = {
  version: 1,
  scene_id: 'E1S01',
  location: '办公室',
  aspect_ratio: '9:16',
  formation: '面对面·对峙·相距2.6米',
  coverage: 'storyboard',
  actors: [
    { id: 'actor-01', name: '林夏', position: [-1.3, 0], yaw_deg: 90, height_m: 1.7, posture: 'stand', role: 'principal', screen_side: 'left' },
    { id: 'actor-02', name: '周教授', position: [1.3, 0], yaw_deg: -90, height_m: 1.7, posture: 'stand', role: 'principal', screen_side: 'right' },
    { id: 'actor-03', name: '助手', position: [0, -2.3], yaw_deg: 0, height_m: 1.7, posture: 'stand', role: 'supporting', screen_side: 'center' },
  ],
  landmarks: [{ id: 'mark-01', name: '录音笔', kind: 'prop', position: [0, -0.9], size: [0.5, 0.5, 0.5] }],
  axis: { kind: 'dialogue', from_name: '林夏', to_name: '周教授', start: [-1.3, 0], end: [1.3, 0], camera_side: 1 },
  cameras: [
    { id: 'cam-01', label: '01 建立', position: [0, 1.45, 5.2], target: [0, 0.9, 0], lens_mm: 28, fov_deg: 65.5, aspect: '9:16', shot_size: '全景', angle: '平视', function: 'establish', subjects: ['林夏', '周教授'], move: { kind: 'static' } },
    { id: 'cam-02', label: '02 单人', position: [0.2, 1.58, 0.9], target: [-1.3, 1.45, 0], lens_mm: 65, fov_deg: 31, aspect: '9:16', shot_size: '近景', angle: '平视', function: 'single', subjects: ['林夏'], move: { kind: 'push', end_position: [-0.2, 1.55, 0.65], end_target: [-1.3, 1.45, 0] } },
  ],
  shots: [
    { shot_id: 1, camera_id: 'cam-01', subjects: ['林夏', '周教授'], speaker: '', action: '两人对峙', overrides: [], function: 'establish', axis_side: 1, crossing: 'reestablish', screen: [], text: TEXT },
    { shot_id: 2, camera_id: 'cam-02', subjects: ['林夏'], speaker: '林夏', action: '林夏盯着对面', overrides: [{ name: '助手', offstage: true, reason: '已退下' }], function: 'single', axis_side: 1, crossing: 'none', screen: [], text: { ...TEXT, composition: '近景，65mm；林夏位于画面中央的中景，朝向画面右侧' } },
  ],
  checks: [
    { code: 'spatial_axis_consistent', passed: true, severity: 'error', detail: '全部机位守在轴线同一侧，或经合法的桥接镜头换边。', shot_ids: [] },
    { code: 'spatial_subject_occlusion', passed: false, severity: 'warning', detail: '第2镜的林夏被助手挡住，请错开站位或换机位。', shot_ids: [2] },
  ],
  scene_bible: '【空间圣经】办公室',
  source: 'auto',
  revision: 3,
};

export function planResponse(overrides: Partial<SpatialPlanResponse> = {}, plan: Partial<StagePlan> = {}): SpatialPlanResponse {
  return { taskId: 't1', sceneId: 'E1S01', persisted: true, boardStatus: 'done', boardStale: false, plan: { ...PLAN, ...plan }, ...overrides };
}
