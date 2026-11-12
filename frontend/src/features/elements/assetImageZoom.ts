/** 位置都是舞台宽高的百分比。 */
export interface ViewPoint {
  x: number;
  y: number;
}

/**
 * 查看器的画面：图按 ``zoom`` 倍绕 ``origin`` 放大；``focus`` 是正在看的那一点在原图上的位置。
 */
export interface ImageView {
  zoom: number;
  origin: ViewPoint;
  focus: ViewPoint;
}

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 4;
export const ZOOM_STEP = 0.5;
export const INITIAL_VIEW: ImageView = { zoom: MIN_ZOOM, origin: { x: 50, y: 50 }, focus: { x: 50, y: 50 } };

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

// 倍数不取整：触控板一次只走千分之几，取整会把每一步都吃掉，慢慢滚就永远不动。
function clampZoom(value: number): number {
  return clamp(value, MIN_ZOOM, MAX_ZOOM);
}

/** 指针底下是原图的哪一点：放大后，屏幕上的位置不等于图上的位置。 */
export function imagePointAt(view: ImageView, pointer: ViewPoint): ViewPoint {
  return {
    x: view.origin.x + (pointer.x - view.origin.x) / view.zoom,
    y: view.origin.y + (pointer.y - view.origin.y) / view.zoom,
  };
}

/** 不指定位置的缩放(按钮、键盘)：绕当前中心。 */
export function zoomBy(view: ImageView, delta: number): ImageView {
  return { ...view, zoom: clampZoom(view.zoom + delta) };
}

/** 把指针下的那一点设成中心：倍数已经到头时，点一下就是"看这里"。 */
export function centreOn(view: ImageView, pointer: ViewPoint): ImageView {
  const focus = imagePointAt(view, pointer);
  return { zoom: view.zoom, origin: focus, focus };
}

/** 以指针下的那一点为准缩放：缩放前后它都留在指针底下。 */
export function zoomAtPointer(view: ImageView, pointer: ViewPoint, nextZoom: number): ImageView {
  const zoom = clampZoom(nextZoom);
  const focus = imagePointAt(view, pointer);
  if (zoom <= MIN_ZOOM) return { zoom, origin: focus, focus };
  // 倍数没变(滚到头了)：画面不动，只记下正在看哪一点。
  if (zoom === view.zoom) return { ...view, focus };
  // 中心收在图内，放大后的图才始终盖满舞台，不露空边。
  const anchor = (image: number, screen: number) => clamp((image * zoom - screen) / (zoom - 1), 0, 100);
  return { zoom, origin: { x: anchor(focus.x, pointer.x), y: anchor(focus.y, pointer.y) }, focus };
}

/** 滚轮一格约 100，触控板双指和捏合是一串小数值：按位移连续缩放，不按次数跳档。 */
export function wheelZoomFactor(deltaY: number, pinch: boolean): number {
  return Math.exp(-deltaY * (pinch ? 0.01 : 0.0015));
}
