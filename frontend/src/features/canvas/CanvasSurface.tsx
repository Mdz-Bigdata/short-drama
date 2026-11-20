import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type ReactNode } from 'react';

import { t } from '../../i18n';
import { backgroundStyle, type CanvasBackgroundMode } from './canvasBackground';
import { focusPlan } from './canvasFocus';
import { carriedIds, edgeEnds, groupDepth, hiddenMemberIds, snapTargets } from './canvasFrames';
import { EDGE_MARKERS, edgeEmphasis, edgeMarker, type EdgeEmphasis } from './canvasEdgeEmphasis';
import {
  SHELL_ZOOM, SNAP_DISTANCE, boundsOf, centerOn, contains, edgePath, inflate, intersects, nodeAt, normalizeRect, screenToWorld, snapMove, visibleRect, type SnapGuide,
} from './canvasGeometry';
import { roleLabel } from './canvasLabels';
import { lodFor, overviewMode, OVERVIEW_ENTER_ZOOM, OVERVIEW_LEAVE_ZOOM, type NodeLod } from './canvasLod';
import { applySelection, marqueeHits, marqueeMode, selectionStrategy, type MarqueeMode, type SelectionModifiers } from './canvasSelectionModes';
import { buildNodeIndex } from './canvasSpatialIndex';
import type { CanvasEdge, CanvasNode, Rect, Viewport } from './canvasTypes';
import { pauseMedia } from './canvasMedia';
import { cancelVideoPreview } from './canvasVideoPreview';
import { animateView, fitAll, fitSelection, focusRect, VIEW_TRANSITION_MS, zoomStep, zoomTo } from './canvasViewportAnimation';
import { edgesToDraw, visibilityRanges, visibleNodeIds } from './canvasVisibility';
import { applyWheel, createWheelIntentGate, wheelForcesCanvas, wheelIntentTarget } from './canvasWheel';
import { useProgressiveMount } from './useProgressiveMount';
import { useTouchPinch } from './useTouchPinch';

export interface SurfaceHandle {
  getView: () => Viewport;
  size: () => { width: number; height: number };
  /** Jump straight to a view, stopping any transition. */
  setView: (view: Viewport) => void;
  /** Glide to a view; the next wheel, press or touch stops it where it is. */
  animateTo: (view: Viewport) => void;
  /** Show every node, or just these; animated unless `instant`. */
  fit: (ids?: readonly string[], options?: { instant?: boolean }) => void;
  fitRects: (rects: readonly Rect[]) => void;
  zoomStep: (dir: 1 | -1) => void;
  zoomTo: (zoom: number) => void;
  /** Centre a node at once (the outline, the workflow panel). */
  jumpTo: (nodeId: string) => void;
  /** Glide to a node at a readable zoom (a search hit). */
  focusNode: (nodeId: string) => void;
  /** Glide to these rects only when they are not already in sight. */
  reveal: (rects: readonly Rect[]) => void;
  /** World point at the screen centre: where a new node goes. */
  centre: () => { x: number; y: number };
  /** World point under the pointer, when it is over the canvas: where a paste goes. */
  pointer: () => { x: number; y: number } | null;
  subscribe: (listener: (view: Viewport, size: { width: number; height: number }) => void) => () => void;
}

export type DropState = 'ok' | 'no' | null;

export interface NodeRenderProps {
  node: CanvasNode;
  selected: boolean;
  lod: NodeLod;
  dropState: DropState;
}

export interface SurfaceMenuRequest {
  target: 'canvas' | 'node' | 'edge';
  id?: string;
  clientX: number;
  clientY: number;
  world: { x: number; y: number };
}

interface Props {
  nodes: readonly CanvasNode[];
  edges: readonly CanvasEdge[];
  selection: ReadonlySet<string>;
  edgeSelection: ReadonlySet<string>;
  initialView?: Viewport | null;
  background?: CanvasBackgroundMode;
  /** Nodes to highlight for a moment (changed by someone else). */
  flash?: ReadonlySet<string>;
  renderNode: (props: NodeRenderProps) => ReactNode;
  onSelect: (nodes: ReadonlySet<string>, edges: ReadonlySet<string>) => void;
  /** A drag ended: `ids` moved by (dx, dy) world units, released at `point`. */
  onMove: (ids: ReadonlySet<string>, dx: number, dy: number, point: { x: number; y: number } | null) => void;
  onResize: (id: string, width: number, height: number) => void;
  onConnect: (source: string, target: string) => void;
  canConnect: (source: string, target: string) => boolean;
  /** A connection dropped on empty canvas. */
  onConnectEmpty?: (source: string, world: { x: number; y: number }, client: { x: number; y: number }) => void;
  onMenu?: (request: SurfaceMenuRequest) => void;
  onViewSettled?: (view: Viewport) => void;
  onDropFiles?: (files: File[], world: { x: number; y: number }) => void;
  /** The pointer's world position as it moves over the canvas (another window draws it). */
  onLivePointer?: (world: { x: number; y: number }) => void;
  /** Where the nodes being dragged or resized are right now; `null` once the gesture ends. */
  onLiveDrag?: (rects: Array<Rect & { id: string }> | null) => void;
  /** With 'hand', a left drag pans the view; controls on the cards still take their clicks (canvasBeefTool.ts). */
  tool?: 'select' | 'hand';
}

