/**
 * 白模站位图的排版：把服务器给的一幅站位图（人物、陈设、机位、走位，单位都是米）
 * 算成一张 16:9 画面里的图元。纯计算，不碰 DOM，画法在 BlockingDiagramDialog 里。
 *
 * 视角只有一个量：从地面往上看的仰角 tilt。90° 是正上方的平面图，45° 是斜俯视，
 * 越小越接近平视。x 向右，z 向画面下方（近处），高度 y 把点往上抬。
 */

export interface DiagramFigure {
  name: string;
  extra: boolean;
  role: string;
  color: string;
  position: [number, number];
  yaw_deg: number;
  posture: string;
  posture_label: string;
  height_m: number;
  start: [number, number] | null;
  /** 脚边的短标签：闪避、格挡、腾空、受击… 普通站位没有。 */
  acts?: string[];
}

export interface DiagramPiece {
  name: string;
  kind: string;
  shape: string;
  position: [number, number];
  size: [number, number, number];
  yaw_deg: number;
  elevation_m: number;
}

export interface DiagramCamera {
  id: string;
  label: string;
  position: [number, number];
  true_position: [number, number];
  height_m: number;
  far_m: number;
  target: [number, number];
  lens_mm: number;
  fov_deg: number;
  subjects: string[];
  focus: string;
  color: string;
  shot_ids: number[];
  candidate: boolean;
  move: string;
  move_label: string;
  end_position: [number, number] | null;
}

export interface DiagramRoute {
  name: string;
  color: string;
  points: Array<[number, number]>;
  meters: number;
  order: number;
  /** walk 之外的走位（闪避、被击退、腾空落点）带一个短说明。 */
  kind?: string;
  label?: string;
}

/** 一次出手：从出手的一侧到接触点；被打的人有受击反应时再给一段受力方向。 */
export interface DiagramStrike {
  attacker: string;
  target: string;
  kind: string;
  short: string;
  label: string;
  color: string;
  from: [number, number];
  to: [number, number];
  meters: number;
  shot_id: number;
  at_s: number | null;
  source: string;
  source_label: string;
  force_to: [number, number] | null;
  reaction: string;
}

/** 特效占位：圆心、占位半径、圈数；from 是发出它的人所在的位置。 */
export interface DiagramEffect {
  id: string;
  kind: string;
  name: string;
  center: [number, number];
  radius_m: number;
  rings: number;
  from: [number, number] | null;
  source: string;
  inside: string[];
  color: string;
}

export interface DiagramDistance {
  a: string;
  b: string;
  meters: number;
  from: [number, number];
  to: [number, number];
}

export interface DiagramNode {
  shot_id: number;
  at_s: number | null;
  end_s: number | null;
  name: string;
  what: string;
  source: string;
}

export interface LegendRow {
  mark: string;
  meaning: string;
  color: string;
  where: string;
}

export interface BlockingDiagram {
  index: number;
  total: number;
  shot_ids: number[];
  title: string;
  view: string;
  figures: DiagramFigure[];
  pieces: DiagramPiece[];
  cameras: DiagramCamera[];
  routes: DiagramRoute[];
  bounds: [number, number, number, number];
  notes: string[];
  prompt: string;
  /** staging / action / vfx；只有 staging 就是普通站位图。 */
  modes?: string[];
  mode_label?: string;
  strikes?: DiagramStrike[];
  effects?: DiagramEffect[];
  distances?: DiagramDistance[];
  nodes?: DiagramNode[];
  legend?: LegendRow[];
}

export interface DiagramView {
  id: string;
  label: string;
  tilt_deg: number;
}

export interface BlockingDiagramSeries {
  task_id: string;
  scene_id: string;
  location: string;
  revision: number;
  persisted: boolean;
  view: string;
  views: DiagramView[];
  grid: { cell_m: number; major_every: number };
  colors: Array<{ name: string; hex: string; color_name: string }>;
  extra_color: string;
  diagrams: BlockingDiagram[];
}

export const DIAGRAM_WIDTH = 1600;
export const DIAGRAM_HEIGHT = 900;
const MARGIN_X = 70;
const MARGIN_TOP = 150;
const MARGIN_BOTTOM = 80;
/** Room kept above the tallest figure for its name tag, in metres of height. */
const HEADROOM_M = 2.4;

export type Point = [number, number];

export interface Projection {
  scale: number;
  tilt: number;
  /** Ground point (x, z) lifted by `y` metres → picture pixels. */
  at: (x: number, z: number, y?: number) => Point;
  /** How tall one metre of height is on the picture, in pixels. */
  rise: number;
  /** How deep one metre of floor depth is on the picture, in pixels. */
  run: number;
}

