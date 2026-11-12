import { createContext, useContext, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Text } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { Vector3, type Camera, type Group, type Mesh, type OrthographicCamera, type PerspectiveCamera } from 'three';

import { HELPER_FLAG } from '../lib/capture';
import { faceViewer } from '../lib/faceViewer';
import { metresPerPixel, screenScale } from '../lib/viewHelpers';
import { raycastWhenShown } from './hitOnTop';
import { boardFor, createLabelBoard, estimatedEms, LABEL_PREP_PRIORITY, labelRank, LIFT_HIDDEN, placeLabels, type LabelKind } from './labelLayout';

const WORLD = new Vector3();
const VIEW = new Vector3();
const SCALE = new Vector3();
/** Below this many screen pixels of letter height a name stops being readable. */
const SMALLEST_LETTER_PX = 13;
/** Troika's "normal" line height, for a label whose text has not been laid out yet. */
const LINE_EMS = 1.2;
const OUTLINE_EMS = 0.08;
const DOT_EMS = 0.16;

/** One label as the layer sees it: the label fills it in after it renders, the layer each frame. Not React state; nothing renders from it. */
class LabelSlot {
  anchor: Group | null = null;
  lift: Group | null = null;
  text: Mesh | null = null;
  dot: Mesh | null = null;
  rank = 0;
  fontSize = 0.13;
  ems = 1;
  /** The text's own height with its outline, in its own units: how far one climb lifts it. Measured each frame. */
  height = 0;

  attach(anchor: Group | null, lift: Group | null, text: Mesh | null, dot: Mesh | null) {
    this.anchor = anchor;
    this.lift = lift;
    this.text = text;
    this.dot = dot;
  }

  update(rank: number, fontSize: number, ems: number) {
    this.rank = rank;
    this.fontSize = fontSize;
    this.ems = ems;
  }

  measured(height: number) {
    this.height = height;
  }

  /** Raise the text `lift` of its own heights, or swap it for its dot. */
  place(lift: number) {
    const shown = lift !== LIFT_HIDDEN;
    if (this.text && this.text.visible !== shown) this.text.visible = shown;
    if (this.dot && this.dot.visible === shown) this.dot.visible = !shown;
    const y = shown ? lift * this.height : 0;
    if (this.lift && this.lift.position.y !== y) this.lift.position.y = y;
  }
}

class LabelRegistry {
  readonly slots: LabelSlot[] = [];

  add(slot: LabelSlot) {
    this.slots.push(slot);
  }

  remove(slot: LabelSlot) {
    const index = this.slots.indexOf(slot);
    if (index >= 0) this.slots.splice(index, 1);
  }
}

const Registry = createContext<LabelRegistry | null>(null);

/** Pixels one metre covers `depth` metres in front of `camera`. */
function pixelsPerMetre(camera: Camera, depth: number, viewportHeightPx: number): number {
  const lens = camera as PerspectiveCamera;
  if (lens.isPerspectiveCamera) return 1 / metresPerPixel(depth / Math.max(lens.zoom, 1e-6), lens.fov, viewportHeightPx);
  const plan = camera as OrthographicCamera;
  return (plan.zoom * viewportHeightPx) / Math.max(plan.top - plan.bottom, 1e-6);
}

/**
 * Keeps the names of one view from printing over each other. Each frame, after every label has
 * turned to the viewer and taken its size, the labels are measured on screen and laid out: what is
 * picked first, then figures, lenses and set pieces; one that would cover a label already placed
 * climbs onto it, and gives way to a dot when it would have to climb too far. Only the view that is worked in
 * draws names, so only it needs this; a capture hides the labels and their dots with every helper.
 */
