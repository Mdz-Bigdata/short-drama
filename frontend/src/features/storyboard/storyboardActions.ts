/** A view the project agent asked the storyboard to open (backend agent tool `open_storyboard_view`). */
export type StoryboardView = 'board' | 'prompt' | 'spatial' | 'desk' | 'blender' | 'packages' | 'sheets' | 'download';

export interface StoryboardViewAction {
  sceneId: string;
  view: StoryboardView;
  /** Bumped per request so asking for the same view twice opens it twice. */
  nonce: number;
}

const VIEWS: ReadonlySet<string> = new Set(['board', 'prompt', 'spatial', 'desk', 'blender', 'packages', 'sheets', 'download']);

interface ToolCall {
  tool?: string;
  result?: { ok?: boolean; result?: { ui_action?: { type?: string; scene_id?: string; view?: string } } };
}

/** The last storyboard view the agent opened in this turn, or null when it opened none. */
export function storyboardActionFrom(toolCalls: unknown, nonce: number): StoryboardViewAction | null {
  if (!Array.isArray(toolCalls)) return null;
  let found: StoryboardViewAction | null = null;
  for (const call of toolCalls as ToolCall[]) {
    const action = call?.result?.ok ? call.result.result?.ui_action : undefined;
    if (action?.type === 'storyboard_view' && action.scene_id && action.view && VIEWS.has(action.view)) {
      found = { sceneId: action.scene_id, view: action.view as StoryboardView, nonce };
    }
  }
  return found;
}