export function projectionFor(bounds: [number, number, number, number], tiltDeg: number, width = DIAGRAM_WIDTH, height = DIAGRAM_HEIGHT): Projection {
  const tilt = (Math.min(90, Math.max(8, tiltDeg)) * Math.PI) / 180;
  const sin = Math.sin(tilt);
  const cos = Math.cos(tilt);
  const [lowX, lowZ, highX, highZ] = bounds;
  const spanX = Math.max(1, highX - lowX);
  const spanY = Math.max(1, (highZ - lowZ) * sin + HEADROOM_M * cos);
  const scale = Math.min((width - MARGIN_X * 2) / spanX, (height - MARGIN_TOP - MARGIN_BOTTOM) / spanY);
  const offsetX = (width - spanX * scale) / 2 - lowX * scale;
  // The far edge's raised headroom sits at the top of the drawing area; a short floor is centred in it.
  const used = spanY * scale;
  const top = MARGIN_TOP + (height - MARGIN_TOP - MARGIN_BOTTOM - used) / 2;
  const offsetY = top + HEADROOM_M * cos * scale - lowZ * sin * scale;
  return {
    scale,
    tilt,
    rise: cos * scale,
    run: sin * scale,
    at: (x, z, y = 0) => [offsetX + x * scale, offsetY + z * sin * scale - y * cos * scale],
  };
}

export interface GridLine {
  from: Point;
  to: Point;
  major: boolean;
}

export function gridLines(bounds: [number, number, number, number], projection: Projection, majorEvery = 5): GridLine[] {
  const [lowX, lowZ, highX, highZ] = bounds;
  const lines: GridLine[] = [];
  for (let x = Math.ceil(lowX); x <= Math.floor(highX); x += 1) {
    lines.push({ from: projection.at(x, lowZ), to: projection.at(x, highZ), major: x % majorEvery === 0 });
  }
  for (let z = Math.ceil(lowZ); z <= Math.floor(highZ); z += 1) {
    lines.push({ from: projection.at(lowX, z), to: projection.at(highX, z), major: z % majorEvery === 0 });
  }
  return lines;
}

const radians = (degrees: number) => (degrees * Math.PI) / 180;

/** Unit vector a yaw faces: 0° is +z (the near edge), +90° is +x. Matches the server's convention. */
export function forwardOf(yawDeg: number): Point {
  return [Math.sin(radians(yawDeg)), Math.cos(radians(yawDeg))];
}

const rightOf = (forward: Point): Point => [-forward[1], forward[0]];

export function footprint(piece: Pick<DiagramPiece, 'position' | 'size' | 'yaw_deg'>): Point[] {
  const forward = forwardOf(piece.yaw_deg);
  const right = rightOf(forward);
  const halfW = piece.size[0] / 2;
  const halfD = piece.size[1] / 2;
  return ([[-1, -1], [1, -1], [1, 1], [-1, 1]] as Point[]).map(([sx, sz]) => [
    piece.position[0] + right[0] * sx * halfW + forward[0] * sz * halfD,
    piece.position[1] + right[1] * sx * halfW + forward[1] * sz * halfD,
  ]);
}

/** How much of a standing height a posture keeps. A figure lying down is drawn along the floor instead. */
export function postureHeight(posture: string): number {
  if (posture === 'sit') return 0.72;
  if (posture === 'crouch' || posture === 'kneel') return 0.6;
  if (posture === 'bow') return 0.85;
  if (posture === 'lie') return 0.18;
  return 1;
}

export interface CameraCone {
  /** The lens point first, then the far arc from the left edge of the view to the right. */
  points: Point[];
  reach: number;
}

/** The floor wedge a lens sees: its horizontal field of view, out to a little past what it aims at. */
export function cameraCone(camera: Pick<DiagramCamera, 'position' | 'target' | 'fov_deg'>, samples = 10): CameraCone {
  const dx = camera.target[0] - camera.position[0];
  const dz = camera.target[1] - camera.position[1];
  const distance = Math.hypot(dx, dz);
  const heading = distance > 1e-6 ? Math.atan2(dx, dz) : 0;
  const reach = Math.min(14, Math.max(3, distance * 1.25));
  const half = radians(Math.min(160, Math.max(4, camera.fov_deg)) / 2);
  const points: Point[] = [[camera.position[0], camera.position[1]]];
  for (let index = 0; index <= samples; index += 1) {
    const angle = heading - half + (2 * half * index) / samples;
    points.push([camera.position[0] + Math.sin(angle) * reach, camera.position[1] + Math.cos(angle) * reach]);
  }
  return { points, reach };
}

export interface TagBox {
  name: string;
  color: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Where the leader line meets the head. */
  anchor: Point;
}

const TAG_HEIGHT = 40;
const TAG_GAP = 6;

/** A tag's width for its text: CJK glyphs are a full em, Latin ones about half. */
export function tagWidth(name: string, fontSize = 24): number {
  let ems = 0;
  for (const char of name) ems += char.charCodeAt(0) < 0x100 ? 0.56 : 1;
  return Math.ceil(ems * fontSize + 26);
}

/**
 * Name tags above the heads, moved so that no two overlap and none leaves the picture.
 * A tag that would cover another is raised above it; the leader line still ends on its own head.
 */
