export const EDITOR_MIN_WIDTH = 360;
export const EDITOR_MIN_HEIGHT = 200;
export const EDITOR_NUDGE = 16;

/** The editor's opening size: min(1200px, 92vw) wide, 60vh tall but never under the minimum. */
export function defaultEditorSize(viewport = { width: window.innerWidth, height: window.innerHeight }) {
  return {
    width: Math.max(EDITOR_MIN_WIDTH, Math.min(1200, Math.round(viewport.width * 0.92))),
    height: Math.max(EDITOR_MIN_HEIGHT, Math.round(viewport.height * 0.6)),
  };
}

/** A size kept inside the window and above the minimum. */
export function clampEditorSize(size: { width: number; height: number }, viewport = { width: window.innerWidth, height: window.innerHeight }) {
  return {
    width: Math.round(Math.min(viewport.width - 16, Math.max(EDITOR_MIN_WIDTH, size.width))),
    height: Math.round(Math.min(viewport.height - 120, Math.max(EDITOR_MIN_HEIGHT, size.height))),
  };
}
