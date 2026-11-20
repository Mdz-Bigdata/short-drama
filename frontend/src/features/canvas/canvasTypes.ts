export type NodeKind =
  | 'artifact' | 'candidate' | 'media' | 'note' | 'group'
  | 'image_gen' | 'video_gen' | 'audio_gen' | 'video_compose' | 'style_ref' | 'panorama' | 'previz' | 'tool';

export type Medium = 'image' | 'video' | 'audio';

/** One row of a shot table (the 拆镜头表 tool). */
export interface TableShot {
  size: string;
  motion: string;
  seconds: number;
  desc: string;
  /** Who is in the shot (absent from tables made before it was asked for). */
  characters?: string[];
  /** 「人物名：对白」 lines. */
  dialogue: string;
  /** 日 / 夜 / 黄昏 / 清晨, from the scene heading (absent from older tables). */
  time?: string;
}

/** A character a shot table describes. */
export interface TableCast {
  name: string;
  look: string;
  /** The words for a look sheet of them alone; only characters seen in more than one shot have one. */
  sheet_prompt?: string;
}
export type OutputType = Medium | 'text' | 'style' | 'capture';
export type EdgeKind = 'lineage' | 'variant' | 'continuity' | 'dependency' | 'reference';

export interface NodeOutput {
  /** 'text' is a tool's written result: it has `text` and an empty `url`. */
  medium: Medium | 'text';
  url: string;
  text?: string;
  beats?: Array<{ title: string; prompt: string }>;
  /** A shot table's rows, whole: what 铺成镜头 turns into a first frame feeding a video node per shot. */
  shots?: TableShot[];
  /** The shot table's characters and their looks. */
  cast?: TableCast[];
  /** How many shots the table was asked for, when it was asked for a number. */
  asked?: number;
  /** Lines the model placed out of the script's order. */
  line_order?: string[];
  /** `text` is a whole HTML page: shown in a sandboxed frame, never as markup of this page. */
  html?: boolean;
  /** 抠像序列帧: the ZIP of same-sized transparent frames; `url` is its sprite sheet (the first frame when there is no sheet). */
  zip?: string;
  /** What that ZIP holds, as its manifest says. */
  sprite?: { frame_width: number; frame_height: number; count: number; fps: number; sheet: { columns: number; rows: number } | null };
  /** How well a continued clip opens on the frame it was handed: good / suspect / jump. */
  seam?: { score: number; verdict: 'good' | 'suspect' | 'jump'; label: string; detail: string };
  filename?: string;
  /** An uploaded clip a browser may not play (H.265, 10-bit): its H.264 copy for watching; runs read `url`. */
  preview_url?: string;
  remote?: boolean;
  run_id?: string;
  provenance?: Record<string, unknown>;
}

export interface NodeParams {
  model?: string;
  durationSeconds?: number;
  size?: string;
  /** Picture and clip nodes: how many results one run makes (the server caps it). */
  count?: number;
  mode?: 'speech' | 'music' | 'sfx';
  gender?: 'male' | 'female';
  /** Tool nodes: which tool, the look picked on the style wall, and that tool's own settings. */
  tool?: string;
  style?: string;
  [key: string]: unknown;
}

export interface ShotBinding {
  sceneId?: string;
  shotId?: number | null;
}

export interface NodePayload {
  label?: string;
  title?: string;
  text?: string;
  prompt?: string;
  styleText?: string;
  params?: NodeParams;
  output?: NodeOutput;
  medium?: Medium;
  groupId?: string;
  binding?: ShotBinding;
  /** Previz only: the shot the desk opens on, and which of its captures this node hands on. */
  sceneId?: string;
  shotId?: number | null;
  selectedCaptureIds?: string[];
  committed?: { marker?: string; artifact_id?: string; shots?: number };
  [key: string]: unknown;
}

export interface CanvasNode {
  id: string;
  kind: NodeKind;
  track: 'mainline' | 'freezone';
  x: number;
  y: number;
  width: number;
  height: number;
  artifact_id: string | null;
  payload: NodePayload;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  payload: { role?: string; [key: string]: unknown };
}