type Gesture =
  | { mode: 'pan'; startX: number; startY: number; view: Viewport }
  | { mode: 'marquee'; startX: number; startY: number; modifiers: SelectionModifiers; base: ReadonlySet<string> }
  | { mode: 'drag'; startX: number; startY: number; ids: Set<string>; box: Rect; others: Rect[]; moved: boolean; collapseTo: string | null }
  | { mode: 'resize'; startX: number; startY: number; id: string; width: number; height: number }
  | { mode: 'connect'; source: string; startX: number; startY: number };

/** What React draws from: the view as it was when the drawn window was last worked out. */
interface RenderFrame {
  view: Viewport;
  width: number;
  height: number;
  overview: boolean;
  /** What was mounted just before: kept while it stays inside the retain range. */
  keep: ReadonlySet<string>;
}

const INTERACTIVE = 'input,textarea,select,button,a,video,audio,label,[data-no-drag]';
const FALLBACK_SIZE = { width: 1200, height: 800 };
const MIN_NODE_WIDTH = 140;
const MIN_NODE_HEIGHT = 80;
const DRAG_THRESHOLD = 3;
/**
 * Screen pixels the view may drift before React works out the drawn window again. A node this close to
 * the screen already counts as on screen, so nothing that comes into view while drifting is a preview.
 */
const SLACK = 96;
/** Zooms where what is drawn, or how much of it, changes: crossing one redraws at once. */
const ZOOM_BANDS = [0.14, OVERVIEW_ENTER_ZOOM, OVERVIEW_LEAVE_ZOOM, 0.28, SHELL_ZOOM];
const NO_IDS: ReadonlySet<string> = new Set();

