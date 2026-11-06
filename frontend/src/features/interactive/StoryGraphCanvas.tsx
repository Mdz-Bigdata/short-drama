import { CornerDownRight, Flag, Focus, Image as ImageIcon, Lock, Plus, Timer, TriangleAlert, Video, ZoomIn, ZoomOut } from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';

import { t } from '../../i18n';
import { edgePath, graphBounds, graphEdges, inPort, NODE_WIDTH, nodeAt, nodeHeight, outPort, positionOf } from './graphOps';
import type { MapStatus } from './storyEngine';
import type { Point, Selection, StoryGraph, StoryIssue, StorySegment } from './storyTypes';

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2;
const ZOOM_STEP = 1.25;
const CLICK_SLOP = 4;

interface View { x: number; y: number; zoom: number }

type Drag =
  | { kind: 'pan'; pointerId: number; startX: number; startY: number; viewX: number; viewY: number; moved: boolean }
  | { kind: 'node'; pointerId: number; id: string; edge: string | null; offset: Point; startX: number; startY: number; moved: boolean }
  | { kind: 'connect'; pointerId: number; from: string; edge: string | null; startX: number; startY: number; moved: boolean };

const clampZoom = (value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));

export interface StoryGraphCanvasProps {
  graph: StoryGraph;
  selection?: Selection;
  issues?: readonly StoryIssue[];
  /** Read-only story map: no editing, and each node shows how far the viewer has got. */
  status?: (id: string) => MapStatus;
  /** Change it to refit the view, after a new layout say. */
  fitKey?: unknown;
  onSelect?: (selection: Selection) => void;
  onMoveNode?: (id: string, position: Point) => void;
  /** ``edge`` null means a new choice is being dragged out of the segment. */
  onConnect?: (segment: string, edge: string | null, target: string) => void;
  onAddChoice?: (segment: string) => void;
  onAddAt?: (position: Point) => void;
  onDeleteSelection?: () => void;
}