export function StageLabelLayer({ children }: { children: ReactNode }) {
  const [registry] = useState(() => new LabelRegistry());
  const board = useRef(createLabelBoard(32));
  useFrame(({ camera, size }) => {
    const { slots } = registry;
    if (!slots.length) return;
    const room = boardFor(board.current, slots.length);
    board.current = room;
    room.count = slots.length;
    // The orbit has moved the view this frame, but its matrices are only brought up to date by the render.
    camera.updateMatrixWorld();
    for (let index = 0; index < slots.length; index += 1) {
      const slot = slots[index];
      room.rank[index] = slot.rank;
      room.onScreen[index] = 0;
      if (!slot.anchor) continue;
      slot.anchor.getWorldPosition(WORLD);
      VIEW.copy(WORLD).applyMatrix4(camera.matrixWorldInverse);
      const depth = -VIEW.z;
      if (!(depth > 0)) continue;
      WORLD.project(camera);
      if (Math.abs(WORLD.x) > 1.2 || Math.abs(WORLD.y) > 1.2 || WORLD.z > 1) continue;
      // The text's own laid-out box once troika has it; until then an estimate from its letters.
      const bounds = (slot.text as { textRenderInfo?: { blockBounds?: number[] } } | null)?.textRenderInfo?.blockBounds;
      const outline = slot.fontSize * OUTLINE_EMS * 2;
      const width = (bounds ? bounds[2] - bounds[0] : slot.ems * slot.fontSize) + outline;
      const height = (bounds ? bounds[3] - bounds[1] : LINE_EMS * slot.fontSize) + outline;
      slot.measured(height);
      const pixels = pixelsPerMetre(camera, depth, size.height) * slot.anchor.getWorldScale(SCALE).y;
      room.onScreen[index] = 1;
      room.depth[index] = depth;
      room.x[index] = ((WORLD.x + 1) / 2) * size.width;
      room.bottom[index] = ((1 - WORLD.y) / 2) * size.height;
      room.width[index] = width * pixels;
      room.height[index] = height * pixels;
    }
    placeLabels(room);
    for (let index = 0; index < slots.length; index += 1) slots[index].place(room.lift[index]);
  });
  return <Registry.Provider value={registry}>{children}</Registry.Provider>;
}

/**
 * A name hung over something on stage. It always faces the viewer, whichever way the figure or prop
 * it belongs to is turned, and it stops shrinking once the view is far enough that it could no
 * longer be read. Both are worked out just before a frame is drawn rather than a frame late: the
 * canvases only draw on demand, so a label that lagged would stay wrong until the next change.
 * Inside a `StageLabelLayer` it also moves out of the way of other names. A capture never shows it.
 */
export function StageLabel({ position, fontSize, color, kind, selected = false, children }: {
  /** Where the bottom middle of the text sits, in the parent's own frame. */
  position: [number, number, number];
  /** Letter height in metres while the view is close. */
  fontSize: number;
  color: string;
  /** What it names, which decides who gives way when two names would cover each other. */
  kind: LabelKind;
  /** A picked thing's name is always shown. */
  selected?: boolean;
  children: string;
}) {
  const registry = useContext(Registry);
  const invalidate = useThree(state => state.invalidate);
  const [slot] = useState(() => new LabelSlot());
  const group = useRef<Group>(null);
  const lift = useRef<Group>(null);
  const text = useRef<Mesh>(null);
  const dot = useRef<Mesh>(null);
  useLayoutEffect(() => {
    slot.attach(group.current, lift.current, text.current, dot.current);
    registry?.add(slot);
    return () => registry?.remove(slot);
  }, [registry, slot]);
  const rank = labelRank(kind, selected);
  const ems = estimatedEms(children);
  useLayoutEffect(() => {
    slot.update(rank, fontSize, ems);
    // Being picked can bring a name back from its dot; nothing else about that draws a frame.
    invalidate();
  }, [ems, fontSize, invalidate, rank, slot]);
  useFrame(({ camera, size }) => {
    const node = group.current;
    if (!node) return;
    faceViewer(node, camera);
    const lens = camera as PerspectiveCamera;
    const scale = lens.isPerspectiveCamera
      ? screenScale(fontSize, SMALLEST_LETTER_PX, lens.position.distanceTo(node.getWorldPosition(WORLD)), lens.fov, size.height)
      : 1;
    if (node.scale.x !== scale) node.scale.setScalar(scale);
  }, LABEL_PREP_PRIORITY);
  return (
    <group ref={group} position={position} userData={{ [HELPER_FLAG]: true }}>
      <group ref={lift}>
        <Text
          ref={text} fontSize={fontSize} color={color} anchorX="center" anchorY="bottom" outlineWidth={fontSize * OUTLINE_EMS} outlineColor="#fcedef"
          raycast={raycastWhenShown}
        >
          {children}
        </Text>
      </group>
      <mesh ref={dot} visible={false} position={[0, fontSize * DOT_EMS, 0]} raycast={raycastWhenShown}>
        <circleGeometry args={[fontSize * DOT_EMS, 12]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  );
}