export function placeTags(heads: Array<{ name: string; color: string; head: Point }>, width = DIAGRAM_WIDTH, top = 96): TagBox[] {
  const placed: TagBox[] = [];
  // Far heads (higher on the picture) first, so the near ones stack over them only when they must.
  const ordered = [...heads].sort((a, b) => a.head[1] - b.head[1] || a.head[0] - b.head[0]);
  for (const item of ordered) {
    const boxWidth = tagWidth(item.name);
    const x = Math.min(width - boxWidth - 8, Math.max(8, item.head[0] - boxWidth / 2));
    let y = item.head[1] - 46 - TAG_HEIGHT;
    for (let guard = 0; guard < 40; guard += 1) {
      const hit = placed.find(other => x < other.x + other.width + TAG_GAP && other.x < x + boxWidth + TAG_GAP
        && y < other.y + other.height + TAG_GAP && other.y < y + TAG_HEIGHT + TAG_GAP);
      if (!hit) break;
      y = hit.y - TAG_HEIGHT - TAG_GAP;
    }
    placed.push({ name: item.name, color: item.color, x, y: Math.max(top, y), width: boxWidth, height: TAG_HEIGHT, anchor: item.head });
  }
  return placed;
}

/** The point halfway along a route, by length: where its order number sits. */
export function routeMidpoint(points: Point[]): Point {
  if (points.length < 2) return points[0] ?? [0, 0];
  const lengths = points.slice(1).map((point, index) => Math.hypot(point[0] - points[index][0], point[1] - points[index][1]));
  const total = lengths.reduce((sum, value) => sum + value, 0);
  let walked = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    if (walked + lengths[index] >= total / 2) {
      const part = lengths[index] > 0 ? (total / 2 - walked) / lengths[index] : 0;
      return [
        points[index][0] + (points[index + 1][0] - points[index][0]) * part,
        points[index][1] + (points[index + 1][1] - points[index][1]) * part,
      ];
    }
    walked += lengths[index];
  }
  return points[points.length - 1];
}

/** An arrowhead at `tip`, pointing the way `from → tip` runs, in picture pixels. */
export function arrowHead(from: Point, tip: Point, size = 18): Point[] {
  const dx = tip[0] - from[0];
  const dy = tip[1] - from[1];
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  return [
    tip,
    [tip[0] - ux * size - uy * size * 0.5, tip[1] - uy * size + ux * size * 0.5],
    [tip[0] - ux * size + uy * size * 0.5, tip[1] - uy * size - ux * size * 0.5],
  ];
}

/** A circle of `radius` metres lying on the floor, as picture points: an ellipse once the view tilts. */
export function ringPoints(center: Point, radius: number, projection: Projection, samples = 48): Point[] {
  const points: Point[] = [];
  for (let index = 0; index < samples; index += 1) {
    const angle = (2 * Math.PI * index) / samples;
    points.push(projection.at(center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius));
  }
  return points;
}

/** The radii of an effect's rings, outermost first: evenly spaced inside the placeholder radius. */
export function ringRadii(radius: number, rings: number): number[] {
  const count = Math.max(1, Math.min(3, Math.round(rings)));
  return Array.from({ length: count }, (_item, index) => (radius * (count - index)) / count);
}

/** A four-pointed star at `at`, in picture pixels: where a blow lands. */
export function contactStar(at: Point, size = 16): Point[] {
  const inner = size * 0.32;
  const points: Point[] = [];
  for (let index = 0; index < 8; index += 1) {
    const reach = index % 2 === 0 ? size : inner;
    const angle = (Math.PI * index) / 4 - Math.PI / 2;
    points.push([at[0] + Math.cos(angle) * reach, at[1] + Math.sin(angle) * reach]);
  }
  return points;
}

/** Metres as the diagram writes them: halves, never below 0.5. */
export function metresLabel(meters: number): string {
  const rounded = Math.max(0.5, Math.round(meters * 2) / 2);
  return `约 ${rounded} 米`;
}

/** The legend as tab-separated lines, for pasting into a sheet or a note next to the exported picture. */
export function legendText(rows: LegendRow[], columns: string[] = ['标记', '含义', '颜色', '指向位置']): string {
  const clean = (value: string) => value.replace(/[\t\n]+/g, ' ').trim();
  return [columns.join('\t'), ...rows.map(row => [row.mark, row.meaning, row.color, row.where || '—'].map(clean).join('\t'))].join('\n');
}

export const pathOf = (points: Point[]) => points.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');

/** A colour mixed toward black, for a figure's floor shadow and outline. */
export function darker(hex: string, amount = 0.45): string {
  const text = hex.replace('#', '');
  const full = text.length === 3 ? [...text].map(char => char + char).join('') : text;
  const channels = [0, 2, 4].map(index => Math.round(parseInt(full.slice(index, index + 2), 16) * (1 - amount)));
  if (channels.some(Number.isNaN)) return '#444444';
  return `#${channels.map(value => value.toString(16).padStart(2, '0')).join('')}`;
}

export function diagramFileName(sceneId: string, diagram: Pick<BlockingDiagram, 'index' | 'total'>, viewId: string): string {
  const safe = sceneId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 60) || 'scene';
  return `${safe}-站位图-${diagram.index}of${diagram.total}-${viewId}.png`;
}
