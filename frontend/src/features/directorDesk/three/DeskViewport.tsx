import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Grid, Line, OrbitControls, PerspectiveCamera, TransformControls } from '@react-three/drei';
import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber';
import { MOUSE, Plane, Raycaster, TOUCH, Vector2, Vector3, type Object3D, type PerspectiveCamera as LensCamera } from 'three';

import { actorsInShot, type GroundPoint, type SpacePoint, type StageOperation, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import { overrideFor } from '../deskOperations';
import { refKey, type DeskTool, type DeskViewHandle, type MeasurePoint, type SelectionRef, type SnapSettings } from '../deskTypes';
import { HELPER_FLAG } from '../lib/capture';
import { dragRefusal, heldTargets } from '../lib/contacts';
import { anchorOf, dragOperations, gizmoMode, type AnchorTransform } from '../lib/dragOperations';
import { appendStrokePoint, strokeFull, strokeIsRoute, type PathTarget } from '../lib/pathTool';
import { useReducedMotion } from '../lib/useReducedMotion';
import type { ActorPath, CameraPath } from '../lib/sampling';
import { lightReach, round2, stageReach } from '../lib/stageMath';
import { focusOf, type ViewFocus } from '../lib/viewFocus';
import { focusPose, gridCells, lensLabel, wholeSetPose } from '../lib/viewHelpers';
import { CameraRig, type PointerHandlers } from './CameraRig';
import { ActorFigure } from './figures/ActorFigure';
import { PoseHandles } from './PoseHandles';
import { StageProp } from './props/StageProp';
import { StageLabel, StageLabelLayer } from './StageLabel';
import { actorColor, DESK_FLOOR_COLOR, SELECTION_COLOR, webglAvailable } from './stageLook';
import { ContextLossGuard, StageLights, ViewportBoundary, ViewportUnavailable } from './ViewportShell';

export interface DeskViewportProps {
  /** The plan as drawn: confirmed, plus unconfirmed edits, plus the drag in progress. */
  plan: StagePlan;
  /** The plan without the drag in progress: what a drag measures its offset from. */
  basePlan: StagePlan;
  shot?: StageShot;
  selection: SelectionRef[];
  tool: DeskTool;
  snap: SnapSettings;
  hidden: string[];
  locked: string[];
  readOnly: boolean;
  measure: MeasurePoint[];
  lensCameraId: string;
  /** Pose edits go to this shot's override rather than to the actor's mark. */
  poseShotOnly: boolean;
  footLock: boolean;
  /** The filming lens's travel through the shot, drawn as a line with a marker per key. */
  cameraPath?: CameraPath | null;
  /** Every actor track of the shot that goes somewhere, drawn the same way in the actor's colour. */
  actorPaths?: ActorPath[];
  /** Who a stroke drawn with the path tool belongs to; `null` keeps the tool from drawing. */
  pathTarget?: PathTarget | null;
  /** Why the path tool cannot draw right now, shown in the hint. */
  pathRefusal?: string;
  /** Playback is running: the stage is for watching, so every handle steps aside. */
  playing?: boolean;
  onSelect: (ref: SelectionRef, additive: boolean) => void;
  onClearSelection: () => void;
  onPreview: (operations: StageOperation[] | null) => void;
  onCommit: (operations: StageOperation[]) => void;
  /** A drag the stage will not take (a prop held in a hand): the sentence says why. */
  onRefuse?: (message: string) => void;
  onMeasure: (point: MeasurePoint) => void;
  /** A finished stroke of the path tool, as ground points in drawing order. */
  onPath?: (points: GroundPoint[]) => void;
  onReady?: (handle: DeskViewHandle | null) => void;
}

// A click that ends a gizmo drag also reaches whatever is under the pointer; ignore it briefly.
const CLICK_AFTER_DRAG_MS = 250;
const NO_PATHS: ActorPath[] = [];
// While the path tool draws with the left button, the orbit keeps only pan (right button, two fingers) and zoom.
const ORBIT_BUTTONS = { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN };
const DRAWING_BUTTONS = { LEFT: undefined, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN };
const ORBIT_TOUCHES = { ONE: TOUCH.ROTATE, TWO: TOUCH.DOLLY_PAN };
const DRAWING_TOUCHES = { ONE: undefined, TWO: TOUCH.DOLLY_PAN };
/** Lines on the floor sit just above it so the ground plane does not swallow them. */
const FLOOR_LIFT = 0.03;

/** One request to re-aim the view. `stamp` 0 is "nothing asked yet"; a `focus` asks for that rather than the whole set. */
interface FitRequest {
  stamp: number;
  focus: ViewFocus | null;
}

/** Re-aim the view each time a new request arrives: back far enough to see the whole set, or onto the request's focus. */
function FitView({ plan, request }: { plan: StagePlan; request: FitRequest }) {
  const camera = useThree(state => state.camera);
  const controls = useThree(state => state.controls) as unknown as { target?: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void }; update?: () => void } | null;
  const invalidate = useThree(state => state.invalidate);
  // Read when asked, not followed: a playing shot changes the plan every frame.
  const latest = useRef(plan);
  useEffect(() => { latest.current = plan; }, [plan]);
  useEffect(() => {
    if (!request.stamp || !controls?.target) return;
    const lens = camera as LensCamera;
    const { center, radius } = stageReach(latest.current);
    const pose = request.focus
      // Framing one thing keeps the angle the director chose; only what is looked at, and from how far, changes.
      ? focusPose({ position: [camera.position.x, camera.position.y, camera.position.z], target: [controls.target.x, controls.target.y, controls.target.z] }, request.focus, lens.fov, lens.aspect)
      : wholeSetPose(center, radius, lens.fov, lens.aspect);
    controls.target.set(...pose.target);
    camera.position.set(...pose.position);
    controls.update?.();
    invalidate();
  }, [camera, controls, invalidate, request]);
  return null;
}

