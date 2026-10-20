import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { cameraCone, floorBounds, floorTransform, forwardOf, isOverhead } from './floorPlanGeometry';
import { actorsInShot, type GroundPoint, type StagePlan, type StageShot } from './spatialTypes';
import { t } from '../../i18n';

const WIDTH = 720;
const HEIGHT = 540;
const ACTOR_RADIUS_M = 0.28;

export type FloorMove =
  | { kind: 'actor'; name: string; position: GroundPoint }
  | { kind: 'landmark'; name: string; position: GroundPoint }
  | { kind: 'camera'; cameraId: string; position: GroundPoint };

interface DragState {
  kind: FloorMove['kind'];
  key: string;
  point: GroundPoint;
}

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  locked?: boolean;
  onSelectShot: (shotId: number) => void;
  onMove: (move: FloorMove) => void;
}

/**
 * The stage seen from above, drawn the way the master camera looks at it: the camera side is at
 * the bottom, so the left of the drawing is screen left. Marks, set pieces and cameras can be
 * dragged; a drag is reported once, when it ends.
 */
export function FloorPlan({ plan, shot, locked = false, onSelectShot, onMove }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const actors = useMemo(() => actorsInShot(plan, shot), [plan, shot]);
  const bounds = useMemo(() => floorBounds(plan, actors), [plan, actors]);
  const transform = useMemo(() => floorTransform(bounds, WIDTH, HEIGHT), [bounds]);
  const selectedCamera = plan.cameras.find(camera => camera.id === shot?.camera_id);
  const shotByCamera = useMemo(() => new Map(plan.shots.map(item => [item.camera_id, item])), [plan.shots]);
  // A mark a shot overrides is that shot's business; dragging edits the scene's base blocking.
  const overridden = new Set((shot?.overrides || []).filter(item => item.position || item.offstage).map(item => item.name));

  const worldPoint = (event: ReactPointerEvent): GroundPoint | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    return transform.toWorld(
      ((event.clientX - rect.left) / rect.width) * WIDTH,
      ((event.clientY - rect.top) / rect.height) * HEIGHT,
    );
  };

  const begin = (kind: FloorMove['kind'], key: string, point: GroundPoint) => (event: ReactPointerEvent) => {
    if (locked) return;
    event.stopPropagation();
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    setDrag({ kind, key, point });
  };

  const move = (event: ReactPointerEvent) => {
    if (!drag) return;
    const point = worldPoint(event);
    if (point) setDrag({ ...drag, point });
  };

  const end = () => {
    if (!drag) return;
    const finished = drag;
    setDrag(null);
    if (finished.kind === 'camera') onMove({ kind: 'camera', cameraId: finished.key, position: finished.point });
    else onMove({ kind: finished.kind, name: finished.key, position: finished.point });
  };

  const placed = (kind: FloorMove['kind'], key: string, fallback: GroundPoint): GroundPoint =>
    drag && drag.kind === kind && drag.key === key ? drag.point : fallback;

  const gridLines: number[] = [];
  for (let value = Math.ceil(bounds.minX); value <= Math.floor(bounds.maxX); value += 1) gridLines.push(value);
  const gridRows: number[] = [];
  for (let value = Math.ceil(bounds.minZ); value <= Math.floor(bounds.maxZ); value += 1) gridRows.push(value);

  const [axisStart, axisEnd] = [transform.toView(plan.axis.start), transform.toView(plan.axis.end)];
  const axisDx = axisEnd[0] - axisStart[0];
  const axisDy = axisEnd[1] - axisStart[1];
  const axisLength = Math.hypot(axisDx, axisDy) || 1;
  const extend = 60;

  return (
    <svg
      ref={svgRef}
      className={`spatial-floor ${locked ? 'is-locked' : ''}`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`${plan.scene_id} 空间调度俯视图`}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={() => setDrag(null)}
    >
      <g className="spatial-floor__grid" aria-hidden="true">
        {gridLines.map(value => {
          const [x] = transform.toView([value, 0]);
          return <line key={`x${value}`} x1={x} y1={0} x2={x} y2={HEIGHT} className={value === 0 ? 'is-origin' : ''} />;
        })}
        {gridRows.map(value => {
          const [, y] = transform.toView([0, value]);
          return <line key={`z${value}`} x1={0} y1={y} x2={WIDTH} y2={y} className={value === 0 ? 'is-origin' : ''} />;
        })}
      </g>
      <text className="spatial-floor__hint" x={WIDTH / 2} y={HEIGHT - 10} textAnchor="middle">{t('主机位一侧（画面左 ← → 画面右）· 网格 1 米')}</text>

      {plan.axis.kind !== 'none' && (
        <line
          className="spatial-floor__axis"
          x1={axisStart[0] - (axisDx / axisLength) * extend}
          y1={axisStart[1] - (axisDy / axisLength) * extend}
          x2={axisEnd[0] + (axisDx / axisLength) * extend}
          y2={axisEnd[1] + (axisDy / axisLength) * extend}
        />
      )}

      {plan.landmarks.map(landmark => {
        const [x, y] = transform.toView(placed('landmark', landmark.name, landmark.position));
        const width = Math.max(10, landmark.size[0] * transform.scale);
        const depth = Math.max(10, landmark.size[1] * transform.scale);
        return (
          <g key={landmark.id} className={`spatial-floor__landmark is-${landmark.kind}`} onPointerDown={begin('landmark', landmark.name, landmark.position)}>
            <rect x={x - width / 2} y={y - depth / 2} width={width} height={depth} rx={3} />
            <text x={x} y={y + depth / 2 + 13} textAnchor="middle">{landmark.name}</text>
          </g>
        );
      })}

      {plan.cameras.map(camera => {
        const owner = shotByCamera.get(camera.id);
        const selected = camera.id === selectedCamera?.id;
        const ground = placed('camera', camera.id, [camera.position[0], camera.position[2]]);
        const shifted = { ...camera, position: [ground[0], camera.position[1], ground[1]] as [number, number, number] };
        const [x, y] = transform.toView(ground);
        const cone = selected ? cameraCone(shifted).map(point => transform.toView(point).join(',')).join(' ') : '';
        const endCone = selected && camera.move.kind !== 'static' ? cameraCone(camera, undefined, true).map(point => transform.toView(point).join(',')).join(' ') : '';
        const crossed = owner ? owner.axis_side !== 0 && plan.axis.camera_side !== 0 && owner.axis_side !== plan.axis.camera_side : false;
        return (
          <g
            key={camera.id}
            className={`spatial-floor__camera ${selected ? 'is-selected' : ''} ${crossed ? 'is-crossed' : ''}`}
            role="button"
            tabIndex={0}
            aria-label={`机位 ${camera.label}`}
            aria-pressed={selected}
            onClick={() => owner && onSelectShot(owner.shot_id)}
            onKeyDown={event => { if ((event.key === 'Enter' || event.key === ' ') && owner) { event.preventDefault(); onSelectShot(owner.shot_id); } }}
            onPointerDown={selected ? begin('camera', camera.id, [camera.position[0], camera.position[2]]) : undefined}
          >
            {cone && <polygon className="spatial-floor__cone" points={cone} />}
            {endCone && <polygon className="spatial-floor__cone is-end" points={endCone} />}
            {isOverhead(camera)
              ? <circle cx={x} cy={y} r={9} className="spatial-floor__camera-body is-overhead" />
              : <rect x={x - 7} y={y - 5} width={14} height={10} rx={2} className="spatial-floor__camera-body" />}
            <text x={x} y={y - 9} textAnchor="middle">{owner ? owner.shot_id : camera.id}</text>
          </g>
        );
      })}

      {actors.map(actor => {
        const [x, y] = transform.toView(placed('actor', actor.name, actor.position));
        const radius = Math.max(9, ACTOR_RADIUS_M * transform.scale);
        const [fx, fz] = forwardOf(actor.yaw_deg);
        const subject = shot?.subjects.includes(actor.name);
        const fixed = overridden.has(actor.name);
        return (
          <g
            key={actor.id}
            className={`spatial-floor__actor is-${actor.role} ${subject ? 'is-subject' : ''} ${fixed ? 'is-overridden' : ''}`}
            onPointerDown={fixed ? undefined : begin('actor', actor.name, actor.position)}
          >
            <circle cx={x} cy={y} r={radius} />
            <line x1={x} y1={y} x2={x + fx * radius * 1.9} y2={y + fz * radius * 1.9} />
            <text x={x} y={y - radius - 5} textAnchor="middle">{actor.name}</text>
          </g>
        );
      })}
    </svg>
  );
}
