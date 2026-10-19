// Mirrors backend/app/core/spatial_stage/models.py. The plan keeps its snake_case keys on the
// wire (it is one document shared with the storyboard pipeline); only the envelope is camelCase.

export type GroundPoint = [number, number];
export type SpacePoint = [number, number, number];
export type StagePosture = 'stand' | 'walk' | 'run' | 'sit' | 'crouch' | 'kneel' | 'lie' | 'fight' | 'bow' | 'lean';
export type ShotFunction = 'establish' | 'relation' | 'single' | 'over_shoulder' | 'reaction' | 'detail' | 'empty';

export type StageFigure = 'standin' | 'mannequin' | 'humanoid';
export type LandmarkShape = 'box' | 'cylinder' | 'sphere' | 'cone' | 'wedge' | 'plane';
export type StageEasing = 'linear' | 'smooth' | 'ease-in' | 'ease-out' | 'hold' | 'whip';

/** Joint angles in degrees. `preset` names where they came from; `clip` only matters to a humanoid. */
export interface StagePose {
  preset?: string;
  joints?: Record<string, number>;
  clip?: string;
  clip_phase?: number;
}

export interface StageActor {
  id: string;
  name: string;
  position: GroundPoint;
  yaw_deg: number;
  height_m: number;
  posture: StagePosture;
  role: 'principal' | 'supporting' | 'crowd';
  screen_side: 'left' | 'right' | 'center';
  note?: string;
  figure?: StageFigure;
  body_type?: string;
  /** "#rrggbb", or empty for the role colour. */
  color?: string;
  /** Members of one crowd array share it; empty for everyone else. */
  crowd_id?: string;
  pose?: StagePose | null;
}

/** How a crowd array was laid out; its members are ordinary actors that carry `crowd_id`. */
export interface StageCrowd {
  id: string;
  label: string;
  rows: number;
  columns: number;
  spacing: number;
  center: GroundPoint;
  yaw_deg: number;
  body_type: string;
  seed: number;
}

export interface StageLandmark {
  id: string;
  name: string;
  kind: 'prop' | 'furniture' | 'architecture' | 'light';
  position: GroundPoint;
  /** Width (X), depth (Z), height (Y) in metres. */
  size: [number, number, number];
  yaw_deg?: number;
  shape?: LandmarkShape;
  /** "#rrggbb", or empty for the kind colour. */
  color?: string;
  element_id?: string;
}

export type BackdropKind = 'none' | 'color' | 'image' | 'panorama';

/** The scene's reference backdrop. It is drawn in the lens view only and never reaches a prompt. */
export interface StageBackdrop {
  kind: BackdropKind;
  /** "#rrggbb"; kept while another kind shows, so switching back needs no re-pick. */
  color: string;
  /** http(s) only. */
  url: string;
  yaw_deg: number;
  opacity: number;
}

export const NO_BACKDROP: StageBackdrop = { kind: 'none', color: '', url: '', yaw_deg: 0, opacity: 1 };

export interface StageAxis {
  kind: 'dialogue' | 'gaze' | 'motion' | 'none';
  from_name: string;
  to_name: string;
  start: GroundPoint;
  end: GroundPoint;
  camera_side: -1 | 0 | 1;
}

export interface StageCamera {
  id: string;
  label: string;
  position: SpacePoint;
  target: SpacePoint;
  lens_mm: number;
  fov_deg: number;
  aspect: string;
  shot_size: string;
  angle: string;
  function: ShotFunction;
  subjects: string[];
  move: { kind: string; end_position?: SpacePoint | null; end_target?: SpacePoint | null };
}

export interface ScreenState {
  name: string;
  visible: boolean;
  x: number;
  y: number;
  depth_m: number;
  height_fraction: number;
  region: string;
  depth_layer: string;
  facing: string;
  occluded_by: string;
}

export interface ActorOverride {
  name: string;
  position?: GroundPoint | null;
  yaw_deg?: number | null;
  posture?: StagePosture | null;
  offstage?: boolean;
  /** The position holds for the whole shot: the move onto the mark comes in a later shot. */
  hold?: boolean;
  reason?: string;
  pose?: StagePose | null;
}