function ViewBridge({ onReady, onFrameSelection }: { onReady?: (handle: DeskViewHandle | null) => void; onFrameSelection: () => void }) {
  const camera = useThree(state => state.camera);
  const controls = useThree(state => state.controls) as { target?: { x: number; y: number; z: number } } | null;
  useEffect(() => {
    onReady?.({
      viewPose: () => ({
        position: [round2(camera.position.x), round2(camera.position.y), round2(camera.position.z)],
        target: controls?.target ? [round2(controls.target.x), round2(controls.target.y), round2(controls.target.z)] : [0, 1, 0],
      }),
      frameSelection: onFrameSelection,
    });
    return () => onReady?.(null);
  }, [camera, controls, onFrameSelection, onReady]);
  return null;
}

/**
 * The pointer phase of a freehand stroke. It listens on the canvas itself rather than on the ground
 * mesh so a route can start under a figure (where the actor stands), and on the window afterwards so
 * leaving the canvas still ends the stroke. Escape cancels; the pointer-up that follows a stroke or a
 * cancel is reported through `onRelease` so the click it turns into can be swallowed.
 */
function StrokeListener({ armed, onStart, onPoint, onEnd, onRelease }: {
  armed: boolean;
  onStart: (point: GroundPoint) => void;
  onPoint: (point: GroundPoint) => void;
  onEnd: (cancelled: boolean) => void;
  onRelease: () => void;
}) {
  const camera = useThree(state => state.camera);
  const canvas = useThree(state => state.gl.domElement);
  useEffect(() => {
    if (!armed) return undefined;
    const raycaster = new Raycaster();
    const ground = new Plane(new Vector3(0, 1, 0), 0);
    const hitAt = (event: PointerEvent): GroundPoint | null => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      raycaster.setFromCamera(new Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1), camera);
      const hit = raycaster.ray.intersectPlane(ground, new Vector3());
      return hit ? [hit.x, hit.z] : null;
    };
    let held = false;
    let finished = false;
    const detach = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cancel);
      window.removeEventListener('keydown', key, true);
    };
    const finish = (cancelled: boolean) => {
      if (finished) return;
      finished = true;
      onEnd(cancelled);
    };
    const move = (event: PointerEvent) => {
      if (finished) return;
      const point = hitAt(event);
      if (point) onPoint(point);
    };
    const up = () => {
      held = false;
      detach();
      finish(false);
      onRelease();
    };
    const cancel = () => {
      held = false;
      detach();
      finish(true);
      onRelease();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Escape means "drop this stroke", not "clear the selection": the desk's own handler must not see it.
      event.stopImmediatePropagation();
      event.preventDefault();
      finish(true);
    };
    const down = (event: PointerEvent) => {
      if (held || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const point = hitAt(event);
      if (!point) return;
      held = true;
      finished = false;
      onStart(point);
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', cancel);
      window.addEventListener('keydown', key, true);
    };
    canvas.addEventListener('pointerdown', down);
    return () => {
      canvas.removeEventListener('pointerdown', down);
      if (!held) return;
      // The tool was put down mid-stroke (selection gone, playback started): the stroke goes with it.
      detach();
      finish(true);
    };
  }, [armed, camera, canvas, onEnd, onPoint, onRelease, onStart]);
  return null;
}

