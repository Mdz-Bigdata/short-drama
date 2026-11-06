export type NodeKind =
  | 'artifact' | 'candidate' | 'media' | 'note' | 'group'
  | 'image_gen' | 'video_gen' | 'audio_gen' | 'video_compose' | 'style_ref' | 'panorama' | 'previz' | 'tool';

export type Medium = 'image' | 'video' | 'audio';
export type OutputType = Medium | 'text' | 'style' | 'capture';
export type EdgeKind = 'lineage' | 'variant' | 'continuity' | 'dependency' | 'reference';

export interface NodeOutput {
  /** 'text' is a tool's written result: it has `text` and an empty `url`. */
  medium: Medium | 'text';
  url: string;
  text?: string;
  beats?: Array<{ title: string; prompt: string }>;
  /** `text` is a whole HTML page: shown in a sandboxed frame, never as markup of this page. */
  html?: boolean;
  /** How well a continued clip opens on the frame it was handed: good / suspect / jump. */
  seam?: { score: number; verdict: 'good' | 'suspect' | 'jump'; label: string; detail: string };
  filename?: string;
  remote?: boolean;
  run_id?: string;
  provenance?: Record<string, unknown>;
}

export interface NodeParams {
  model?: string;
  durationSeconds?: number;
  size?: string;
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
  models: { image: string; video: string; audio: string };
  enabled: { image: string[]; video: string[]; audio: string[] };
  video_durations: number[];
  camera_recipes?: Array<{ value: string; label: string; purpose: string }>;
  kinds: Record<string, { runnable: boolean; reason: string; modes?: Record<string, boolean> }>;
}

export interface ProjectShot {
  scene_id: string;
  shot_id: number;
  shot_uid?: number;
  desc: string;
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
