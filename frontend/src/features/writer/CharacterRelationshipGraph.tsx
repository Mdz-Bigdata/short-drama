import { Focus, Minimize2, Network, ZoomIn, ZoomOut } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { createPortal } from 'react-dom';

import { graphCast, isBidirectional, namedRelationships } from './relationshipCast';
import type { WriterRelationship, WriterRole } from './types';
import { t } from '../../i18n';

interface Position { x: number; y: number }
const MAX_GRAPH_EDGES = 80;
const VIEW_WIDTH = 680;
const VIEW_HEIGHT = 400;
const CENTER: Position = { x: VIEW_WIDTH / 2, y: VIEW_HEIGHT / 2 - 10 };
const LEAD_RADIUS = 30;
const NODE_RADIUS = 24;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 1.25;

function edgeGeometry(
  edge: WriterRelationship, sameDirectionIndex: number, sameDirectionCount: number, reverseExists: boolean,
  positions: Record<string, Position>, lead: string,
) {
  const start = edge.from ? positions[edge.from] : undefined;
  const end = edge.to ? positions[edge.to] : undefined;
  if (!start || !end || !edge.from || !edge.to) return null;
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance;
  const uy = dy / distance;
  const startRadius = (edge.from === lead ? LEAD_RADIUS : NODE_RADIUS) + 3;
  const endRadius = (edge.to === lead ? LEAD_RADIUS : NODE_RADIUS) + 3;
  const sx = start.x + ux * startRadius;
  const sy = start.y + uy * startRadius;
  const ex = end.x - ux * endRadius;
  const ey = end.y - uy * endRadius;
  const laneOffset = (sameDirectionIndex - (sameDirectionCount - 1) / 2) * 22;
  const curve = reverseExists ? 22 + laneOffset : sameDirectionCount > 1 ? laneOffset : 0;
  const cx = (sx + ex) / 2 - uy * curve;
  const cy = (sy + ey) / 2 + ux * curve;
  return {
    path: `M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`,
    point: (at: number): Position => ({
      x: (1 - at) * (1 - at) * sx + 2 * (1 - at) * at * cx + at * at * ex,
      y: (1 - at) * (1 - at) * sy + 2 * (1 - at) * at * cy + at * at * ey,
    }),
  };
}

interface Box { left: number; right: number; top: number; bottom: number }

/** The space a node takes: its circle and the name / role chip under it. */
function nodeBox(position: Position, radius: number, chipWidth: number): Box {
  const half = Math.max(radius + 3, chipWidth / 2);
  return { left: position.x - half, right: position.x + half, top: position.y - radius - 3, bottom: position.y + radius + 40 };
}

/** Where a relation's name sits: the point of its curve nearest the middle that clears every node and chip. */
function labelPoint(point: (at: number) => Position, width: number, boxes: Box[]): Position {
  const clear = (at: Position) => boxes.every(box => (
    at.x + width / 2 < box.left || at.x - width / 2 > box.right || at.y + 8 < box.top || at.y - 8 > box.bottom
  ));
  for (const offset of [0, 0.05, -0.05, 0.1, -0.1, 0.15, -0.15, 0.2, -0.2, 0.25, -0.25, 0.3, -0.3]) {
    const at = point(0.5 + offset);
    if (clear(at)) return at;
  }
  return point(0.5);
}

function relationText(edge: WriterRelationship) {
  const text = String(edge.relation || '').trim();
  return text.length > 6 ? `${text.slice(0, 6)}…` : text;
}

const clampZoom = (value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));

type Drag =
  | { kind: 'node'; name: string; pointerId: number; dx: number; dy: number }
  | { kind: 'pan'; pointerId: number; startX: number; startY: number; panX: number; panY: number };

/**
 * The 关系星域: the cast as portrait nodes around the lead; every line carries the name of the relation
 * (君臣、父子、宿敌 …). Nodes can be dragged, the empty field pans, the wheel or a pinch zooms; 适应画布 resets.
 * Pairings counted from shared scenes are not relations and are not drawn.
 */
