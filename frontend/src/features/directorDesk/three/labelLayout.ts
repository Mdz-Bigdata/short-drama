// Where the names over the stage go on screen, so that two things standing close together do not
// print their names on top of each other. Kept free of three: the director view fills a board with
// each label's screen box, this decides which ones stay put, which climb and which give way to a dot.

/**
 * The frame priority of the per-label pass (facing, size): after the orbit has moved the view (-1)
 * and before the layer lays the labels out (0). `ScreenLifted` runs then too, so a lens's label is
 * measured where it is drawn. Never above 0: a positive priority takes the drawing over from R3F.
 */
export const LABEL_PREP_PRIORITY = -0.5;

export type LabelKind = 'actor' | 'distance' | 'camera' | 'prop';

/** What is picked is always named; past that a figure outranks the lens filming it, and a lens a set piece. */
const KIND_RANK: Record<LabelKind, number> = { actor: 4, distance: 3, camera: 2, prop: 1 };
const PINNED_RANK = 5;
/** A distance the director measured is what they are reading: even a picked name nearer the view makes way for it. */
const MEASURED_RANK = 6;
/** A label climbs at most this many of its own heights, standing on the names in its way, before it gives way to a dot. */
export const MAX_LIFT = 3;
/** The lift of a label that gave way: only a dot is left at its foot. */
export const LIFT_HIDDEN = -1;
/** Air between two labels side by side, in pixels. One standing on another may touch it. */
const GAP_PX = 2;
/** Less than this much overlap, in pixels, is rounding. */
const TOUCH_PX = 0.5;
/** Han characters and kana are about one letter height wide; Latin letters and digits a little over half. */
const NARROW_EM = 0.6;

export function labelRank(kind: LabelKind, selected: boolean): number {
  if (!selected) return KIND_RANK[kind];
  return kind === 'distance' ? MEASURED_RANK : PINNED_RANK;
}

/**
 * Every label's screen box, one slot per label: `x` the middle and `bottom` the foot in pixels from
 * the top left, `width` and `height` in pixels, `depth` in metres in front of the view. Arrays, so a
 * frame fills them in place; `lift` is the answer, in label heights or `LIFT_HIDDEN`.
 */
export interface LabelBoard {
  count: number;
  x: Float64Array;
  bottom: Float64Array;
  width: Float64Array;
  height: Float64Array;
  depth: Float64Array;
  rank: Float64Array;
  /** 0 for a label behind the view or off the pane: it is left as it is and takes no room. */
  onScreen: Uint8Array;
  lift: Float64Array;
  order: Int32Array;
}

export function createLabelBoard(capacity: number): LabelBoard {
  const size = Math.max(1, capacity);
  return {
    count: 0,
    x: new Float64Array(size), bottom: new Float64Array(size), width: new Float64Array(size), height: new Float64Array(size),
    depth: new Float64Array(size), rank: new Float64Array(size), onScreen: new Uint8Array(size), lift: new Float64Array(size), order: new Int32Array(size),
  };
}

/** The board itself while it is big enough; otherwise one twice as big (nothing in it needs keeping, every frame refills it). */
export function boardFor(board: LabelBoard, count: number): LabelBoard {
  return board.x.length >= count ? board : createLabelBoard(Math.max(count, board.x.length * 2));
}

/** A label's width in letter heights before its text has been laid out. */
export function estimatedEms(text: string): number {
  let ems = 0;
  for (const letter of text) ems += (letter.codePointAt(0) ?? 0) > 0x2e7f ? 1 : NARROW_EM;
  return ems;
}

/** Placed first: the higher rank, then the nearer label, then the one that came first. */
function before(board: LabelBoard, a: number, b: number): boolean {
  if (board.rank[a] !== board.rank[b]) return board.rank[a] > board.rank[b];
  if (board.depth[a] !== board.depth[b]) return board.depth[a] < board.depth[b];
  return a < b;
}

/** The top of the highest label already placed that a box of this label with its foot at `foot` would cover; NaN when it covers none. */
function blockerTop(board: LabelBoard, label: number, foot: number, placed: number): number {
  const half = board.width[label] / 2 + GAP_PX;
  const top = foot - board.height[label] + TOUCH_PX;
  const low = foot - TOUCH_PX;
  let highest = NaN;
  for (let index = 0; index < placed; index += 1) {
    const other = board.order[index];
    const otherLift = board.lift[other];
    if (!board.onScreen[other] || otherLift === LIFT_HIDDEN) continue;
    if (Math.abs(board.x[other] - board.x[label]) >= half + board.width[other] / 2) continue;
    const otherFoot = board.bottom[other] - board.height[other] * otherLift;
    const otherTop = otherFoot - board.height[other];
    if (otherFoot > top && otherTop < low && !(otherTop >= highest)) highest = otherTop;
  }
  return highest;
}

/**
 * Decide each label's lift. The most important label keeps its place; each one after it, when it
 * would cover a label already placed, climbs to stand on the highest of those, and again, until it
 * is clear. One that would have to climb more than `MAX_LIFT` of its own heights, or off the top of
 * the pane, gives way to a dot, unless it is pinned (what is picked): that one stays where it is.
 */
export function placeLabels(board: LabelBoard): void {
  const { count, order } = board;
  for (let index = 0; index < count; index += 1) {
    // Insertion sort: a few dozen labels, and no allocation.
    let at = index;
    while (at > 0 && before(board, index, order[at - 1])) {
      order[at] = order[at - 1];
      at -= 1;
    }
    order[at] = index;
  }
  for (let index = 0; index < count; index += 1) {
    const label = order[index];
    board.lift[label] = 0;
    if (!board.onScreen[label]) continue;
    const bottom = board.bottom[label];
    const height = Math.max(board.height[label], TOUCH_PX);
    let foot = bottom;
    let lift = 0;
    // Each climb lands at least half a pixel higher, so this ends; the reach ends it sooner.
    for (let blocker = blockerTop(board, label, foot, index); !Number.isNaN(blocker); blocker = blockerTop(board, label, foot, index)) {
      foot = blocker;
      lift = (bottom - foot) / height;
      if (lift > MAX_LIFT + 1e-6 || foot - height < 0) {
        lift = LIFT_HIDDEN;
        break;
      }
    }
    board.lift[label] = lift === LIFT_HIDDEN && board.rank[label] >= PINNED_RANK ? 0 : lift;
  }
}