// drei re-attaches the controls whenever its `children` change identity, and three's detach()
// forgets the axis being dragged: a fresh <group /> per render would end every drag without its
// mouse-up. One element for the life of the module keeps the attachment, and the drag, intact.
const GIZMO_ANCHOR = <group />;

function readAnchor(object: Object3D): AnchorTransform {
  return {
    position: [object.position.x, object.position.y, object.position.z],
    yawDeg: (object.rotation.y * 180) / Math.PI,
    scale: [object.scale.x, object.scale.y, object.scale.z],
  };
}

function Gizmo({ anchor, mode, primary, onDragStart, onDrag, onDragEnd }: {
  anchor: AnchorTransform;
  mode: 'translate' | 'rotate' | 'scale';
  primary: SelectionRef;
  onDragStart: () => void;
  onDrag: (now: AnchorTransform) => AnchorTransform;
  onDragEnd: () => void;
}) {
  const floorBound = primary.kind !== 'camera' && primary.kind !== 'camera-target';
  return (
    // drei switches the default OrbitControls off for as long as a handle is held.
    <TransformControls
      mode={mode}
      space={mode === 'translate' ? 'world' : 'local'}
      size={0.8}
      showX={mode !== 'rotate'}
      showY={mode === 'rotate' || mode === 'scale' || !floorBound}
      showZ={mode !== 'rotate'}
      position={anchor.position}
      // YXZ keeps the whole turn in `rotation.y`; the default order folds it back past ±90°.
      rotation={[0, (anchor.yawDeg * Math.PI) / 180, 0, 'YXZ']}
      userData={{ [HELPER_FLAG]: true }}
      onMouseDown={onDragStart}
      onMouseUp={onDragEnd}
      onObjectChange={event => {
        const object = (event?.target as { object?: Object3D } | undefined)?.object;
        if (!object) return;
        const snapped = onDrag(readAnchor(object));
        object.position.set(...snapped.position);
        object.rotation.set(0, (snapped.yawDeg * Math.PI) / 180, 0, 'YXZ');
        // Size lives in the plan, not in the handle: the handle always starts the next move at 1.
        object.scale.set(1, 1, 1);
      }}
    >
      {GIZMO_ANCHOR}
    </TransformControls>
  );
}

function distance(a: SpacePoint, b: SpacePoint): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** A distance read off the stage. `pinned` is one the director measured: its number is never moved aside for a name. */
function Ruler({ from, to, color, pinned = false }: { from: SpacePoint; to: SpacePoint; color: string; pinned?: boolean }) {
  const middle: SpacePoint = [(from[0] + to[0]) / 2, Math.max((from[1] + to[1]) / 2, 0.04) + 0.16, (from[2] + to[2]) / 2];
  // drei builds a new line (and drops its material) whenever `points` is a new array; while a shot plays this renders every frame.
  const [ax, ay, az] = from;
  const [bx, by, bz] = to;
  const points = useMemo<SpacePoint[]>(() => [[ax, Math.max(ay, 0.04), az], [bx, Math.max(by, 0.04), bz]], [ax, ay, az, bx, by, bz]);
  return (
    <group userData={{ [HELPER_FLAG]: true }}>
      <Line points={points} color={color} lineWidth={1.4} dashed dashSize={0.14} gapSize={0.08} />
      <StageLabel position={middle} fontSize={0.15} color={color} kind="distance" selected={pinned}>{`${distance(from, to).toFixed(2)} m`}</StageLabel>
    </group>
  );
}

function onFloor(point: SpacePoint): SpacePoint {
  return [point[0], Math.max(point[1], FLOOR_LIFT), point[2]];
}