function typing(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function shiftedBy(node: CanvasNode, dx: number, dy: number): CanvasNode {
  return dx || dy ? { ...node, x: node.x + dx, y: node.y + dy } : node;
}

function grow(rect: Rect, by: number): Rect {
  return { x: rect.x - by, y: rect.y - by, width: rect.width + by * 2, height: rect.height + by * 2 };
}

function zoomBand(zoom: number) {
  return ZOOM_BANDS.filter(level => zoom >= level).length;
}

const EdgeLine = memo(function EdgeLine({ edge, d, selected, emphasis, labelled, midX, midY }: { edge: CanvasEdge; d: string; selected: boolean; emphasis: EdgeEmphasis; labelled: boolean; midX: number; midY: number }) {
  const label = roleLabel(edge.payload.role);
  return (
    <g className={`cn-edge cn-edge--${edge.kind}${selected ? ' is-selected' : ''}${emphasis === 'plain' ? '' : ` is-${emphasis}`}`} data-edge-id={edge.id}>
      <path d={d} className="cn-edge__hit" />
      <path d={d} className="cn-edge__line" markerEnd={`url(#${edgeMarker(edge.kind, selected)})`} />
      {labelled && label && <text x={midX} y={midY - 6} className="cn-edge__label" textAnchor="middle">{label}</text>}
    </g>
  );
});

/**
 * The world: pan and zoom are a CSS transform set directly on one element, so moving the view never
 * re-renders a node. React only hears about it when the drawn window has to change (the view drifted
 * past the slack around what is drawn, or crossed a zoom where nodes change their level of detail).
 * What is drawn comes from a spatial index; off-screen buffer nodes mount a few per frame.
 */
export const CanvasSurface = forwardRef<SurfaceHandle, Props>(function CanvasSurface(
  {
    nodes, edges, selection, edgeSelection, initialView, background = 'dots', flash, renderNode, onSelect, onMove, onResize, onConnect, canConnect,
    onConnectEmpty, onMenu, onViewSettled, onDropFiles, onLivePointer, onLiveDrag, tool = 'select',
  },
  handle,
) {
  const root = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const view = useRef<Viewport>(initialView ?? { x: 0, y: 0, zoom: 1 });
  const painted = useRef<Viewport | null>(null);
  const gesture = useRef<Gesture | null>(null);
  const listeners = useRef(new Set<(view: Viewport, size: { width: number; height: number }) => void>());
  const spaceHeld = useRef(false);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const frame = useRef(0);
  const pendingMove = useRef<PointerEvent | null>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animation = useRef<{ stop: () => void; target: Viewport } | null>(null);
  const settledRef = useRef(onViewSettled);
  const liveRef = useRef({ pointer: onLivePointer, drag: onLiveDrag });
  const liveDragging = useRef(false);
  const backgroundRef = useRef(background);
  const drawnRef = useRef<ReadonlySet<string>>(NO_IDS);
  const [gate] = useState(() => createWheelIntentGate<Element>());
  // The latest position of a gesture, readable on release: its state update may not have landed yet.
  const latest = useRef<{
    drag: { ids: Set<string>; dx: number; dy: number; guides: SnapGuide[] } | null;
    resize: { id: string; width: number; height: number } | null;
    marquee: { rect: Rect; mode: MarqueeMode } | null;
  }>({ drag: null, resize: null, marquee: null });

  const [renderFrame, setRenderFrame] = useState<RenderFrame>(() => ({
    view: view.current, width: FALLBACK_SIZE.width, height: FALLBACK_SIZE.height, overview: overviewMode(view.current.zoom, false), keep: NO_IDS,
  }));
  const frameRef = useRef(renderFrame);
  const [drag, setDrag] = useState<{ ids: Set<string>; dx: number; dy: number; guides: SnapGuide[] } | null>(null);
  const [resize, setResize] = useState<{ id: string; width: number; height: number } | null>(null);
  const [marquee, setMarquee] = useState<{ rect: Rect; mode: MarqueeMode } | null>(null);
  const [draft, setDraft] = useState<{ source: string; x: number; y: number; hover: string | null; ok: boolean } | null>(null);
  const [panning, setPanning] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    settledRef.current = onViewSettled;
    backgroundRef.current = background;
    liveRef.current = { pointer: onLivePointer, drag: onLiveDrag };
  });

  const size = useCallback(() => {
    const element = root.current;
    return element && element.clientWidth > 0 ? { width: element.clientWidth, height: element.clientHeight } : FALLBACK_SIZE;
  }, []);

  const syncWindow = useCallback(() => {
    const { width, height } = size();
    const current = view.current;
    const last = frameRef.current;
    const drifted = width !== last.width || height !== last.height
      || zoomBand(current.zoom) !== zoomBand(last.view.zoom)
      || current.zoom > last.view.zoom * 2
      || !contains(grow(visibleRect(last.view, last.width, last.height), SLACK / last.view.zoom), visibleRect(current, width, height));
    if (!drifted) return;
    const next: RenderFrame = { view: current, width, height, overview: overviewMode(current.zoom, last.overview), keep: drawnRef.current };
    frameRef.current = next;
    setRenderFrame(next);
  }, [size]);

  const paint = useCallback((settled: boolean) => {
    const current = view.current;
    if (world.current) world.current.style.transform = `translate(${current.x}px, ${current.y}px) scale(${current.zoom})`;
    if (backdrop.current) Object.assign(backdrop.current.style, backgroundStyle(backgroundRef.current, current));
    const before = painted.current;
    if (before !== current) {
      // A hover preview belongs to a view that is standing still.
      if (before && (before.x !== current.x || before.y !== current.y || before.zoom !== current.zoom)) cancelVideoPreview();
      painted.current = current;
    }
    const dimensions = size();
    for (const listener of listeners.current) listener(current, dimensions);
    syncWindow();
    if (settled) {
      if (settle.current) clearTimeout(settle.current);
      settle.current = setTimeout(() => settledRef.current?.(view.current), 300);
    }
  }, [size, syncWindow]);

  const stopAnimation = useCallback(() => {
    const running = animation.current;
    animation.current = null;
    running?.stop();
  }, []);

  const setViewNow = useCallback((next: Viewport) => {
    stopAnimation();
    view.current = next;
    paint(true);
  }, [paint, stopAnimation]);

  const animateTo = useCallback((target: Viewport) => {
    stopAnimation();
    const { width, height } = size();
    const now = () => performance.now();
    const running = { stop: () => undefined as void, target };
    animation.current = running;
    running.stop = animateView(view.current, target, VIEW_TRANSITION_MS, next => {
      view.current = next;
      paint(false);
    }, {
      width, height, now,
      // Frames are timed when they run, not by the timestamp handed in (which a fake frame clock may not keep).
      raf: callback => requestAnimationFrame(() => callback(now())),
      onDone: () => {
        if (animation.current === running) animation.current = null;
        paint(true);
      },
    });
  }, [paint, size, stopAnimation]);

  useEffect(() => {
    paint(false);
    if (typeof ResizeObserver === 'undefined' || !root.current) return undefined;
    const observer = new ResizeObserver(() => paint(false));
    observer.observe(root.current);
    return () => observer.disconnect();
  }, [paint]);

  useEffect(() => {
    if (backdrop.current) Object.assign(backdrop.current.style, backgroundStyle(background, view.current));
  }, [background]);

  useEffect(() => () => {
    animation.current?.stop();
    if (settle.current) clearTimeout(settle.current);
  }, []);

  const hidden = useMemo(() => hiddenMemberIds(nodes), [nodes]);
  const shown = useMemo(() => (hidden.size ? nodes.filter(node => !hidden.has(node.id)) : nodes), [hidden, nodes]);
  const nodesRef = useRef(nodes);
  const shownRef = useRef(shown);
  useEffect(() => {
    nodesRef.current = nodes;
    shownRef.current = shown;
  }, [nodes, shown]);

  // The view a glide should start from: where a running glide is heading, so two quick clicks add up.
  const baseView = useCallback(() => animation.current?.target ?? view.current, []);

  useImperativeHandle(handle, () => ({
    getView: () => view.current,
    size,
    setView: setViewNow,
    animateTo,
    fit: (ids, options) => {
      const { width, height } = size();
      const chosen = ids ? shownRef.current.filter(node => ids.includes(node.id)) : shownRef.current;
      const target = ids ? fitSelection(chosen, width, height) : fitAll(chosen, width, height) ?? { x: width / 2, y: height / 2, zoom: 1 };
      if (!target) return;
      if (options?.instant) setViewNow(target);
      else animateTo(target);
    },
    fitRects: rects => {
      const { width, height } = size();
      const target = fitAll(rects, width, height);
      if (target) animateTo(target);
    },
    zoomStep: dir => {
      const { width, height } = size();
      animateTo(zoomStep(baseView(), dir, width, height));
    },
    zoomTo: zoom => {
      const { width, height } = size();
      animateTo(zoomTo(baseView(), zoom, width, height));
    },
    jumpTo: nodeId => {
      const node = nodesRef.current.find(item => item.id === nodeId);
      if (!node) return;
      const { width, height } = size();
      // Far out, a jump would land on a dot: come in to where the node can be read.
      const base = view.current.zoom < 0.6 ? { ...view.current, zoom: 0.8 } : view.current;
      setViewNow(centerOn(node, base, width, height));
    },
    focusNode: nodeId => {
      const node = nodesRef.current.find(item => item.id === nodeId);
      if (!node) return;
      const { width, height } = size();
      animateTo(focusRect(node, view.current, width, height));
    },
    reveal: rects => {
      const { width, height } = size();
      const target = focusPlan(rects, view.current, width, height);
      if (target) animateTo(target);
    },
    centre: () => {
      const { width, height } = size();
      return screenToWorld(view.current, width / 2, height / 2);
    },
    pointer: () => (pointer.current ? screenToWorld(view.current, pointer.current.x, pointer.current.y) : null),
    subscribe: listener => {
      listeners.current.add(listener);
      listener(view.current, size());
      return () => { listeners.current.delete(listener); };
    },
  }), [animateTo, baseView, setViewNow, size]);

  const local = useCallback((event: { clientX: number; clientY: number }) => {
    const box = root.current?.getBoundingClientRect();
    return { x: event.clientX - (box?.left ?? 0), y: event.clientY - (box?.top ?? 0) };
  }, []);

  // React attaches wheel listeners passively, and a passive listener cannot stop the page zooming along.
  useEffect(() => {
    const element = root.current;
    if (!element) return undefined;
    const wheel = (event: WheelEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      // A prompt field only keeps the wheel once it is being typed in: resting the cursor on one must not stop a zoom.
      if (target && (target.closest('[data-no-wheel]') || target === document.activeElement)) return;
      // A scrollable list inside a node scrolls itself only once the pointer has rested on it.
      if (gate.resolve(wheelIntentTarget(target), event, performance.now(), wheelForcesCanvas(event)) === 'scroll') return;
      event.preventDefault();
      stopAnimation();
      const { x, y } = local(event);
      view.current = applyWheel(view.current, event, x, y);
      paint(true);
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [gate, local, paint, stopAnimation]);

  const touchView = useCallback(() => view.current, []);
  const touchSet = useCallback((next: Viewport) => {
    stopAnimation();
    view.current = next;
    paint(true);
  }, [paint, stopAnimation]);
  useTouchPinch(root, touchView, touchSet);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || typing(event.target) || event.target instanceof HTMLButtonElement) return;
      event.preventDefault();
      spaceHeld.current = true;
      setPanning(true);
    };
    const up = (event: KeyboardEvent) => {
      if (event.code !== 'Space') return;
      spaceHeld.current = false;
      setPanning(false);
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, []);

  // Panning is not a moment to watch: whatever plays on a card stops (the cards also stop taking clicks, in CSS).
  useEffect(() => { if (panning) pauseMedia(root.current); }, [panning]);

  const capture = (event: React.PointerEvent) => {
    try {
      root.current?.setPointerCapture?.(event.pointerId);
    } catch {
      // A synthetic pointer has nothing to capture; the gesture still works while it stays inside.
    }
  };

  const endGesture = useCallback(() => {
    root.current?.parentElement?.removeAttribute('data-canvas-dragging');
    gesture.current = null;
    pendingMove.current = null;
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = 0;
    latest.current = { drag: null, resize: null, marquee: null };
    if (liveDragging.current) {
      liveDragging.current = false;
      liveRef.current.drag?.(null);
    }
    setDrag(null);
    setResize(null);
    setMarquee(null);
    setDraft(null);
    setPanning(spaceHeld.current);
  }, []);

  const reportLive = useCallback((rects: Array<Rect & { id: string }>) => {
    if (!liveRef.current.drag) return;
    liveDragging.current = true;
    liveRef.current.drag(rects);
  }, []);

  const handleMove = useCallback((event: PointerEvent) => {
    const current = gesture.current;
    if (!current) return;
    const at = local(event);
    const zoom = view.current.zoom;
    if (current.mode === 'pan') {
      view.current = { ...current.view, x: current.view.x + event.clientX - current.startX, y: current.view.y + event.clientY - current.startY };
      paint(true);
    } else if (current.mode === 'marquee') {
      latest.current.marquee = { rect: normalizeRect(current.startX, current.startY, at.x, at.y), mode: marqueeMode(current.startX, at.x) };
      setMarquee(latest.current.marquee);
    } else if (current.mode === 'drag') {
      let dx = (event.clientX - current.startX) / zoom;
      let dy = (event.clientY - current.startY) / zoom;
      if (!current.moved && Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < DRAG_THRESHOLD) return;
      // 拖动中多选工具栏先藏起来：它跟着文档位置走，拖完落定再出现在新位置，不会悬在旧地方。
      if (!current.moved) root.current?.parentElement?.setAttribute('data-canvas-dragging', '');
      current.moved = true;
      let guides: SnapGuide[] = [];
      if (!event.altKey) {
        const snapped = snapMove({ ...current.box, x: current.box.x + dx, y: current.box.y + dy }, current.others, SNAP_DISTANCE / zoom);
        dx += snapped.dx;
        dy += snapped.dy;
        guides = snapped.guides;
      }
      latest.current.drag = { ids: current.ids, dx, dy, guides };
      setDrag(latest.current.drag);
      reportLive(nodesRef.current.filter(node => current.ids.has(node.id)).map(node => ({ id: node.id, x: node.x + dx, y: node.y + dy, width: node.width, height: node.height })));
    } else if (current.mode === 'resize') {
      latest.current.resize = {
        id: current.id,
        width: Math.max(MIN_NODE_WIDTH, current.width + (event.clientX - current.startX) / zoom),
        height: Math.max(MIN_NODE_HEIGHT, current.height + (event.clientY - current.startY) / zoom),
      };
      setResize(latest.current.resize);
      const node = nodesRef.current.find(item => item.id === current.id);
      if (node) reportLive([{ id: node.id, x: node.x, y: node.y, width: latest.current.resize.width, height: latest.current.resize.height }]);
    } else if (current.mode === 'connect') {
      const point = screenToWorld(view.current, at.x, at.y);
      const over = nodeAt(shownRef.current, point.x, point.y, new Set([current.source]));
      const hover = over && over.kind !== 'group' ? over.id : null;
      setDraft({ source: current.source, x: point.x, y: point.y, hover, ok: hover ? canConnect(current.source, hover) : false });
    }
  }, [canConnect, local, paint, reportLive]);

  const index = useMemo(() => buildNodeIndex(nodes), [nodes]);
  const byId = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    if (!target.closest(INTERACTIVE)) root.current?.focus({ preventScroll: true });
    stopAnimation();
    if (gesture.current) return;
    if (event.button === 1 || (event.button === 0 && (spaceHeld.current || (tool === 'hand' && !target.closest(INTERACTIVE))))) {
      event.preventDefault();
      capture(event);
      gesture.current = { mode: 'pan', startX: event.clientX, startY: event.clientY, view: view.current };
      setPanning(true);
      return;
    }
    if (event.button !== 0) return;
    const port = target.closest('[data-port="out"]');
    const owner = target.closest<HTMLElement>('[data-node-id]');
    if (port && owner) {
      event.preventDefault();
      event.stopPropagation();
      capture(event);
      gesture.current = { mode: 'connect', source: owner.dataset.nodeId!, startX: event.clientX, startY: event.clientY };
      return;
    }
    const resizeHandle = target.closest('[data-resize]');
    if (resizeHandle && owner) {
      const node = nodesRef.current.find(item => item.id === owner.dataset.nodeId);
      if (!node) return;
      event.preventDefault();
      capture(event);
      gesture.current = { mode: 'resize', startX: event.clientX, startY: event.clientY, id: node.id, width: node.width, height: node.height };
      return;
    }
    const edgeElement = target.closest<SVGElement>('[data-edge-id]');
    if (edgeElement && !owner) {
      const edgeId = edgeElement.dataset.edgeId!;
      const next = new Set(event.shiftKey ? edgeSelection : []);
      if (next.has(edgeId)) next.delete(edgeId);
      else next.add(edgeId);
      onSelect(event.shiftKey ? selection : new Set(), next);
      return;
    }
    if (owner) {
      const id = owner.dataset.nodeId!;
      const interactive = Boolean(target.closest(INTERACTIVE));
      let nextSelection: Set<string> = new Set(selection);
      let collapseTo: string | null = null;
      if (event.shiftKey || event.metaKey || event.ctrlKey) {
        if (nextSelection.has(id)) nextSelection.delete(id);
        else nextSelection.add(id);
      } else if (!nextSelection.has(id)) {
        nextSelection = new Set([id]);
      } else if (nextSelection.size > 1) {
        // A click (no drag) on one of several selected nodes narrows to it; decided on release.
        collapseTo = id;
      }
      onSelect(nextSelection, new Set());
      if (interactive || !nextSelection.has(id)) return;
      capture(event);
      const ids = carriedIds(nodesRef.current, nextSelection);
      const moving = nodesRef.current.filter(node => ids.has(node.id));
      const { width, height } = size();
      const near = inflate(visibleRect(view.current, width, height), 0.25);
      gesture.current = {
        mode: 'drag', startX: event.clientX, startY: event.clientY, ids,
        box: boundsOf(moving) ?? { x: 0, y: 0, width: 0, height: 0 },
        others: snapTargets(nodesRef.current, ids).filter(node => intersects(node, near)),
        moved: false, collapseTo,
      };
      return;
    }
    capture(event);
    const at = local(event);
    const modifiers: SelectionModifiers = { shift: event.shiftKey, alt: event.altKey, meta: event.metaKey, ctrl: event.ctrlKey };
    const replace = selectionStrategy(modifiers) === 'replace';
    gesture.current = { mode: 'marquee', startX: at.x, startY: at.y, modifiers, base: replace ? new Set() : selection };
    if (replace) onSelect(new Set(), new Set());
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    pointer.current = local(event);
    liveRef.current.pointer?.(screenToWorld(view.current, pointer.current.x, pointer.current.y));
    gate.move(wheelIntentTarget(event.target instanceof Element ? event.target : null), event, performance.now());
    if (!gesture.current) return;
    // Pointer events outrun frames, and every frame of a drag costs a render.
    pendingMove.current = event.nativeEvent;
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const pending = pendingMove.current;
      if (pending) handleMove(pending);
    });
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (!current) return;
    // The last position counts even if no frame was drawn for it.
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = 0;
    handleMove(event.nativeEvent);
    const { drag: dragged, resize: resized, marquee: area } = latest.current;
    const at = local(event);
    const point = screenToWorld(view.current, at.x, at.y);
    if (current.mode === 'drag') {
      if (current.moved && dragged) onMove(dragged.ids, dragged.dx, dragged.dy, point);
      else if (current.collapseTo) onSelect(new Set([current.collapseTo]), new Set());
    } else if (current.mode === 'marquee') {
      if (area && (area.rect.width > 2 || area.rect.height > 2)) {
        const a = screenToWorld(view.current, area.rect.x, area.rect.y);
        const b = screenToWorld(view.current, area.rect.x + area.rect.width, area.rect.y + area.rect.height);
        const box = normalizeRect(a.x, a.y, b.x, b.y);
        // Dragged rightwards it takes what it wholly holds, leftwards whatever it touches; a group only when wholly inside.
        const hits = marqueeHits({ candidates: rect => index.query(rect).map(id => byId.get(id)!) }, box, area.mode, hidden);
        onSelect(applySelection(current.base, hits, current.modifiers), new Set());
      }
    } else if (current.mode === 'resize') {
      if (resized) onResize(resized.id, resized.width, resized.height);
    } else if (current.mode === 'connect') {
      const over = nodeAt(shownRef.current, point.x, point.y, new Set([current.source]));
      if (over && over.kind !== 'group') onConnect(current.source, over.id);
      else if (onConnectEmpty && Math.hypot(event.clientX - current.startX, event.clientY - current.startY) > DRAG_THRESHOLD * 2) {
        onConnectEmpty(current.source, point, { x: event.clientX, y: event.clientY });
      }
    }
    endGesture();
  };

  // Escape, or the browser taking the pointer away, ends a gesture without committing it.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && gesture.current) {
        event.stopPropagation();
        endGesture();
      }
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [endGesture]);

  // ------------------------------------------------------------ what to draw

  const draggedIds = drag?.ids;
  const resizedId = resize?.id;
  const forced = useMemo(() => {
    const ids = new Set(selection);
    draggedIds?.forEach(id => ids.add(id));
    if (resizedId) ids.add(resizedId);
    if (editingId) ids.add(editingId);
    return ids;
  }, [draggedIds, editingId, resizedId, selection]);

  const { view: frameView, width: frameWidth, height: frameHeight, overview, keep } = renderFrame;
  const ranges = useMemo(() => visibilityRanges(frameView, frameWidth, frameHeight), [frameHeight, frameView, frameWidth]);
  const lodView = useMemo(() => grow(ranges.view, SLACK / frameView.zoom), [frameView.zoom, ranges.view]);
  const candidates = useMemo(() => visibleNodeIds({
    index, nodes, view: frameView, width: frameWidth, height: frameHeight, mounted: keep, forced, hidden,
  }), [forced, frameHeight, frameView, frameWidth, hidden, index, keep, nodes]);
  const immediate = useMemo(() => new Set(candidates.filter(id => forced.has(id) || intersects(byId.get(id)!, lodView))), [byId, candidates, forced, lodView]);
  const rectOf = useCallback((id: string) => index.rectOf(id), [index]);
  const mounted = useProgressiveMount(candidates, immediate, rectOf, ranges.view);
  useEffect(() => { drawnRef.current = mounted.mounted; }, [mounted]);

  const depths = useMemo(() => {
    const result = new Map<string, number>();
    for (const node of nodes) if (node.kind === 'group') result.set(node.id, groupDepth(nodes, node.id));
    return result;
  }, [nodes]);

  const drawn = useMemo(() => {
    const list = mounted.ids.map(id => byId.get(id)!).filter(Boolean);
    // Frames first, outer ones before those nested in them, so a frame stays behind what it holds.
    const groups = list.filter(node => node.kind === 'group').sort((a, b) => (depths.get(a.id) ?? 0) - (depths.get(b.id) ?? 0));
    return [...groups, ...list.filter(node => node.kind !== 'group')];
  }, [byId, depths, mounted.ids]);

  const place = useCallback((node: CanvasNode): CanvasNode => {
    const moved = drag?.ids.has(node.id) ? shiftedBy(node, drag.dx, drag.dy) : node;
    return resize?.id === node.id ? { ...moved, width: resize.width, height: resize.height } : moved;
  }, [drag, resize]);

  // An edge into a collapsed group's member is drawn to the group; two edges folding onto one pair draw once.
  const routed = useMemo(() => {
    if (!hidden.size) return edges;
    const seen = new Set<string>();
    const out: CanvasEdge[] = [];
    for (const edge of edges) {
      if (!hidden.has(edge.source) && !hidden.has(edge.target)) {
        out.push(edge);
        continue;
      }
      const ends = edgeEnds(nodes, edge);
      if (!ends) continue;
      const key = `${ends.source}\u0000${ends.target}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ...edge, source: ends.source, target: ends.target });
    }
    return out;
  }, [edges, hidden, nodes]);

  const edgeLines = useMemo(() => {
    const placedRect = (id: string) => {
      const node = byId.get(id);
      return node ? place(node) : undefined;
    };
    return edgesToDraw(routed, mounted.mounted, placedRect, frameView, frameWidth, frameHeight).map(edge => {
      const a = placedRect(edge.source)!;
      const b = placedRect(edge.target)!;
      const ax = a.x + a.width;
      const ay = a.y + a.height / 2;
      const bx = b.x;
      const by = b.y + b.height / 2;
      return { edge, d: edgePath(ax, ay, bx, by), midX: (ax + bx) / 2, midY: (ay + by) / 2 };
    });
  }, [byId, frameHeight, frameView, frameWidth, mounted.mounted, place, routed]);

  const draftLine = useMemo(() => {
    if (!draft) return '';
    const source = byId.get(draft.source);
    return source ? edgePath(source.x + source.width, source.y + source.height / 2, draft.x, draft.y) : '';
  }, [byId, draft]);

  const zoom = frameView.zoom;
  const lodOf = (node: CanvasNode): NodeLod => lodFor(node, {
    zoom,
    inView: intersects(node, lodView),
    inEnter: intersects(node, ranges.enter),
    editing: editingId === node.id,
    hovered: hoverId === node.id,
    active: selection.has(node.id) || Boolean(draggedIds?.has(node.id)) || resizedId === node.id,
    overviewWas: overview,
  });

  const nodeIdAt = (target: EventTarget | null) => (target instanceof Element ? target.closest<HTMLElement>('[data-node-id]')?.dataset.nodeId ?? null : null);

  return (
    <div
      ref={root}
      className={`cn-surface${panning ? ' is-panning' : ''}${tool === 'hand' ? ' is-hand' : ''}`}
      tabIndex={0}
      role="application"
      aria-label={t('节点画布')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={endGesture}
      onPointerLeave={() => { pointer.current = null; }}
      onPointerOver={event => {
        // Hovering only changes what is drawn below the zoom where cards turn into previews.
        const id = zoom < SHELL_ZOOM ? nodeIdAt(event.target) : null;
        if (id !== hoverId) setHoverId(id);
      }}
      onFocus={event => {
        const id = typing(event.target) ? nodeIdAt(event.target) : null;
        if (id !== editingId) setEditingId(id);
      }}
      onBlur={event => {
        if (editingId && nodeIdAt(event.relatedTarget) !== editingId) setEditingId(null);
      }}
      onContextMenu={event => {
        if (gesture.current) {
          event.preventDefault();
          return;
        }
        // A text field keeps the browser's own menu (copy, paste, spelling).
        if (typing(event.target)) return;
        event.preventDefault();
        if (!onMenu) return;
        const target = event.target as Element;
        const at = local(event);
        const point = screenToWorld(view.current, at.x, at.y);
        const owner = target.closest<HTMLElement>('[data-node-id]');
        const edgeElement = owner ? null : target.closest<SVGElement>('[data-edge-id]');
        onMenu({
          target: owner ? 'node' : edgeElement ? 'edge' : 'canvas',
          id: owner?.dataset.nodeId ?? edgeElement?.dataset.edgeId,
          clientX: event.clientX, clientY: event.clientY, world: point,
        });
      }}
      onDragOver={event => { if (onDropFiles) event.preventDefault(); }}
      onDrop={event => {
        if (!onDropFiles || !event.dataTransfer.files.length) return;
        event.preventDefault();
        const at = local(event);
        onDropFiles([...event.dataTransfer.files], screenToWorld(view.current, at.x, at.y));
      }}
    >
      <div ref={backdrop} className="cn-backdrop" aria-hidden="true" />
      <div ref={world} className="cn-world">
        <svg className="cn-edges" aria-hidden="true">
          <defs>
            {/* Arrowheads, in world units so they grow and shrink with the cards they point at. The tip stops short of
                the line's end (refX past the tip): the end lies under the target's input port, and the head must not. */}
            {EDGE_MARKERS.map(id => (
              <marker key={id} id={id} className={`cn-arrow ${id}`} viewBox="0 0 10 10" refX="17" refY="5" markerWidth="11" markerHeight="11" markerUnits="userSpaceOnUse" orient="auto">
                <path d="M 0 1 L 10 5 L 0 9 z" />
              </marker>
            ))}
          </defs>
          {edgeLines.map(line => (
            <EdgeLine
              key={line.edge.id} edge={line.edge} d={line.d} midX={line.midX} midY={line.midY} selected={edgeSelection.has(line.edge.id)}
              emphasis={edgeEmphasis(line.edge, selection, edgeSelection)} labelled={zoom >= SHELL_ZOOM}
            />
          ))}
          {draftLine && <path d={draftLine} className={`cn-edge__draft${draft?.hover ? (draft.ok ? ' is-ok' : ' is-no') : ''}`} />}
        </svg>
        {drawn.map(node => {
          const placed = place(node);
          const group = node.kind === 'group';
          return (
            <div
              key={node.id}
              className={`cn-frame${group ? ' cn-frame--group' : ''}${group && node.payload.collapsed ? ' is-collapsed' : ''}${flash?.has(node.id) ? ' cn-flash' : ''}`}
              style={{ transform: `translate(${placed.x}px, ${placed.y}px)`, width: placed.width, height: placed.height }}
              data-node-id={node.id}
              data-testid={`node-${node.id}`}
            >
              {renderNode({ node, selected: selection.has(node.id), lod: lodOf(node), dropState: draft?.hover === node.id ? (draft.ok ? 'ok' : 'no') : null })}
            </div>
          );
        })}
        {drag?.guides.map(guide => (
          <div
            key={`${guide.axis}${guide.at}`}
            className={`cn-guide cn-guide--${guide.axis}`}
            style={guide.axis === 'x'
              ? { transform: `translate(${guide.at}px, ${guide.from}px)`, height: guide.to - guide.from }
              : { transform: `translate(${guide.from}px, ${guide.at}px)`, width: guide.to - guide.from }}
          />
        ))}
      </div>
      {marquee && (
        <div
          className={`cn-marquee${marquee.mode === 'intersect' ? ' is-intersect' : ''}`}
          style={{ left: marquee.rect.x, top: marquee.rect.y, width: marquee.rect.width, height: marquee.rect.height }}
        />
      )}
      {!nodes.length && (
        <p className="cn-empty">{t('从左侧添加节点，或把文件拖到这里。')}</p>
      )}
    </div>
  );
});

