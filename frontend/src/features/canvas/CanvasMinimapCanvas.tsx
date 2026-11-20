// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/components/canvas/canvas-mini-map.tsx.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { t } from '../../i18n';
import { visibleRect } from './canvasGeometry';
import type { CanvasNode, Rect, Viewport } from './canvasTypes';
import './CanvasMinimapCanvas.css';

export const MINIMAP_WIDTH = 240;
export const MINIMAP_HEIGHT = 160;
/** World units of margin around the nodes' bounding box. */
export const MINIMAP_MARGIN = 500;
const MAX_DPR = 2;

/** How the world maps onto the minimap: minimap = (world - bounds) * scale + offset. */
interface MinimapFrame {
  bounds: Rect;
  scale: number;
  offsetX: number;
  offsetY: number;
}

function minimapFrame(nodes: readonly CanvasNode[], mapWidth = MINIMAP_WIDTH, mapHeight = MINIMAP_HEIGHT): MinimapFrame {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const node of nodes) {
    left = Math.min(left, node.x);
    top = Math.min(top, node.y);
    right = Math.max(right, node.x + node.width);
    bottom = Math.max(bottom, node.y + node.height);
  }
  if (!Number.isFinite(left)) {
    left = 0;
    top = 0;
    right = 0;
    bottom = 0;
  }
  const bounds = {
    x: left - MINIMAP_MARGIN,
    y: top - MINIMAP_MARGIN,
    width: Math.max(right - left + MINIMAP_MARGIN * 2, 1),
    height: Math.max(bottom - top + MINIMAP_MARGIN * 2, 1),
  };
  const scale = Math.min(mapWidth / bounds.width, mapHeight / bounds.height);
  return { bounds, scale, offsetX: (mapWidth - bounds.width * scale) / 2, offsetY: (mapHeight - bounds.height * scale) / 2 };
}

function minimapToWorldPoint(frame: MinimapFrame, localX: number, localY: number) {
  return { x: (localX - frame.offsetX) / frame.scale + frame.bounds.x, y: (localY - frame.offsetY) / frame.scale + frame.bounds.y };
}

function worldToMinimapRect(frame: MinimapFrame, rect: Rect): Rect {
  return {
    x: (rect.x - frame.bounds.x) * frame.scale + frame.offsetX,
    y: (rect.y - frame.bounds.y) * frame.scale + frame.offsetY,
    width: rect.width * frame.scale,
    height: rect.height * frame.scale,
  };
}

/** The view, at the same zoom, that puts the world point under the minimap pointer at the surface centre. */
function minimapJump(frame: MinimapFrame, localX: number, localY: number, view: Viewport, surfaceWidth: number, surfaceHeight: number): Viewport {
  const world = minimapToWorldPoint(frame, localX, localY);
  return { zoom: view.zoom, x: surfaceWidth / 2 - world.x * view.zoom, y: surfaceHeight / 2 - world.y * view.zoom };
}

interface MinimapColors {
  node: string;
  group: string;
  selected: string;
  window: string;
}

const FALLBACK_COLORS: MinimapColors = { node: 'rgba(214, 90, 120, 0.34)', group: '#7d6670', selected: '#c8335a', window: '#c8335a' };

function readColors(element: Element | null): MinimapColors {
  if (!element || typeof getComputedStyle !== 'function') return FALLBACK_COLORS;
  const style = getComputedStyle(element);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    node: read('--cn-mm-node', FALLBACK_COLORS.node),
    group: read('--cn-mm-group', FALLBACK_COLORS.group),
    selected: read('--cn-mm-selected', FALLBACK_COLORS.selected),
    window: read('--cn-mm-window', FALLBACK_COLORS.window),
  };
}

/** Draw the nodes: groups as outlines underneath, the rest filled, selected ones in the accent colour. */
function drawMinimapNodes(
  context: CanvasRenderingContext2D,
  frame: MinimapFrame,
  nodes: readonly CanvasNode[],
  colors: MinimapColors,
  selected?: ReadonlySet<string>,
) {
  context.globalAlpha = 0.9;
  context.lineWidth = 1;
  for (const node of nodes) {
    if (node.kind !== 'group') continue;
    const box = worldToMinimapRect(frame, node);
    context.strokeStyle = selected?.has(node.id) ? colors.selected : colors.group;
    context.strokeRect(box.x + 0.5, box.y + 0.5, Math.max(box.width, 2), Math.max(box.height, 2));
  }
  context.globalAlpha = 0.85;
  context.fillStyle = colors.node;
  const chosen: CanvasNode[] = [];
  for (const node of nodes) {
    if (node.kind === 'group') continue;
    if (selected?.has(node.id)) {
      chosen.push(node);
      continue;
    }
    const box = worldToMinimapRect(frame, node);
    context.fillRect(box.x, box.y, Math.max(box.width, 1.5), Math.max(box.height, 1.5));
  }
  context.fillStyle = colors.selected;
  for (const node of chosen) {
    const box = worldToMinimapRect(frame, node);
    context.fillRect(box.x, box.y, Math.max(box.width, 2), Math.max(box.height, 2));
  }
  context.globalAlpha = 1;
}