export interface StageShot {
  shot_id: number;
  camera_id: string;
  /** Extra candidate lenses; `camera_id` stays the one that films. */
  alt_camera_ids?: string[];
  subjects: string[];
  speaker: string;
  action: string;
  overrides: ActorOverride[];
  function: ShotFunction;
  axis_side: -1 | 0 | 1;
  crossing: 'none' | 'neutral' | 'moving' | 'reestablish';
  screen: ScreenState[];
  text: {
    camera_angle: string;
    composition: string;
    action_axis: string;
    eyeline: string;
    blocking: string;
    camera_start: string;
    camera_end: string;
  };
}

export interface StageCheck {
  code: string;
  passed: boolean;
  severity: 'error' | 'warning';
  detail: string;
  shot_ids: number[];
}

export interface CameraKey {
  time: number;
  position: SpacePoint;
  target: SpacePoint;
  lens_mm: number;
  easing: StageEasing;
}

/** A whole-figure key: whatever it leaves out is carried from the key before. */
export interface ActorKey {
  time: number;
  position?: GroundPoint | null;
  yaw_deg?: number | null;
  pose?: StagePose | null;
  easing: StageEasing;
}

export interface ShotTimeline {
  duration_s: number;
  fps: 24 | 25 | 30;
  camera: CameraKey[];
  actors: Record<string, ActorKey[]>;
}

export interface StagePlan {
  version: 1;
  scene_id: string;
  location: string;
  aspect_ratio: string;
  formation: string;
  coverage: 'storyboard' | 'template';
  actors: StageActor[];
  crowds?: StageCrowd[];
  landmarks: StageLandmark[];
  axis: StageAxis;
  /** Absent in a plan stored before the desk had backdrops. */
  backdrop?: StageBackdrop;
  cameras: StageCamera[];
  shots: StageShot[];
  checks: StageCheck[];
  scene_bible: string;
  source: 'auto' | 'edited';
  revision: number;
  /** Keyed by shot id as a string. */
  timelines?: Record<string, ShotTimeline>;
  blockout_standin_limbs?: boolean;
}

export interface SpatialPlanResponse {
  taskId: string;
  sceneId: string;
  persisted: boolean;
  boardStatus: string;
  boardStale: boolean;
  plan: StagePlan;
}

export type StageOperation = { op: string } & Record<string, unknown>;

/** What would put one failing check right. `operations` stay stage operations, so an ordinary PATCH applies them. */
export interface SpatialRepair {
  code: string;
  label: string;
  detail: string;
  shotIds: number[];
  operations: StageOperation[];
  /** Filled in when `automatic` is false: what the person has to decide. */
  manual: string;
  automatic: boolean;
}

export interface SpatialRepairsResponse {
  schemaVersion: string;
  taskId: string;
  sceneId: string;
  /** The plan revision these repairs were worked out on. */
  revision: number;
  /** One per failing check, in `plan.checks` order. */
  repairs: SpatialRepair[];
  /** Every automatic operation, de-duplicated and in order: what「一键修正」sends. */
  operations: StageOperation[];
  automatic: number;
  manual: number;
}

export const FUNCTION_LABELS: Record<ShotFunction, string> = {
  establish: '建立', relation: '关系', single: '单人', over_shoulder: '过肩',
  reaction: '反应', detail: '细节', empty: '空镜',
};

export const POSTURE_LABELS: Record<StagePosture, string> = {
  stand: '站立', walk: '行走', run: '奔跑', sit: '坐', crouch: '蹲伏',
  kneel: '跪', lie: '倒卧', fight: '格斗', bow: '躬身', lean: '倚靠',
};

export const MOVE_LABELS: Record<string, string> = {
  static: '固定', push: '推', pull: '拉', pan: '摇', track: '横移', orbit: '环绕', rise: '升', fall: '降', follow: '跟拍',
};

/** The cast as it stands during one shot: marks with that shot's changes applied, minus whoever is offstage. */
export function actorsInShot(plan: StagePlan, shot: StageShot | undefined): StageActor[] {
  if (!shot) return plan.actors;
  const changes = new Map(shot.overrides.map(item => [item.name, item]));
  return plan.actors.flatMap(actor => {
    const change = changes.get(actor.name);
    if (!change) return [actor];
    if (change.offstage) return [];
    return [{
      ...actor,
      position: change.position ?? actor.position,
      yaw_deg: change.yaw_deg ?? actor.yaw_deg,
      posture: change.posture ?? actor.posture,
      pose: change.pose ?? actor.pose,
    }];
  });
}