/** Segments as DOM nodes, edges as SVG, both inside one transformed layer: drag a node, drag empty space to pan, wheel to zoom. */
export function StoryGraphCanvas({
  graph, selection = null, issues, status, fitKey, onSelect, onMoveNode, onConnect, onAddChoice, onAddAt, onDeleteSelection,
}: StoryGraphCanvasProps) {
  const readOnly = Boolean(status);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<Drag | null>(null);
  const [view, setView] = useState<View>({ x: 40, y: 40, zoom: 1 });
  const [moved, setMoved] = useState<{ id: string; position: Point } | null>(null);
  const [rubber, setRubber] = useState<{ from: Point; to: Point; hover: string | null } | null>(null);
  const [panning, setPanning] = useState(false);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');

  // Read through a ref: refitting on every edit would throw away the view the author has set up.
  const latestGraph = useRef(graph);
  useEffect(() => { latestGraph.current = graph; }, [graph]);

  const fit = useCallback(() => {
    const rect = rootRef.current?.getBoundingClientRect();
    const width = rect?.width || 900;
    const height = rect?.height || 600;
    const bounds = graphBounds(latestGraph.current);
    const zoom = clampZoom(Math.min(1, (width - 80) / Math.max(1, bounds.right - bounds.left), (height - 80) / Math.max(1, bounds.bottom - bounds.top)));
    setView({ zoom, x: (width - (bounds.right - bounds.left) * zoom) / 2 - bounds.left * zoom, y: (height - (bounds.bottom - bounds.top) * zoom) / 2 - bounds.top * zoom });
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(fit, 0);
    return () => window.clearTimeout(handle);
  }, [fit, fitKey]);

  // A native listener: React's wheel handler is passive, and the page behind must not scroll.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const onWheel = (event: WheelEvent) => {
      if (!event.deltaY) return;
      event.preventDefault();
      const rect = root.getBoundingClientRect();
      const factor = Math.min(1.25, Math.max(0.8, Math.exp(-event.deltaY * (event.ctrlKey ? 0.006 : 0.001))));
      const cx = event.clientX - rect.left;
      const cy = event.clientY - rect.top;
      setView(current => {
        const zoom = clampZoom(current.zoom * factor);
        const ratio = zoom / current.zoom;
        return { zoom, x: cx - (cx - current.x) * ratio, y: cy - (cy - current.y) * ratio };
      });
    };
    root.addEventListener('wheel', onWheel, { passive: false });
    return () => root.removeEventListener('wheel', onWheel);
  }, []);

  const zoomBy = useCallback((factor: number) => {
    const rect = rootRef.current?.getBoundingClientRect();
    const cx = (rect?.width || 0) / 2;
    const cy = (rect?.height || 0) / 2;
    setView(current => {
      const zoom = clampZoom(current.zoom * factor);
      const ratio = zoom / current.zoom;
      return { zoom, x: cx - (cx - current.x) * ratio, y: cy - (cy - current.y) * ratio };
    });
  }, []);

  const toWorld = useCallback((clientX: number, clientY: number, current: View): Point => {
    const rect = rootRef.current?.getBoundingClientRect();
    return { x: (clientX - (rect?.left || 0) - current.x) / current.zoom, y: (clientY - (rect?.top || 0) - current.y) / current.zoom };
  }, []);

  const placed = useMemo(() => new Map(graph.segments.map(segment => [segment.id, positionOf(segment)])), [graph.segments]);
  const positionFor = (id: string): Point => (moved?.id === id ? moved.position : placed.get(id) ?? { x: 0, y: 0 });
  const byId = useMemo(() => new Map(graph.segments.map(segment => [segment.id, segment])), [graph.segments]);
  const edges = useMemo(() => graphEdges(graph), [graph]);
  const problems = useMemo(() => {
    const counts = new Map<string, { errors: number; warnings: number }>();
    for (const issue of issues ?? []) {
      for (const id of issue.segment_ids ?? (issue.segment_id ? [issue.segment_id] : [])) {
        const row = counts.get(id) ?? { errors: 0, warnings: 0 };
        if (issue.severity === 'error') row.errors += 1;
        else row.warnings += 1;
        counts.set(id, row);
      }
    }
    return counts;
  }, [issues]);

  const capture = (event: ReactPointerEvent) => rootRef.current?.setPointerCapture?.(event.pointerId);

  const startPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    drag.current = { kind: 'pan', pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, viewX: view.x, viewY: view.y, moved: false };
    capture(event);
    setPanning(true);
  };

  const startNode = (event: ReactPointerEvent, id: string, edge: string | null) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const at = toWorld(event.clientX, event.clientY, view);
    const position = positionFor(id);
    drag.current = { kind: 'node', pointerId: event.pointerId, id, edge, offset: { x: at.x - position.x, y: at.y - position.y }, startX: event.clientX, startY: event.clientY, moved: false };
    capture(event);
  };

  const startConnect = (event: ReactPointerEvent, from: string, edge: string | null, row: number) => {
    if (event.button !== 0 || readOnly) return;
    event.stopPropagation();
    drag.current = { kind: 'connect', pointerId: event.pointerId, from, edge, startX: event.clientX, startY: event.clientY, moved: false };
    capture(event);
    const origin = outPort(positionFor(from), row);
    setRubber({ from: origin, to: origin, hover: null });
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - current.startX, event.clientY - current.startY) >= CLICK_SLOP) current.moved = true;
    if (current.kind === 'pan') {
      setView(state => ({ ...state, x: current.viewX + event.clientX - current.startX, y: current.viewY + event.clientY - current.startY }));
    } else if (current.kind === 'node') {
      if (current.moved && !readOnly) {
        const at = toWorld(event.clientX, event.clientY, view);
        setMoved({ id: current.id, position: { x: Math.round(at.x - current.offset.x), y: Math.round(at.y - current.offset.y) } });
      }
    } else {
      const at = toWorld(event.clientX, event.clientY, view);
      const hover = nodeAt(graph, at);
      setRubber(state => (state ? { ...state, to: at, hover: hover === current.from ? null : hover } : state));
    }
  };

  const finish = (event: ReactPointerEvent<HTMLDivElement>, cancelled = false) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    rootRef.current?.releasePointerCapture?.(event.pointerId);
    drag.current = null;
    setPanning(false);
    if (current.kind === 'pan') {
      if (!current.moved && !cancelled) onSelect?.(null);
    } else if (current.kind === 'node') {
      if (current.moved && moved && !cancelled) onMoveNode?.(current.id, moved.position);
      else if (!current.moved && !cancelled) {
        onSelect?.(current.edge ? { kind: 'edge', segment: current.id, edge: current.edge } : { kind: 'segment', id: current.id });
      }
      setMoved(null);
    } else {
      const target = cancelled ? null : nodeAt(graph, toWorld(event.clientX, event.clientY, view));
      setRubber(null);
      if (cancelled) return;
      if (!current.moved) {
        if (current.edge === null) onAddChoice?.(current.from);
        else onSelect?.({ kind: 'edge', segment: current.from, edge: current.edge });
      } else if (target) {
        onConnect?.(current.from, current.edge, target);
      }
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (readOnly || !selection) return;
    if ((event.key === 'Delete' || event.key === 'Backspace') && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      onDeleteSelection?.();
    }
  };

  const renderRow = (segment: StorySegment, row: number, edge: { id: string; label: string; target: string | null; gated: boolean; kind: 'choice' | 'route'; isDefault: boolean }) => {
    const selected = selection?.kind === 'edge' && selection.edge === edge.id;
    const connected = Boolean(edge.target && byId.has(edge.target));
    return (
      <div
        key={edge.id}
        className={`istory-node__row ${selected ? 'is-selected' : ''} ${connected ? '' : 'is-open'}`}
        onPointerDown={event => startNode(event, segment.id, edge.id)}
        title={edge.label}
      >
        {edge.kind === 'route' ? <CornerDownRight aria-hidden="true" /> : edge.gated ? <Lock aria-hidden="true" /> : null}
        {edge.kind === 'route' && edge.gated && <Lock aria-hidden="true" />}
        {edge.isDefault && <Timer aria-hidden="true" />}
        <span>{edge.label || (edge.kind === 'route' ? t('自动路由') : t('（未命名选项）'))}</span>
        {!readOnly && (
          <span
            className="istory-node__port"
            role="button"
            aria-label={t('拖到另一个片段以连接')}
            data-port={edge.id}
            onPointerDown={event => startConnect(event, segment.id, edge.id, row)}
          />
        )}
      </div>
    );
  };

  return (
    <div
      ref={rootRef}
      className={`istory-canvas ${panning ? 'is-panning' : ''}`}
      data-testid="story-canvas"
      tabIndex={0}
      role="application"
      aria-label={t('{0} 个片段、{1} 条连线的分支图', [graph.segments.length, edges.length])}
      data-zoom={view.zoom.toFixed(3)}
      onPointerDown={startPan}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={event => finish(event, true)}
      onKeyDown={onKeyDown}
      onDoubleClick={event => {
        if (readOnly) return;
        const at = toWorld(event.clientX, event.clientY, view);
        if (!nodeAt(graph, at)) onAddAt?.(at);
      }}
    >
      <div className="istory-canvas__world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}>
        <svg className="istory-canvas__edges" width="1" height="1" aria-hidden="true">
          <defs>
            <marker id={`${uid}-arrow`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L8 4L0 8Z" />
            </marker>
          </defs>
          {edges.map(edge => {
            const from = outPort(positionFor(edge.from), edge.row);
            const to = inPort(positionFor(edge.to));
            const d = edgePath(from, to);
            const selected = selection?.kind === 'edge' && selection.edge === edge.id;
            return (
              <g key={edge.id} className={`istory-edge is-${edge.kind} ${edge.gated ? 'is-gated' : ''} ${selected ? 'is-selected' : ''}`} data-edge={edge.id}>
                <path className="istory-edge__line" d={d} markerEnd={`url(#${uid}-arrow)`} />
                {!readOnly && (
                  <path
                    className="istory-edge__hit"
                    d={d}
                    onPointerDown={event => {
                      event.stopPropagation();
                      onSelect?.({ kind: 'edge', segment: edge.from, edge: edge.id });
                    }}
                  />
                )}
              </g>
            );
          })}
          {rubber && <path className="istory-edge__rubber" d={edgePath(rubber.from, rubber.to)} />}
        </svg>
        {graph.segments.map(segment => {
          const position = positionFor(segment.id);
          const selected = selection?.kind === 'segment' && selection.id === segment.id;
          const counts = problems.get(segment.id);
          const state = status?.(segment.id);
          const snippet = segment.narration || segment.dialogue[0]?.text || '';
          return (
            <div
              key={segment.id}
              className={[
                'istory-node', segment.kind === 'ending' ? 'is-ending' : '', selected ? 'is-selected' : '',
                graph.start === segment.id ? 'is-start' : '', counts?.errors ? 'has-error' : '',
                state ? `is-${state}` : '', rubber?.hover === segment.id ? 'is-drop' : '',
              ].filter(Boolean).join(' ')}
              style={{ left: position.x, top: position.y, width: NODE_WIDTH, minHeight: nodeHeight(segment) }}
              data-segment={segment.id}
              data-status={state}
              role="button"
              tabIndex={0}
              aria-label={segment.title || segment.id}
              aria-pressed={selected}
              onPointerDown={event => startNode(event, segment.id, null)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect?.({ kind: 'segment', id: segment.id });
                }
              }}
            >
              <div className="istory-node__head">
                {segment.kind === 'ending' && <Flag aria-hidden="true" />}
                {segment.media?.kind === 'video' && <Video aria-hidden="true" />}
                {segment.media?.kind === 'image' && <ImageIcon aria-hidden="true" />}
                <strong>{segment.title || segment.id}</strong>
                {segment.timer && segment.kind !== 'ending' && <em className="istory-node__tag"><Timer aria-hidden="true" />{segment.timer.seconds}s</em>}
                {counts && <em className={`istory-node__tag ${counts.errors ? 'is-error' : 'is-warning'}`}><TriangleAlert aria-hidden="true" />{counts.errors + counts.warnings}</em>}
              </div>
              <p className="istory-node__snippet">{snippet || (segment.kind === 'ending' ? segment.ending_label || t('结局') : t('（还没有内容）'))}</p>
              {segment.choices.map((choice, row) => renderRow(segment, row, {
                id: choice.id, label: choice.text, target: choice.target, gated: Boolean(choice.condition), kind: 'choice', isDefault: segment.timer?.default_choice === choice.id,
              }))}
              {segment.routes.map((route, index) => renderRow(segment, segment.choices.length + index, {
                id: route.id, label: '', target: route.target, gated: Boolean(route.condition), kind: 'route', isDefault: false,
              }))}
              {segment.kind !== 'ending' && !readOnly && (
                <div
                  className="istory-node__add"
                  role="button"
                  data-add-choice={segment.id}
                  aria-label={t('添加选项；拖到另一个片段可直接连上')}
                  onPointerDown={event => startConnect(event, segment.id, null, segment.choices.length + segment.routes.length)}
                >
                  <Plus aria-hidden="true" /> {t('选项')}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="istory-canvas__zoom" role="group" aria-label={t('画布缩放')} onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
        <button type="button" aria-label={t('放大')} disabled={view.zoom >= MAX_ZOOM} onClick={() => zoomBy(ZOOM_STEP)}><ZoomIn aria-hidden="true" /></button>
        <button type="button" aria-label={t('缩小')} disabled={view.zoom <= MIN_ZOOM} onClick={() => zoomBy(1 / ZOOM_STEP)}><ZoomOut aria-hidden="true" /></button>
        <button type="button" aria-label={t('适应画布')} onClick={fit}><Focus aria-hidden="true" /></button>
      </div>
    </div>
  );
}
