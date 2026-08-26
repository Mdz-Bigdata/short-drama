export type PromptValue = string | number | boolean | null | undefined | PromptValue[] | { [key: string]: PromptValue };

export interface StoryboardTimeBeat {
  index: number;
  page_number: number;
  page_slot: number;
  start_seconds: number;
  keyframe_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  action_phase: string;
  core_event: string;
  start_state: string;
  keyframe_state: string;
  end_state: string;
  character_pose: string;
  subject_dynamics: string;
  secondary_dynamics: string;
  camera_state: string;
  color_state: string;
  change_from_previous: string;
  verbatim_line?: string;
  environmental_sound: string;
  linkage: string;
}

export interface StoryboardPromptDetail {
  project_name: string;
  episode: string;
  scene_number: number;
  shot_number: string;
  duration_seconds: number;
  aspect_ratio: string;
  fps: number;
  grid_spec: string;
  foundation: {
    shot_information?: Record<string, PromptValue>;
    narrative_goal?: string;
    script_text?: string;
    characters?: Array<Record<string, PromptValue>>;
    scene_and_props?: Record<string, PromptValue>;
    verbatim_dialogue?: Array<Record<string, PromptValue>>;
    global_visual_rules?: Record<string, PromptValue>;
    continuity_locks?: Record<string, PromptValue>;
    shot_visual_design?: Record<string, PromptValue>;
    color_design?: Record<string, PromptValue>;
    dynamics_design?: Record<string, PromptValue>;
    camera_design?: Record<string, PromptValue>;
    transition_design?: Record<string, PromptValue>;
  };
  beats: StoryboardTimeBeat[];
  still_prompts: Array<Record<string, PromptValue>>;
  video_segments: Array<Record<string, PromptValue>>;
  grid_pages: Array<Record<string, PromptValue>>;
  continuity_checks: Array<Record<string, PromptValue>>;
  submission_ready?: boolean;
  warnings?: string[];
}
