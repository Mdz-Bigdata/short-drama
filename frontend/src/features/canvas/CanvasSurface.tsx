import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type ReactNode } from 'react';

import { t } from '../../i18n';
import {
  SHELL_ZOOM, SNAP_DISTANCE, boundsOf, centerOn, contains, edgePath, fitView, inflate, intersects, nodeAt, normalizeRect, screenToWorld, snapMove, visibleRect, zoomAt, type SnapGuide,
} from './canvasGeometry';
import { movingIds } from './canvasGraph';
import { roleLabel } from './canvasLabels';
import type { CanvasEdge, CanvasNode, Rect, Viewport } from './canvasTypes';

export interface SurfaceHandle {
  getView: () => Viewport;
  size: () => { width: number; height: number };
  setView: (view: Viewport) => void;
  fit: (ids?: readonly string[]) => void;
  jumpTo: (nodeId: string) => void;
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
  shell: boolean;
  dropState: DropState;
}

interface Props {
  nodes: readonly CanvasNode[];
  edges: readonly CanvasEdge[];
  selection: ReadonlySet<string>;
  edgeSelection: ReadonlySet<string>;
  initialView?: Viewport | null;
  renderNode: (props: NodeRenderProps) => ReactNode;
  onSelect: (nodes: ReadonlySet<string>, edges: ReadonlySet<string>) => void;
  onMove: (ids: ReadonlySet<string>, dx: number, dy: number) => void;
  onResize: (id: string, width: number, height: number) => void;
  onConnect: (source: string, target: string) => void;
  canConnect: (source: string, target: string) => boolean;
  onViewSettled?: (view: Viewport) => void;
  onDropFiles?: (files: File[], world: { x: number; y: number }) => void;
}

type Gesture =
  | { mode: 'pan'; startX: number; startY: number; view: Viewport }
  | { mode: 'marquee'; startX: number; startY: number; additive: boolean }
  | { mode: 'drag'; startX: number; startY: number; ids: Set<string>; box: Rect; others: Rect[]; moved: boolean; collapseTo: string | null }
  | { mode: 'resize'; startX: number; startY: number; id: string; width: number; height: number }
  | { mode: 'connect'; source: string };

const INTERACTIVE = 'input,textarea,select,button,a,video,audio,label,[data-no-drag]';
const FALLBACK_SIZE = { width: 1200, height: 800 };
const MIN_NODE_WIDTH = 140;
const MIN_NODE_HEIGHT = 80;
const DRAG_THRESHOLD = 3;

