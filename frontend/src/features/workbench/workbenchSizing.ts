export const WORKBENCH_SIDEBAR_DEFAULT_WIDTH = 380;
export const WORKBENCH_SIDEBAR_MIN_WIDTH = 300;
export const WORKBENCH_SIDEBAR_MAX_WIDTH = 700;
export const WORKBENCH_MAIN_MIN_WIDTH = 560;

export function workbenchSidebarMaximum(containerWidth: number) {
  return Math.max(
    WORKBENCH_SIDEBAR_MIN_WIDTH,
    Math.min(WORKBENCH_SIDEBAR_MAX_WIDTH, containerWidth - WORKBENCH_MAIN_MIN_WIDTH),
  );
}

export function clampWorkbenchSidebarWidth(width: number, containerWidth: number) {
  const maximum = workbenchSidebarMaximum(containerWidth);
  return Math.round(Math.min(maximum, Math.max(WORKBENCH_SIDEBAR_MIN_WIDTH, width)));
}