export interface CanvasDoc {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface CanvasRecord extends CanvasDoc {
  project_id: string;
  version: number;
  created_at: string;
  canvas_id?: string;
}

export interface Viewport {
  /** Screen position of the world origin. */
  x: number;
  y: number;
  zoom: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Bookmark {
  slot: number;
  x: number;
  y: number;
  zoom: number;
  label?: string;
}

export interface CanvasBoard {
  id: string;
  project_id: string;
  title: string;
  bookmarks: Bookmark[];
  version: number;
}

export interface CanvasVersion {
  version: number;
  created_at: string;
  node_count: number;
  edge_count: number;
}

export type RunStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'skipped';

export interface NodeRun {
  id: string;
  node_id: string;
  batch_id: string;
  medium: Medium;
  status: RunStatus;
  model: string;
  request: { prompt?: string; requested_seconds?: number };
  output: NodeOutput | null;
  error: string | null;
  created_at: string;
}

export interface NodeHistory {
  node_id: string;
  active_run_id: string | null;
  runs: NodeRun[];
}

export interface LatestRun {
  run_id: string;
  status: RunStatus;
  error: string | null;
  batch_id: string;
  /** Present when the last order asked for several results: how many, and how they ended so far. */
  versions?: { total: number; done: number; failed: number };
}

export interface CanvasOutputs {
  version: number;
  outputs: Record<string, NodeOutput>;
  latest: Record<string, LatestRun>;
  history_counts: Record<string, number>;
  running: number;
}

export interface RunProblem {
  code: string;
  message: string;
  blocking: boolean;
}

export interface Estimate {
  priced: boolean;
  cost: number | null;
  currency: string | null;
}

export interface AssessedNode {
  node_id: string;
  kind: NodeKind;
  label: string;
  medium: Medium | null;
  model: string;
  quote: 'generate' | 'blocked';
  paid: boolean;
  problems: RunProblem[];
  requested_seconds: number;
  scripted_seconds: number;
  estimate: Estimate;
  /** How many results the run makes; the estimate covers all of them. */
  versions?: number;
}

export interface TierConfirmation {
  scripted_seconds: number;
  requested_seconds: number;
  shot_count: number;
}

export interface RunAssessment {
  decision: 'admitted' | 'confirmation_required' | 'blocked';
  nodes: AssessedNode[];
  confirmations: TierConfirmation[];
  estimate: { items: number; paid_items: number; unpriced_items: number; totals: Array<{ currency: string; cost: number }> };
}

export interface RunStart {
  status: 'started' | 'blocked' | 'needs_confirmation';
  batch_id?: string;
  reused?: boolean;
  assessment?: RunAssessment;
}

export interface StyleLook {
  id: string;
  group: string;
  names: Record<string, string>;
  prompt: string;
  swatch: [string, string];
}

export interface RunOptions {
  /** Absent when talking to a server from before the tool node. */
  tools?: {
    styles: StyleLook[];
    engines: { image: boolean; vision: boolean; text: boolean; local: boolean; voice: boolean };
  };
  /** `text` is absent when talking to a server from before text models could be picked on the canvas. */
  models: { image: string; video: string; audio: string; text?: string };
  enabled: { image: string[]; video: string[]; audio: string[]; text?: string[] };
  video_durations: number[];
  /** Absent when talking to a server from before several results per run. */
  versions?: { max: number; kinds: string[] };
  camera_recipes?: Array<{ value: string; label: string; purpose: string }>;
  kinds: Record<string, { runnable: boolean; reason: string; modes?: Record<string, boolean> }>;
}

export interface ProjectShot {
  scene_id: string;
  shot_id: number;
  shot_uid?: number;
  desc: string;
}

/** One storyboard scene, as the "lay the storyboard out" picker lists it: `new` shots are not on this canvas yet. */
export interface StoryboardScene {
  scene_id: string;
  shots: number;
  new: number;
}

export interface StoryboardLayout {
  applied: boolean;
  shots: number;
  skipped: number;
  frames_to_draw: number;
  cast: number;
  scenes: string[];
  version?: number;
  node_ids?: string[];
}

export interface CommitRow {
  node_id: string;
  label: string;
  kind: NodeKind;
  medium: Medium | null;
  url: string | null;
  target_kind: string | null;
  impact: { count: number; shots: Array<{ scene_id: string; shot_id: number; desc: string }> };
  state: 'ready' | 'no_provenance' | 'already' | 'no_result';
  reason: string;
  applies_to_shots: boolean;
}

export interface CommitPreview {
  version: number;
  nodes: CommitRow[];
  counts: { ready: number; no_provenance: number; already: number; no_result: number };
  impacted_shots: number;
}

export interface CommitResult {
  version: number;
  canvas: CanvasRecord | null;
  results: Array<{ node_id: string; label: string; status: 'committed' | 'failed' | 'skipped'; state?: string; reason?: string; applied_shots?: number }>;
  counts: { committed: number; failed: number; skipped: number; no_provenance: number };
}
