import { memo, useEffect, useRef, type RefObject } from 'react';

import { t } from '../../i18n';
import { boundsOf, centerOn, inflate, minimapToWorld, visibleRect } from './canvasGeometry';
import type { CanvasNode, Rect } from './canvasTypes';
import type { SurfaceHandle } from './CanvasSurface';

const MiniNodes = memo(function MiniNodes({ nodes }: { nodes: readonly CanvasNode[] }) {
  return (
    <>
      {nodes.map(node => (
        <rect key={node.id} x={node.x} y={node.y} width={node.width} height={node.height} className={`cn-mini cn-kind--${node.kind}`} />
      ))}
    </>
  );
});

/** The whole canvas at a glance. Its viewport rectangle follows the view directly, without rendering the nodes again. */
export function CanvasMinimap({ nodes, surface }: { nodes: readonly CanvasNode[]; surface: RefObject<SurfaceHandle | null> }) {
  const svg = useRef<SVGSVGElement>(null);
  const windowRect = useRef<SVGRectElement>(null);
  const viewBox = useRef<Rect>({ x: 0, y: 0, width: 100, height: 100 });
  const nodesRef = useRef(nodes);
  const dragging = useRef(false);

  useEffect(() => {
    nodesRef.current = nodes;
    const handle = surface.current;
    if (!handle) return undefined;
    return handle.subscribe((view, size) => {
      const visible = visibleRect(view, size.width, size.height);
      const box = boundsOf([...nodesRef.current, visible]) ?? visible;
      const framed = inflate(box, 0.05);
      viewBox.current = framed;
      svg.current?.setAttribute('viewBox', `${framed.x} ${framed.y} ${framed.width} ${framed.height}`);
      const rect = windowRect.current;
      if (rect) {
        rect.setAttribute('x', String(visible.x));
        rect.setAttribute('y', String(visible.y));
        rect.setAttribute('width', String(visible.width));
        rect.setAttribute('height', String(visible.height));
      }
    });
  }, [nodes, surface]);

  const jump = (event: React.PointerEvent<SVGSVGElement>) => {
    const handle = surface.current;
    const element = svg.current;
    if (!handle || !element) return;
    const box = element.getBoundingClientRect();
    const point = minimapToWorld(box, viewBox.current, event.clientX - box.left, event.clientY - box.top);
    const { width, height } = handle.size();
    handle.setView(centerOn({ x: point.x, y: point.y, width: 0, height: 0 }, handle.getView(), width, height));
  };

  return (
    <svg
      ref={svg}
      className="cn-minimap"
      role="img"
      aria-label={t('画布缩略图')}
      preserveAspectRatio="xMidYMid meet"
      onPointerDown={event => {
        dragging.current = true;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        jump(event);
      }}
      onPointerMove={event => { if (dragging.current) jump(event); }}
      onPointerUp={() => { dragging.current = false; }}
      onPointerCancel={() => { dragging.current = false; }}
    >
      <MiniNodes nodes={nodes} />
      <rect ref={windowRect} className="cn-mini-window" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