function typing(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function shiftedBy(node: CanvasNode, dx: number, dy: number): CanvasNode {
  return dx || dy ? { ...node, x: node.x + dx, y: node.y + dy } : node;
}

const EdgeLine = memo(function EdgeLine({ edge, d, selected, labelled, midX, midY }: { edge: CanvasEdge; d: string; selected: boolean; labelled: boolean; midX: number; midY: number }) {
  const label = roleLabel(edge.payload.role);
  return (
    <g className={`cn-edge cn-edge--${edge.kind}${selected ? ' is-selected' : ''}`} data-edge-id={edge.id}>
      <path d={d} className="cn-edge__hit" />
      <path d={d} className="cn-edge__line" />
      {labelled && label && <text x={midX} y={midY - 6} className="cn-edge__label" textAnchor="middle">{label}</text>}
    </g>
  );
});

/**
 * The world: pan and zoom are a CSS transform set directly on one element, so moving the view never
 * re-renders a node. React only hears about it when the rendered window has to change (the view left
 * the margin around what is drawn, or crossed the zoom where bodies become shells).
 */
export const CanvasSurface = forwardRef<SurfaceHandle, Props>(function CanvasSurface(
  { nodes, edges, selection, edgeSelection, initialView, renderNode, onSelect, onMove, onResize, onConnect, canConnect, onViewSettled, onDropFiles },
  handle,
) {
  const root = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const view = useRef<Viewport>(initialView ?? { x: 0, y: 0, zoom: 1 });
  const gesture = useRef<Gesture | null>(null);
  const listeners = useRef(new Set<(view: Viewport, size: { width: number; height: number }) => void>());
  const spaceHeld = useRef(false);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const frame = useRef(0);
  const pendingMove = useRef<PointerEvent | null>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The latest position of a gesture, readable on release: its state update may not have landed yet.
  const latest = useRef<{
    drag: { ids: Set<string>; dx: number; dy: number; guides: SnapGuide[] } | null;
    resize: { id: string; width: number; height: number } | null;
    marquee: Rect | null;
  }>({ drag: null, resize: null, marquee: null });

  const [windowRect, setWindowRect] = useState<Rect>(() => inflate(visibleRect(view.current, FALLBACK_SIZE.width, FALLBACK_SIZE.height), 0.5));
  const [shell, setShell] = useState(() => view.current.zoom < SHELL_ZOOM);
  const [drag, setDrag] = useState<{ ids: Set<string>; dx: number; dy: number; guides: SnapGuide[] } | null>(null);
  const [resize, setResize] = useState<{ id: string; width: number; height: number } | null>(null);
  const [marquee, setMarquee] = useState<Rect | null>(null);
  const [draft, setDraft] = useState<{ source: string; x: number; y: number; hover: string | null; ok: boolean } | null>(null);
  const [panning, setPanning] = useState(false);

  const size = useCallback(() => {
    const element = root.current;
    return element && element.clientWidth > 0 ? { width: element.clientWidth, height: element.clientHeight } : FALLBACK_SIZE;
  }, []);

  const syncWindow = useCallback(() => {
    const { width, height } = size();
    const visible = visibleRect(view.current, width, height);
    setWindowRect(current => (
      contains(current, visible) && current.width <= visible.width * 4 ? current : inflate(visible, 0.5)
    ));
    setShell(view.current.zoom < SHELL_ZOOM);
  }, [size]);

  const paint = useCallback((settled: boolean) => {
    const current = view.current;
    if (world.current) world.current.style.transform = `translate(${current.x}px, ${current.y}px) scale(${current.zoom})`;
    if (root.current) {
      root.current.style.backgroundPosition = `${current.x}px ${current.y}px`;
      root.current.style.backgroundSize = `${28 * current.zoom}px ${28 * current.zoom}px`;
      root.current.dataset.grid = current.zoom < 0.25 ? 'off' : 'on';
    }
    const dimensions = size();
    for (const listener of listeners.current) listener(current, dimensions);
    syncWindow();
    if (settled) {
      if (settle.current) clearTimeout(settle.current);
      settle.current = setTimeout(() => onViewSettled?.(view.current), 300);
    }
  }, [onViewSettled, size, syncWindow]);

  const setViewNow = useCallback((next: Viewport) => {
    view.current = next;
    paint(true);
  }, [paint]);

  useEffect(() => {
    paint(false);
    if (typeof ResizeObserver === 'undefined' || !root.current) return undefined;
    const observer = new ResizeObserver(() => paint(false));
    observer.observe(root.current);
    return () => observer.disconnect();
  }, [paint]);

  const nodesRef = useRef(nodes);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);

  useImperativeHandle(handle, () => ({
    getView: () => view.current,
    size,
    setView: setViewNow,
    fit: ids => {
      const chosen = ids ? nodesRef.current.filter(node => ids.includes(node.id)) : nodesRef.current;
      const box = boundsOf(chosen);
      const { width, height } = size();
      setViewNow(box ? fitView(box, width, height) : { x: width / 2, y: height / 2, zoom: 1 });
    },
    jumpTo: nodeId => {
      const node = nodesRef.current.find(item => item.id === nodeId);
      if (!node) return;
      const { width, height } = size();
      // Far out, a jump would land on a dot: come in to where the node can be read.
      const base = view.current.zoom < 0.6 ? { ...view.current, zoom: 0.8 } : view.current;
      setViewNow(centerOn(node, base, width, height));
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
  }), [setViewNow, size]);

  const local = useCallback((event: { clientX: number; clientY: number }) => {
    const box = root.current?.getBoundingClientRect();
    return { x: event.clientX - (box?.left ?? 0), y: event.clientY - (box?.top ?? 0) };
  }, []);

  // React attaches wheel listeners passively, and a passive listener cannot stop the page zooming along.
  useEffect(() => {
    const element = root.current;
    if (!element) return undefined;
    const wheel = (event: WheelEvent) => {
      // A prompt field only keeps the wheel once it is being typed in: resting the cursor on one must not stop a zoom.
      if (event.target instanceof Element && (event.target.closest('[data-no-wheel]') || event.target === document.activeElement)) return;
      event.preventDefault();
      const { x, y } = local(event);
      // A mouse wheel moves in big straight notches; a trackpad scrolls in small two-axis steps and pans.
      const wantsZoom = event.ctrlKey || event.metaKey || (event.deltaX === 0 && Number.isInteger(event.deltaY) && Math.abs(event.deltaY) >= 50);
      if (wantsZoom) {
        view.current = zoomAt(view.current, x, y, Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015)));
      } else {
        view.current = { ...view.current, x: view.current.x - event.deltaX, y: view.current.y - event.deltaY };
      }
      paint(true);
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [local, paint]);

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

  const capture = (event: React.PointerEvent) => {
    try {
      root.current?.setPointerCapture?.(event.pointerId);
    } catch {
      // A synthetic pointer has nothing to capture; the gesture still works while it stays inside.
    }
  };

  const endGesture = useCallback(() => {
    gesture.current = null;
    pendingMove.current = null;
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = 0;
    latest.current = { drag: null, resize: null, marquee: null };
    setDrag(null);
    setResize(null);
    setMarquee(null);
    setDraft(null);
    setPanning(spaceHeld.current);
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
      latest.current.marquee = normalizeRect(current.startX, current.startY, at.x, at.y);
      setMarquee(latest.current.marquee);
    } else if (current.mode === 'drag') {
      let dx = (event.clientX - current.startX) / zoom;
      let dy = (event.clientY - current.startY) / zoom;
      if (!current.moved && Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < DRAG_THRESHOLD) return;
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
    } else if (current.mode === 'resize') {
      latest.current.resize = {
        id: current.id,
        width: Math.max(MIN_NODE_WIDTH, current.width + (event.clientX - current.startX) / zoom),
        height: Math.max(MIN_NODE_HEIGHT, current.height + (event.clientY - current.startY) / zoom),
      };
      setResize(latest.current.resize);
    } else if (current.mode === 'connect') {
      const point = screenToWorld(view.current, at.x, at.y);
      const over = nodeAt(nodesRef.current, point.x, point.y, new Set([current.source]));
      const hover = over && over.kind !== 'group' ? over.id : null;
      setDraft({ source: current.source, x: point.x, y: point.y, hover, ok: hover ? canConnect(current.source, hover) : false });
    }
  }, [canConnect, local, paint]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    if (!target.closest(INTERACTIVE)) root.current?.focus({ preventScroll: true });
    if (gesture.current) return;
    if (event.button === 1 || (event.button === 0 && spaceHeld.current)) {
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
      gesture.current = { mode: 'connect', source: owner.dataset.nodeId! };
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
      if (event.shiftKey) {
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
      const ids = movingIds(nodesRef.current, nextSelection);
      const moving = nodesRef.current.filter(node => ids.has(node.id));
      const { width, height } = size();
      const near = inflate(visibleRect(view.current, width, height), 0.25);
      gesture.current = {
        mode: 'drag', startX: event.clientX, startY: event.clientY, ids,
        box: boundsOf(moving) ?? { x: 0, y: 0, width: 0, height: 0 },
        others: nodesRef.current.filter(node => !ids.has(node.id) && intersects(node, near)),
        moved: false, collapseTo,
      };
      return;
    }
    capture(event);
    const at = local(event);
    gesture.current = { mode: 'marquee', startX: at.x, startY: at.y, additive: event.shiftKey };
    if (!event.shiftKey) onSelect(new Set(), new Set());
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    pointer.current = local(event);
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
    if (current.mode === 'drag') {
      if (current.moved && dragged) onMove(dragged.ids, dragged.dx, dragged.dy);
      else if (current.collapseTo) onSelect(new Set([current.collapseTo]), new Set());
    } else if (current.mode === 'marquee') {
      if (area && (area.width > 2 || area.height > 2)) {
        const a = screenToWorld(view.current, area.x, area.y);
        const b = screenToWorld(view.current, area.x + area.width, area.y + area.height);
        const box = normalizeRect(a.x, a.y, b.x, b.y);
        // A group joins only when wholly inside: a marquee drawn within a frame means its contents.
        const hit = nodesRef.current.filter(node => (node.kind === 'group' ? contains(box, node) : intersects(box, node))).map(node => node.id);
        onSelect(new Set(current.additive ? [...selection, ...hit] : hit), new Set());
      }
    } else if (current.mode === 'resize') {
      if (resized) onResize(resized.id, resized.width, resized.height);
    } else if (current.mode === 'connect') {
      const at = local(event);
      const point = screenToWorld(view.current, at.x, at.y);
      const over = nodeAt(nodesRef.current, point.x, point.y, new Set([current.source]));
      if (over && over.kind !== 'group') onConnect(current.source, over.id);
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

  const byId = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes]);
  const draggedIds = drag?.ids;
  const drawn = useMemo(() => {
    const list = nodes.filter(node => selection.has(node.id) || draggedIds?.has(node.id) || intersects(node, windowRect));
    return [...list.filter(node => node.kind === 'group'), ...list.filter(node => node.kind !== 'group')];
  }, [draggedIds, nodes, selection, windowRect]);

  const place = useCallback((node: CanvasNode): CanvasNode => {
    const moved = drag?.ids.has(node.id) ? shiftedBy(node, drag.dx, drag.dy) : node;
    return resize?.id === node.id ? { ...moved, width: resize.width, height: resize.height } : moved;
  }, [drag, resize]);

  const edgeLines = useMemo(() => edges.flatMap(edge => {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target) return [];
    const a = place(source);
    const b = place(target);
    const ax = a.x + a.width;
    const ay = a.y + a.height / 2;
    const bx = b.x;
    const by = b.y + b.height / 2;
    const box = normalizeRect(ax, ay, bx, by);
    if (!intersects({ x: box.x - 60, y: box.y - 60, width: box.width + 120, height: box.height + 120 }, windowRect)) return [];
    return [{ edge, d: edgePath(ax, ay, bx, by), midX: (ax + bx) / 2, midY: (ay + by) / 2 }];
  }), [byId, edges, place, windowRect]);

  const draftLine = useMemo(() => {
    if (!draft) return '';
    const source = byId.get(draft.source);
    return source ? edgePath(source.x + source.width, source.y + source.height / 2, draft.x, draft.y) : '';
  }, [byId, draft]);

  return (
    <div
      ref={root}
      className={`cn-surface${panning ? ' is-panning' : ''}`}
      tabIndex={0}
      role="application"
      aria-label={t('节点画布')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={endGesture}
      onPointerLeave={() => { pointer.current = null; }}
      onContextMenu={event => { if (gesture.current) event.preventDefault(); }}
      onDragOver={event => { if (onDropFiles) event.preventDefault(); }}
      onDrop={event => {
        if (!onDropFiles || !event.dataTransfer.files.length) return;
        event.preventDefault();
        const at = local(event);
        onDropFiles([...event.dataTransfer.files], screenToWorld(view.current, at.x, at.y));
      }}
    >
      <div ref={world} className="cn-world">
        <svg className="cn-edges" aria-hidden="true">
          {edgeLines.map(line => (
            <EdgeLine key={line.edge.id} edge={line.edge} d={line.d} midX={line.midX} midY={line.midY} selected={edgeSelection.has(line.edge.id)} labelled={!shell} />
          ))}
          {draftLine && <path d={draftLine} className={`cn-edge__draft${draft?.hover ? (draft.ok ? ' is-ok' : ' is-no') : ''}`} />}
        </svg>
        {drawn.map(node => {
          const placed = place(node);
          return (
            <div
              key={node.id}
              className={`cn-frame${node.kind === 'group' ? ' cn-frame--group' : ''}`}
              style={{ transform: `translate(${placed.x}px, ${placed.y}px)`, width: placed.width, height: placed.height }}
              data-node-id={node.id}
              data-testid={`node-${node.id}`}
            >
              {renderNode({ node, selected: selection.has(node.id), shell, dropState: draft?.hover === node.id ? (draft.ok ? 'ok' : 'no') : null })}
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
      {marquee && <div className="cn-marquee" style={{ left: marquee.x, top: marquee.y, width: marquee.width, height: marquee.height }} />}
      {!nodes.length && (
        <p className="cn-empty">{t('从左侧添加节点，或把文件拖到这里。')}</p>
      )}
    </div>
  );
});