/** A track through the shot: the line it travels and a marker on each key, in one colour. */
function TrackPath({ points, keys, color, markerSize }: { points: SpacePoint[]; keys: Array<{ time: number; position: SpacePoint }>; color: string; markerSize: number }) {
  // The track holds still while the shot plays through it; only a new track rebuilds the line.
  const line = useMemo(() => points.map(onFloor), [points]);
  return (
    <group userData={{ [HELPER_FLAG]: true }}>
      {points.length >= 2 && <Line points={line} color={color} lineWidth={1.6} />}
      {keys.map((key, index) => (
        <mesh key={index} position={onFloor(key.position)}>
          <octahedronGeometry args={[markerSize]} />
          <meshBasicMaterial color={color} />
        </mesh>
      ))}
    </group>
  );
}

export default function DeskViewport({
  plan, basePlan, shot, selection, tool, snap, hidden, locked, readOnly, measure, lensCameraId, poseShotOnly, footLock, cameraPath,
  actorPaths = NO_PATHS, pathTarget = null, pathRefusal = '', playing = false,
  onSelect, onClearSelection, onPreview, onCommit, onRefuse, onMeasure, onPath, onReady,
}: DeskViewportProps) {
  const [canRender] = useState(webglAvailable);
  const [contextLost, setContextLost] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [stroke, setStroke] = useState<GroundPoint[] | null>(null);
  const reducedMotion = useReducedMotion();
  const drag = useRef<{ start: AnchorTransform; operations: StageOperation[]; endedAt: number; refused?: boolean }>({ start: { position: [0, 0, 0], yawDeg: 0, scale: [1, 1, 1] }, operations: [], endedAt: 0 });
  const strokeRef = useRef<GroundPoint[]>([]);
  // The pointer-up after a route (or a cancelled stroke) lands as a click on whatever is under it.
  const swallowRelease = useRef(false);
  // Read through a ref so a parent render mid-stroke cannot re-arm the listener and drop the stroke.
  const onPathRef = useRef(onPath);
  useEffect(() => { onPathRef.current = onPath; }, [onPath]);

  const actors = useMemo(() => actorsInShot(plan, shot), [plan, shot]);
  // Kept while the axis is: a new array would have drei rebuild the line on every frame of playback.
  const axisLine = useMemo<SpacePoint[]>(() => (plan.axis.kind === 'none' ? [] : [[plan.axis.start[0], 0.02, plan.axis.start[1]], [plan.axis.end[0], 0.02, plan.axis.end[1]]]), [plan.axis]);
  const selectedKeys = useMemo(() => new Set(selection.map(refKey)), [selection]);
  const primary = selection[selection.length - 1];
  const mode = readOnly || playing || (primary && locked.includes(refKey(primary))) ? null : gizmoMode(tool, primary);
  const anchor = useMemo(() => (primary ? anchorOf(plan, shot, primary) : null), [plan, primary, shot]);
  const drawing = tool === 'path' && pathTarget !== null && Boolean(onPath) && !readOnly && !playing;
  // Asked for by the buttons, a double-click or the desk's shortcut. A blockout landing asks for the whole set too, since it is
  // usually far bigger than the default view; a piece deleted from one does not, or the view the director set up would be thrown away.
  const [fit, setFit] = useState<FitRequest>({ stamp: 0, focus: null });
  const blockoutPieces = plan.landmarks.filter(item => item.origin === 'blockout').length;
  const [blockoutSeen, setBlockoutSeen] = useState(0);
  if (blockoutPieces !== blockoutSeen) {
    setBlockoutSeen(blockoutPieces);
    if (blockoutPieces > blockoutSeen) setFit(current => ({ stamp: current.stamp + 1, focus: null }));
  }
  // Read when asked: the callbacks below keep one identity, so the view handle is not rebuilt on every edit.
  const staged = useRef({ plan, shot, selection });
  useEffect(() => { staged.current = { plan, shot, selection }; }, [plan, selection, shot]);
  const frameWholeSet = useCallback(() => setFit(current => ({ stamp: current.stamp + 1, focus: null })), []);
  /** Turn the view onto `refs`, or onto the selection; with nothing to look at, onto the whole set. */
  const frame = useCallback((refs?: SelectionRef[]) => {
    const now = staged.current;
    const focus = focusOf(now.plan, now.shot, refs ?? now.selection);
    setFit(current => ({ stamp: current.stamp + 1, focus }));
  }, []);
  const frameSelection = useCallback(() => frame(), [frame]);
  const root = useRef<HTMLDivElement>(null);
  // The pointer says "this can be picked" only while a click would pick: not while measuring or drawing
  // (their crosshair stays), and not in the middle of a drag. What lies under it is still kept track of,
  // so the pointer is right again the moment the drag ends, without having to leave the object first.
  const hoverBlocked = useRef(false);
  const hoverCursor = useRef('');
  const showCursor = useCallback((cursor: string) => {
    hoverCursor.current = cursor;
    if (root.current) root.current.style.cursor = hoverBlocked.current ? '' : cursor;
  }, []);
  useEffect(() => {
    hoverBlocked.current = tool === 'measure' || drawing || dragging;
    if (root.current) root.current.style.cursor = hoverBlocked.current ? '' : hoverCursor.current;
  }, [dragging, drawing, tool]);
  const plainCursor = useCallback(() => showCursor(''), [showCursor]);
  /** What the pointer does over something that can be picked: say so, and turn the view onto it on a double-click. */
  const pointerOn = useCallback((ref: SelectionRef): PointerHandlers => ({
    onPointerOver: event => {
      // Whatever lies behind is not what a click would pick. Stopping first matters: it ends the hover
      // on every other part of the same piece, and each of those endings resets the cursor.
      event.stopPropagation();
      showCursor('pointer');
    },
    onPointerOut: plainCursor,
    onDoubleClick: event => {
      if (hoverBlocked.current) return;
      event.stopPropagation();
      frame([ref]);
    },
  }), [frame, plainCursor, showCursor]);
  // A locked object does not answer a click, but it still stands in the way of one: nothing behind it is picked
  // through it. It takes the hover the same way, so the pointer does not promise what is behind either.
  const lockedPointer = useMemo<PointerHandlers>(() => ({
    onPointerOver: event => {
      event.stopPropagation();
      showCursor('');
    },
    onDoubleClick: event => event.stopPropagation(),
  }), [showCursor]);
  // A wrist or ankle handle is dragged, not picked.
  const handlePointer = useMemo<Pick<PointerHandlers, 'onPointerOver' | 'onPointerOut'>>(() => ({
    onPointerOver: event => {
      event.stopPropagation();
      showCursor('grab');
    },
    onPointerOut: plainCursor,
  }), [plainCursor, showCursor]);
  // The orbit pivot is read once: following every edit would yank the view around mid-drag.
  const [centre] = useState<SpacePoint>(() => {
    const solid = basePlan.actors.filter(actor => actor.role !== 'crowd');
    const pool = solid.length ? solid : basePlan.actors;
    if (!pool.length) return [0, 1, 0];
    return [pool.reduce((sum, a) => sum + a.position[0], 0) / pool.length, 1, pool.reduce((sum, a) => sum + a.position[1], 0) / pool.length];
  });

  const pick = useCallback((ref: SelectionRef, point?: SpacePoint) => (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    if (performance.now() - drag.current.endedAt < CLICK_AFTER_DRAG_MS) return;
    if (tool === 'measure') {
      onMeasure({ label: 'name' in ref ? ref.name : ref.id, point: point ?? [event.point.x, event.point.y, event.point.z] });
      return;
    }
    if (locked.includes(refKey(ref))) return;
    onSelect(ref, event.shiftKey);
  }, [locked, onMeasure, onSelect, tool]);

  const held = useMemo(() => heldTargets(basePlan, shot?.shot_id), [basePlan, shot]);
  const startDrag = useCallback(() => {
    if (!primary) return;
    const start = anchorOf(basePlan, shot, primary);
    if (!start) return;
    // A held prop goes where the hand goes; a lock only keeps the operator off, the contact is what moves it.
    const refusal = dragRefusal(basePlan, shot?.shot_id, primary, mode);
    drag.current = { start, operations: [], endedAt: 0, refused: Boolean(refusal) };
    if (refusal) onRefuse?.(refusal);
    setDragging(true);
  }, [basePlan, mode, onRefuse, primary, shot]);

  const moveDrag = useCallback((now: AnchorTransform) => {
    if (!primary || !mode) return now;
    // A refused drag holds the handle where it started, so nothing on stage pretends to move.
    if (drag.current.refused) return drag.current.start;
    const result = dragOperations({ plan: basePlan, shot, selection, primary, mode, snap, start: drag.current.start, now });
    // Whatever a hand holds rides along with the person holding it: it is not moved or turned on its own as well.
    const operations = held.size
      ? result.operations.filter(op => !(op.op === 'transform_landmark' && held.has(String(op.name)) && ('position' in op || 'yaw_deg' in op)))
      : result.operations;
    drag.current.operations = operations;
    onPreview(operations);
    return mode === 'scale' ? { ...result.anchor, position: drag.current.start.position, yawDeg: drag.current.start.yawDeg } : result.anchor;
  }, [basePlan, held, mode, onPreview, primary, selection, shot, snap]);

  const endDrag = useCallback(() => {
    const operations = drag.current.operations;
    drag.current = { ...drag.current, operations: [], endedAt: performance.now(), refused: false };
    setDragging(false);
    // One operation batch per gesture, on release; the preview is dropped in the same render.
    if (operations.length) onCommit(operations);
    else onPreview(null);
  }, [onCommit, onPreview]);

  const startStroke = useCallback((point: GroundPoint) => {
    strokeRef.current = appendStrokePoint([], point);
    setStroke(strokeRef.current);
    setDragging(true);
  }, []);
  const extendStroke = useCallback((point: GroundPoint) => {
    const next = appendStrokePoint(strokeRef.current, point);
    if (next === strokeRef.current) return;
    strokeRef.current = next;
    setStroke(next);
  }, []);
  const endStroke = useCallback((cancelled: boolean) => {
    const points = strokeRef.current;
    strokeRef.current = [];
    setStroke(null);
    setDragging(false);
    const route = strokeIsRoute(points);
    // A stroke that never left its first point is a click: it goes on to select or clear as usual.
    swallowRelease.current = cancelled || route;
    if (!cancelled && route) onPathRef.current?.(points);
  }, []);
  const releaseStroke = useCallback(() => {
    if (swallowRelease.current) drag.current.endedAt = performance.now();
    swallowRelease.current = false;
  }, []);

  if (!canRender) return <ViewportUnavailable message="当前浏览器或设备不支持 WebGL，导演台无法显示 3D 舞台。" />;
  if (contextLost) return <ViewportUnavailable message="图形上下文已中断。" onRetry={() => setContextLost(false)} />;

  const subjectNames = shot?.subjects || [];
  const posed = tool === 'pose' && !readOnly && !playing && primary?.kind === 'actor' && !locked.includes(refKey(primary))
    ? actors.find(actor => actor.name === primary.name && actor.figure === 'mannequin') : undefined;
  const posedBase = posed && actorsInShot(basePlan, basePlan.shots.find(item => item.shot_id === shot?.shot_id)).find(actor => actor.name === posed.name);
  const focus = primary?.kind === 'actor' ? actors.find(actor => actor.name === primary.name) : undefined;
  const crowdSelected = (crowdId: string | undefined) => Boolean(crowdId) && selectedKeys.has(`crowd:${crowdId}`);
  const pointerFor = (ref: SelectionRef) => (locked.includes(refKey(ref)) ? lockedPointer : pointerOn(ref));
  const set = stageReach({ actors: [], landmarks: plan.landmarks });
  // The light covers the cast and where the shot's keys take them, as well as the set: figures away from every
  // set piece keep their shadows, and the shadows hold still while the shot plays.
  const lit = lightReach(plan, shot?.shot_id, actors);
  const grid = gridCells(snap.gridSize);
  const pathHint = () => {
    if (readOnly) return '只读状态下不能画路径';
    if (playing) return '播放中不能画路径，先暂停';
    if (!pathTarget) return pathRefusal || '先选择一个角色，或本镜的拍摄机位';
    if (stroke && strokeFull(stroke)) return '已到 400 个点，后面的不再记录：松开即保存，要画更长请重新来过';
    if (stroke) return '松开保存 · Esc 取消';
    const who = pathTarget.kind === 'actor' ? `「${pathTarget.name}」的走位` : '机位的运动路径';
    return `按住左键在地面上拖动，画出${who} · 松开保存，Esc 取消 · 右键平移，滚轮缩放`;
  };

  return (
    <div ref={root} className={`desk-viewport is-director ${tool === 'measure' ? 'is-measuring' : ''} ${drawing ? 'is-drawing' : ''}`} role="region" aria-label="导演视角">
      <ViewportBoundary fallback={<ViewportUnavailable message="3D 场景渲染失败，请关闭后重新打开导演台。" />}>
        <Canvas shadows dpr={[1, 1.5]} frameloop="demand" gl={{ antialias: true, powerPreference: 'high-performance' }} onPointerMissed={() => { if (tool !== 'measure' && performance.now() - drag.current.endedAt > CLICK_AFTER_DRAG_MS) onClearSelection(); }}>
          <StageLights reach={lit.radius} center={lit.center} />
          <PerspectiveCamera makeDefault fov={42} near={0.05} far={500} position={[centre[0] + 5.5, 5, centre[2] + 8]} />
          <OrbitControls
            makeDefault enableDamping={!reducedMotion} target={centre} minDistance={0.5} maxDistance={400} maxPolarAngle={Math.PI / 2.02} enabled={!dragging}
            mouseButtons={drawing ? DRAWING_BUTTONS : ORBIT_BUTTONS} touches={drawing ? DRAWING_TOUCHES : ORBIT_TOUCHES}
          />
          <ViewBridge onReady={onReady} onFrameSelection={frameSelection} />
          <FitView plan={plan} request={fit} />
          <StrokeListener armed={drawing} onStart={startStroke} onPoint={extendStroke} onEnd={endStroke} onRelease={releaseStroke} />
          <ContextLossGuard onLost={() => setContextLost(true)} />
          {/* Names of things standing close together stack above one another, or give way to a dot, rather than print over each other. */}
          <StageLabelLayer>
            <group userData={{ [HELPER_FLAG]: true }}>
              <Grid
                args={[40, 40]} cellSize={grid.cell} cellThickness={0.5} cellColor="#fef9fa"
                sectionSize={grid.section} sectionThickness={0.9} sectionColor="#e14962" fadeDistance={Math.max(45, set.radius * 4)} fadeStrength={1.4} infiniteGrid
              />
            </group>
            <mesh
              rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]} receiveShadow
              // Back on bare floor there is nothing to pick. This also clears the pointer after the piece under it was deleted, which ends no hover.
              onPointerOver={plainCursor}
              onClick={event => {
                event.stopPropagation();
                if (performance.now() - drag.current.endedAt < CLICK_AFTER_DRAG_MS) return;
                if (tool === 'measure') onMeasure({ label: '地面', point: [round2(event.point.x), 0, round2(event.point.z)] });
                // The floor fills the view, so a click on it is the click on "nothing".
                else onClearSelection();
              }}
            >
              <planeGeometry args={[200, 200]} />
              <meshStandardMaterial color={DESK_FLOOR_COLOR} roughness={1} />
            </mesh>
            {plan.axis.kind !== 'none' && (
              <group userData={{ [HELPER_FLAG]: true }}>
                <Line points={axisLine} color="#e60000" lineWidth={1.2} dashed dashSize={0.25} gapSize={0.15} />
              </group>
            )}
            {plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`)).map(item => {
              const ref: SelectionRef = { kind: 'landmark', name: item.name };
              // A blockout's ground slab fills the view: a click on it is a click on the floor. The outliner still reaches it.
              const pickable = !(item.origin === 'blockout' && item.size[2] < 0.2);
              return (
                <group key={item.id} {...(pickable ? pointerFor(ref) : undefined)}>
                  <StageProp
                    landmark={item} selected={selectedKeys.has(`landmark:${item.name}`)}
                    // Names on a hundred wall sections are noise; a picked one still says what it is.
                    labelled={item.origin !== 'blockout' || selectedKeys.has(`landmark:${item.name}`)}
                    onPick={pickable ? pick(ref, [item.position[0], 0, item.position[1]]) : undefined}
                  />
                </group>
              );
            })}
            {actors.filter(actor => !hidden.includes(actor.crowd_id ? `crowd:${actor.crowd_id}` : `actor:${actor.name}`)).map(actor => {
              const ref: SelectionRef = actor.crowd_id ? { kind: 'crowd', id: actor.crowd_id } : { kind: 'actor', name: actor.name };
              return (
                <group key={actor.id} {...pointerFor(ref)}>
                  <ActorFigure
                    actor={actor} labelled={!actor.crowd_id} subject={subjectNames.includes(actor.name)}
                    selected={actor.crowd_id ? crowdSelected(actor.crowd_id) : selectedKeys.has(`actor:${actor.name}`)}
                    onPick={pick(ref, [actor.position[0], 0, actor.position[1]])}
                  />
                </group>
              );
            })}
            <group userData={{ [HELPER_FLAG]: true }}>
              {plan.cameras.filter(camera => !hidden.includes(`camera:${camera.id}`)).map(camera => (
                <CameraRig
                  key={camera.id} camera={camera} label={lensLabel(camera, plan.shots)}
                  active={camera.id === (lensCameraId || shot?.camera_id)}
                  selected={selectedKeys.has(`camera:${camera.id}`)} targetSelected={selectedKeys.has(`camera-target:${camera.id}`)}
                  onPick={pick({ kind: 'camera', id: camera.id }, camera.position)}
                  onPickTarget={pick({ kind: 'camera-target', id: camera.id }, camera.target)}
                  bodyPointer={pointerFor({ kind: 'camera', id: camera.id })}
                  targetPointer={pointerFor({ kind: 'camera-target', id: camera.id })}
                />
              ))}
            </group>
            {cameraPath && <TrackPath points={cameraPath.points} keys={cameraPath.keys} color="#e6a000" markerSize={0.07} />}
            {actorPaths.filter(path => !hidden.includes(`actor:${path.name}`)).map(path => {
              const actor = actors.find(item => item.name === path.name);
              return actor && <TrackPath key={path.name} points={path.points} keys={path.keys} color={actorColor(actor)} markerSize={0.06} />;
            })}
            {stroke && (
              <group userData={{ [HELPER_FLAG]: true }}>
                {stroke.length >= 2 && <Line points={stroke.map(point => [point[0], FLOOR_LIFT, point[1]] as SpacePoint)} color={SELECTION_COLOR} lineWidth={2} />}
                <mesh position={[stroke[0][0], FLOOR_LIFT, stroke[0][1]]}>
                  <sphereGeometry args={[0.06, 12, 10]} />
                  <meshBasicMaterial color={SELECTION_COLOR} />
                </mesh>
              </group>
            )}
            {focus && actors.filter(actor => actor.name !== focus.name && subjectNames.includes(actor.name)).map(actor => (
              <Ruler key={actor.id} from={[focus.position[0], 0, focus.position[1]]} to={[actor.position[0], 0, actor.position[1]]} color="#e66378" />
            ))}
            {measure.length === 2 && <Ruler from={measure[0].point} to={measure[1].point} color={SELECTION_COLOR} pinned />}
            {measure.map((item, index) => (
              <mesh key={index} position={[item.point[0], Math.max(item.point[1], 0.04), item.point[2]]} userData={{ [HELPER_FLAG]: true }}>
                <sphereGeometry args={[0.06, 12, 10]} />
                <meshBasicMaterial color={SELECTION_COLOR} />
              </mesh>
            ))}
            {posed && posedBase && (
              <PoseHandles
                actor={posed} baseActor={posedBase} shotId={poseShotOnly || overrideFor(shot, posed.name)?.pose ? shot?.shot_id : undefined} footLock={footLock} pointer={handlePointer}
                onDragState={held => { setDragging(held); if (!held) drag.current.endedAt = performance.now(); }}
                onPreview={onPreview} onCommit={onCommit}
              />
            )}
            {mode && primary && anchor && (
              <Gizmo key={`${refKey(primary)}:${mode}`} anchor={anchor} mode={mode} primary={primary} onDragStart={startDrag} onDrag={moveDrag} onDragEnd={endDrag} />
            )}
          </StageLabelLayer>
        </Canvas>
      </ViewportBoundary>
      <div className="desk-viewport__fit">
        <button type="button" className="desk-button" title="把视角对准选中的对象；双击对象也可以" disabled={!selection.length} onClick={frameSelection}>聚焦所选</button>
        <button type="button" className="desk-button" title="把视角退到能看到整个场景" onClick={frameWholeSet}>框选全场</button>
      </div>
      <div className="desk-viewport__hint">
        {tool === 'measure' ? '依次点击两个点或物体，读出它们之间的距离'
          : tool === 'path' ? pathHint()
            : tool === 'pose' ? (posed ? '拖动手腕或脚踝的黄色控制点摆姿势 · 松开后保存' : '选择一个「关节人偶」角色后可拖动手腕与脚踝；人偶类型在右侧「姿势」页切换')
              : '点击选择 · Shift 多选 · 双击对准 · 拖动旋转视角 · 滚轮缩放 · 右键平移'}
      </div>
    </div>
  );
}