export function CharacterRelationshipGraph({
  roles,
  relationships,
  avatars = {},
  expanded = false,
}: {
  roles: WriterRole[];
  relationships: WriterRelationship[];
  /** name → portrait url; a node without one shows the first character of its name. */
  avatars?: Record<string, string>;
  /** A taller field, for the 放大 toggle. */
  expanded?: boolean;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Position>({ x: 0, y: 0 });
  const [moved, setMoved] = useState<Record<string, Position>>({});
  const [dragging, setDragging] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const drag = useRef<Drag | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const named = namedRelationships(relationships);
  const { allNames, lead, names, hidden, valid } = graphCast(roles, named);

  const viewWidth = VIEW_WIDTH / zoom;
  const viewHeight = VIEW_HEIGHT / zoom;
  const originX = (VIEW_WIDTH - viewWidth) / 2 + pan.x;
  const originY = (VIEW_HEIGHT - viewHeight) / 2 + pan.y;

  // The wheel zooms the field (a trackpad pinch arrives as a ctrl+wheel); a native listener so the page does not scroll too.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (event: WheelEvent) => {
      if (!event.deltaY) return;
      event.preventDefault();
      // About 10% per wheel notch, a little more per pinch step; never more than 25% at once.
      const raw = Math.exp(-event.deltaY * (event.ctrlKey ? 0.006 : 0.001));
      const factor = Math.min(1.25, Math.max(0.8, raw));
      setZoom(current => clampZoom(current * factor));
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [lead, fullscreen]);

  // Leaving the browser's full screen (Esc, its own exit) leaves ours too.
  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement) setFullscreen(false);
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);
  // Without the Fullscreen API the field fills the window instead; Esc leaves that too.
  useEffect(() => {
    if (!fullscreen) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.fullscreenElement) setFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  // Full screen renders the field straight under <body> (no ancestor can clip it or pin it in place),
  // filling the window at once; where the browser allows it, that element also goes truly full screen.
  // Embedded browsers may ignore the request without a word, so the window-filling state never waits on it.
  const toggleFullscreen = useCallback(() => {
    if (fullscreen || document.fullscreenElement) {
      setFullscreen(false);
      if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => undefined);
      return;
    }
    setFullscreen(true);
  }, [fullscreen]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!fullscreen || !canvas || document.fullscreenElement) return;
    if (typeof canvas.requestFullscreen === 'function') void canvas.requestFullscreen().catch(() => undefined);
  }, [fullscreen]);

  /** A pointer position in the field's own coordinates. */
  const toField = useCallback((clientX: number, clientY: number): Position | null => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM?.();
    if (!svg || !matrix || typeof DOMPoint === 'undefined') return null;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return { x: point.x, y: point.y };
  }, []);

  if (allNames.length === 0 || !lead) {
    return (
      <div className="writer-relationship-empty">
        <Network aria-hidden="true" />
        <p>{t('识别角色后，这里会生成以主角为中心的人物关系图谱。')}</p>
      </div>
    );
  }

  const shown = new Set(names);
  const eligible = valid.filter(edge => shown.has(String(edge.from)) && shown.has(String(edge.to)));
  const graphRelationships = [
    ...eligible.filter(edge => edge.from === lead || edge.to === lead),
    ...eligible.filter(edge => edge.from !== lead && edge.to !== lead),
  ].slice(0, MAX_GRAPH_EDGES);
  const key = (from?: string, to?: string) => JSON.stringify([from, to]);
  const counts = new Map<string, number>();
  graphRelationships.forEach(edge => counts.set(key(edge.from, edge.to), (counts.get(key(edge.from, edge.to)) || 0) + 1));
  const indexes = new Map<string, number>();
  const edges = graphRelationships.map(edge => {
    const direction = key(edge.from, edge.to);
    const sameDirectionIndex = indexes.get(direction) || 0;
    indexes.set(direction, sameDirectionIndex + 1);
    return { edge, sameDirectionIndex, sameDirectionCount: counts.get(direction) || 1, reverseExists: counts.has(key(edge.to, edge.from)) };
  });

  const others = names.filter(name => name !== lead);
  const layout: Record<string, Position> = { [lead]: CENTER };
  // A tight ring around the lead, slightly wider than tall so chips do not collide; more people, a wider ring.
  const ringX = Math.min(230, 120 + others.length * 18);
  const ringY = Math.min(125, 70 + others.length * 9);
  others.forEach((name, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(others.length, 1) - Math.PI / 2;
    layout[name] = { x: CENTER.x + ringX * Math.cos(angle), y: CENTER.y + ringY * Math.sin(angle) };
  });
  const positions: Record<string, Position> = { ...layout };
  for (const name of names) if (moved[name]) positions[name] = moved[name];
  const roleLabel = (name: string) => roles.find(role => role.name === name)?.position || '剧情角色';
  const boxes = names.map(name => nodeBox(positions[name], name === lead ? LEAD_RADIUS : NODE_RADIUS, Math.max(40, name.slice(0, 5).length * 12 + 14)));

  const startNodeDrag = (event: ReactPointerEvent<SVGGElement>, name: string) => {
    event.stopPropagation();
    const at = toField(event.clientX, event.clientY);
    if (!at) return;
    const current = positions[name];
    drag.current = { kind: 'node', name, pointerId: event.pointerId, dx: at.x - current.x, dy: at.y - current.y };
    svgRef.current?.setPointerCapture?.(event.pointerId);
    setDragging(name);
  };

  const startPan = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    drag.current = { kind: 'pan', pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, panX: pan.x, panY: pan.y };
    svgRef.current?.setPointerCapture?.(event.pointerId);
    setDragging('__pan__');
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    if (current.kind === 'node') {
      const at = toField(event.clientX, event.clientY);
      if (at) setMoved(previous => ({ ...previous, [current.name]: { x: at.x - current.dx, y: at.y - current.dy } }));
      return;
    }
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || !rect.width) return;
    // Screen pixels to field units: the field is viewWidth wide across rect.width pixels.
    const scale = viewWidth / rect.width;
    setPan({ x: current.panX - (event.clientX - current.startX) * scale, y: current.panY - (event.clientY - current.startY) * scale });
  };

  const endDrag = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (drag.current && drag.current.pointerId === event.pointerId) {
      svgRef.current?.releasePointerCapture?.(event.pointerId);
      drag.current = null;
      setDragging(null);
    }
  };

  const fit = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setMoved({});
  };

  const field = (
    <div
      ref={canvasRef}
      className={`writer-relationship-canvas ${expanded ? 'is-expanded' : ''} ${dragging ? 'is-dragging' : ''} ${fullscreen ? 'is-fullscreen' : ''}`}
      onDoubleClick={toggleFullscreen}
    >
      <svg
        ref={svgRef}
        className="writer-relationship-graph"
        viewBox={`${originX} ${originY} ${viewWidth} ${viewHeight}`}
        role="img"
        aria-label={allNames.length === names.length
          ? `${names.length}名角色、${graphRelationships.length}条人物关系组成的关系图谱`
          : `图中展示${names.length}/${allNames.length}名角色、${graphRelationships.length}/${valid.length}条人物关系`}
        onPointerDown={startPan}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <defs>
          <marker id={`${uid}-arrow`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0L8 4L0 8Z" />
          </marker>
          <linearGradient id={`${uid}-ring`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f28b9c" />
            <stop offset="100%" stopColor="#f5b3a3" />
          </linearGradient>
          <linearGradient id={`${uid}-lead-ring`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#e3546c" />
            <stop offset="100%" stopColor="#f28b6c" />
          </linearGradient>
          <filter id={`${uid}-glow`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {edges.map(({ edge, sameDirectionIndex, sameDirectionCount, reverseExists }, index) => {
          const geometry = edgeGeometry(edge, sameDirectionIndex, sameDirectionCount, reverseExists, positions, lead);
          if (!geometry) return null;
          const bidirectional = isBidirectional(edge);
          const text = relationText(edge);
          const labelWidth = Math.max(30, text.length * 10 + 12);
          const at = labelPoint(geometry.point, labelWidth, boxes);
          return (
            <g className={`writer-relationship-graph__edge ${edge.from === lead || edge.to === lead ? 'is-lead-edge' : ''}`} key={`${edge.from}-${edge.to}-${index}`}>
              <title>{`${edge.from} ${bidirectional ? '双向' : '指向'} ${edge.to}：${edge.relation}`}</title>
              <path d={geometry.path} data-relation-edge="true" markerStart={bidirectional ? `url(#${uid}-arrow)` : undefined} markerEnd={`url(#${uid}-arrow)`} />
              <g className="writer-relationship-graph__relation" data-relation-label="true">
                <rect x={at.x - labelWidth / 2} y={at.y - 8} width={labelWidth} height={16} rx={8} />
                <text x={at.x} y={at.y + 3.5}>{text}</text>
              </g>
            </g>
          );
        })}
        {names.map((name, index) => {
          const position = positions[name];
          const isLead = name === lead;
          const radius = isLead ? LEAD_RADIUS : NODE_RADIUS;
          const portrait = avatars[name];
          const label = name.slice(0, 5);
          const chipWidth = Math.max(40, label.length * 12 + 14);
          return (
            <g
              className={`writer-relationship-graph__node ${isLead ? 'is-lead' : ''} ${dragging === name ? 'is-dragging' : ''}`}
              key={name}
              data-node-name={name}
              transform={`translate(${Math.round(position.x * 10) / 10} ${Math.round(position.y * 10) / 10})`}
              onPointerDown={event => startNodeDrag(event, name)}
            >
              {isLead && <circle className="writer-relationship-graph__halo" r={radius + 14} filter={`url(#${uid}-glow)`} />}
              <circle className="writer-relationship-graph__ring" r={radius + 3} stroke={`url(#${isLead ? `${uid}-lead-ring` : `${uid}-ring`})`} />
              <circle className="writer-relationship-graph__face" r={radius} />
              {portrait ? (
                <>
                  <clipPath id={`${uid}-clip-${index}`}><circle r={radius - 1} /></clipPath>
                  <image href={portrait} x={-(radius - 1)} y={-(radius - 1)} width={(radius - 1) * 2} height={(radius - 1) * 2} clipPath={`url(#${uid}-clip-${index})`} preserveAspectRatio="xMidYMid slice" />
                </>
              ) : (
                <text className="writer-relationship-graph__initial" y="6">{name.slice(0, 1)}</text>
              )}
              <rect className="writer-relationship-graph__tag" x={-chipWidth / 2} y={radius + 7} width={chipWidth} height={18} rx={5} />
              <text className="writer-relationship-graph__name" y={radius + 20}>{label}</text>
              <text className="writer-relationship-graph__role" y={radius + 35}>{roleLabel(name).slice(0, 8)}</text>
            </g>
          );
        })}
      </svg>
      {hidden.length > 0 && (
        <p className="writer-relationship-canvas__overflow" aria-label={`图外角色 ${hidden.length} 名`}>
          {t('图外角色')}：{hidden.map(name => `${name}（${roleLabel(name)}）`).join('、')}
        </p>
      )}
      <div className="writer-relationship-zoom" role="group" aria-label={t('星图缩放')} onDoubleClick={event => event.stopPropagation()}>
        <button type="button" aria-label={t('放大')} disabled={zoom >= MAX_ZOOM} onClick={() => setZoom(current => clampZoom(current * ZOOM_STEP))}><ZoomIn aria-hidden="true" /></button>
        <button type="button" aria-label={t('缩小')} disabled={zoom <= MIN_ZOOM} onClick={() => setZoom(current => clampZoom(current / ZOOM_STEP))}><ZoomOut aria-hidden="true" /></button>
        <button type="button" aria-label={t('适应画布')} onClick={fit}><Focus aria-hidden="true" /></button>
      </div>
      {fullscreen && (
        <button type="button" className="writer-relationship-canvas__exit" onClick={toggleFullscreen} onDoubleClick={event => event.stopPropagation()}>
          <Minimize2 aria-hidden="true" /> {t('退出全屏')}
        </button>
      )}
      <p className="writer-relationship-canvas__hint">{t('拖动人物调整位置，拖动空白处平移，滚轮缩放，双击全屏')}</p>
    </div>
  );
  return fullscreen && typeof document !== 'undefined' ? createPortal(field, document.body) : field;
}
