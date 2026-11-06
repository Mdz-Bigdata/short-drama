export type Scalar = number | boolean;
export type CompareOp = 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte';

export interface Comparison { var: string; op: CompareOp; value: Scalar }
export type Condition = { all: Condition[] } | { any: Condition[] } | Comparison;

export interface StoryVariable {
  id: string;
  label: string;
  kind: 'number' | 'flag';
  initial: Scalar | null;
  min: number | null;
  max: number | null;
}

export interface StoryEffect { var: string; op: 'add' | 'set'; value: Scalar }

export interface StoryChoice {
  id: string;
  text: string;
  target: string | null;
  condition: Condition | null;
  when_locked: 'hide' | 'lock';
  locked_hint: string;
  effects: StoryEffect[];
}

export interface StoryRoute { id: string; condition: Condition | null; target: string | null }
export interface StoryTimer { seconds: number; default_choice: string }

export type MediaSource = 'shot' | 'clip' | 'episode' | 'upload';
export interface StoryMedia {
  kind: 'video' | 'image';
  url: string;
  source: MediaSource;
  shot_uid: number | null;
  label: string;
  duration_s: number;
}

export interface DialogueLine { speaker: string; text: string }
export interface Point { x: number; y: number }

export interface StorySegment {
  id: string;
  title: string;
  kind: 'scene' | 'ending';
  narration: string;
  dialogue: DialogueLine[];
  media: StoryMedia | null;
  est_seconds: number | null;
  ending_label: string;
  timer: StoryTimer | null;
  choices: StoryChoice[];
  routes: StoryRoute[];
  position: Point | null;
}

export interface StoryGraph {
  title: string;
  synopsis: string;
  outline: string[];
  start: string;
  variables: StoryVariable[];
  segments: StorySegment[];
}

export interface StoryIssue {
  code: string;
  severity: 'error' | 'warning';
  message: string;
  segment_id?: string;
  segment_ids?: string[];
  choice_id?: string;
  route_id?: string;
  variable_id?: string;
  params?: Record<string, string | number>;
}

export interface EndingRow {
  id: string;
  title: string;
  label: string;
  paths: number;
  reach_rate: number;
  min_minutes: number | null;
  max_minutes: number | null;
  avg_minutes: number | null;
}

export interface RouteRow {
  key: string;
  ending_id: string;
  segments: string[];
  choices: string[];
  seconds: number;
  minutes: number;
  probability: number;
}

export interface PathAnalysis {
  paths: number;
  complete_paths: number;
  stuck_paths: number;
  loop_cuts: number;
  truncated: boolean;
  max_paths: number;
  loop_limit: number;
  rate_method: 'enumeration' | 'simulation';
  coverage: {
    segments_covered: number; segments_total: number; segments_ratio: number;
    choices_covered: number; choices_total: number; choices_ratio: number;
    endings_covered: number; endings_total: number; endings_ratio: number;
  };
  endings: EndingRow[];
  unfinished_rate: number;
  minutes: { min: number | null; max: number | null; avg: number | null };
  routes: RouteRow[];
  stuck: Array<{ segment_id: string; values: Record<string, Scalar> }>;
}

export interface StoryAnalysis {
  issues: StoryIssue[];
  errors: number;
  warnings: number;
  ready: boolean;
  paths: PathAnalysis;
}

export interface PlaytestStats {
  runs: number;
  completed: number;
  timeouts: number;
  choices: Array<{ segment_id: string; segment: string; choice_id: string; text: string; count: number; share: number }>;
  endings: Array<{ id: string; title: string; count: number }>;
  endings_reached: number;
  endings_total: number;
  segments_played: number;
  segments_total: number;
  routes_played: number;
  routes_total: number;
  route_coverage: number;
}

export interface StoryRecord {
  revision: number;
  graph: StoryGraph | null;
  updated_at: string;
  analysis: StoryAnalysis | null;
  stats: PlaytestStats | null;
}

export interface LibraryShot {
  shot_id: number;
  shot_uid: number;
  scene_id: string;
  desc: string;
  image_url: string | null;
  video_url: string | null;
  candidate_urls: string[];
  duration_s: number;
  stale: boolean;
}

export interface LibraryUpload {
  id: string;
  kind: 'video' | 'image';
  url: string;
  label: string;
  size: number;
  duration_s: number;
}

export interface MediaLibrary {
  shots: LibraryShot[];
  films: Array<{ label: string; video_url: string }>;
  uploads: LibraryUpload[];
}

export interface ExportPreview {
  ready: boolean;
  errors: StoryIssue[];
  media: Array<{ segment_id: string; title: string; kind: 'video' | 'image'; status: 'local' | 'remote' | 'expired' | 'missing'; size: number }>;
  inline_limit_bytes: number;
}

export interface PlanDraft {
  draft: StoryGraph;
  analysis: StoryAnalysis;
  attempts: number;
}

export interface PlaytestRun {
  steps: Array<{ segment: string; choice: string | null }>;
  ending: string | null;
  from_start: boolean;
  timeouts: number;
}

export type Selection = { kind: 'segment'; id: string } | { kind: 'edge'; segment: string; edge: string } | null;