function drawMinimapWindow(context: CanvasRenderingContext2D, frame: MinimapFrame, visible: Rect, colors: MinimapColors) {
  const box = worldToMinimapRect(frame, visible);
  context.globalAlpha = 1;
  context.lineWidth = 1.5;
  context.strokeStyle = colors.window;
  context.strokeRect(box.x, box.y, Math.max(box.width, 4), Math.max(box.height, 4));
}

export interface CanvasMinimapCanvasProps {
  nodes: readonly CanvasNode[];
  view: Viewport;
  /** Surface size in screen pixels. */
  width: number;
  height: number;
  selected?: ReadonlySet<string>;
  onJump: (view: Viewport) => void;
  /** Minimap size in CSS pixels. */
  mapWidth?: number;
  mapHeight?: number;
  className?: string;
}

function pixelRatio() {
  return Math.min(MAX_DPR, Math.max(1, typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1));
}

/**
 * The whole canvas at a glance, drawn on one 2D canvas so fifty thousand nodes cost one bitmap, not
 * fifty thousand elements. Nodes are drawn into a cached layer that a view change only stamps again.
 */
export function CanvasMinimapCanvas({
  nodes, view, width, height, selected, onJump, mapWidth = MINIMAP_WIDTH, mapHeight = MINIMAP_HEIGHT, className,
}: CanvasMinimapCanvasProps) {
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const layer = useRef<{ key: unknown[]; bitmap: HTMLCanvasElement } | null>(null);
  const latest = useRef({ view, width, height, onJump });
  const [dragging, setDragging] = useState(false);
  const frame = useMemo(() => minimapFrame(nodes, mapWidth, mapHeight), [nodes, mapWidth, mapHeight]);

  useEffect(() => {
    latest.current = { view, width, height, onJump };
  });

  useEffect(() => {
    const element = canvas.current;
    if (!element) return undefined;
    const draw = () => {
      const dpr = pixelRatio();
      const pixelWidth = Math.round(mapWidth * dpr);
      const pixelHeight = Math.round(mapHeight * dpr);
      if (element.width !== pixelWidth) element.width = pixelWidth;
      if (element.height !== pixelHeight) element.height = pixelHeight;
      const context = element.getContext('2d');
      if (!context) return;
      const colors = readColors(root.current);
      const key = [nodes, selected, frame, dpr, colors.node, colors.group, colors.selected];
      let cached = layer.current;
      if (!cached || cached.key.length !== key.length || cached.key.some((part, index) => part !== key[index])) {
        const bitmap = cached?.bitmap ?? document.createElement('canvas');
        bitmap.width = pixelWidth;
        bitmap.height = pixelHeight;
        const layerContext = bitmap.getContext('2d');
        if (layerContext) {
          layerContext.setTransform(dpr, 0, 0, dpr, 0, 0);
          layerContext.clearRect(0, 0, mapWidth, mapHeight);
          drawMinimapNodes(layerContext, frame, nodes, colors, selected);
        }
        cached = { key, bitmap };
        layer.current = cached;
      }
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, pixelWidth, pixelHeight);
      context.drawImage(cached.bitmap, 0, 0);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawMinimapWindow(context, frame, visibleRect(view, width, height), colors);
    };
    if (typeof requestAnimationFrame !== 'function') {
      draw();
      return undefined;
    }
    const handle = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(handle);
  }, [frame, height, mapHeight, mapWidth, nodes, selected, view, width]);

  const jump = (event: ReactPointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const localX = (event.clientX - box.left) * (box.width > 0 ? mapWidth / box.width : 1);
    const localY = (event.clientY - box.top) * (box.height > 0 ? mapHeight / box.height : 1);
    const current = latest.current;
    const next = minimapJump(frame, localX, localY, current.view, current.width, current.height);
    // The next pointermove may come before the parent hands the new view back.
    latest.current = { ...current, view: next };
    current.onJump(next);
  };

  return (
    <div
      ref={root}
      className={`cn-minimap-canvas${dragging ? ' is-dragging' : ''}${className ? ` ${className}` : ''}`}
      style={{ width: mapWidth, height: mapHeight }}
      onPointerDown={event => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        setDragging(true);
        jump(event);
      }}
      onPointerMove={event => { if (dragging) jump(event); }}
      onPointerUp={() => setDragging(false)}
      onPointerCancel={() => setDragging(false)}
    >
      <canvas ref={canvas} role="img" aria-label={t('小地图')} width={mapWidth} height={mapHeight} />
    </div>
  );
}
