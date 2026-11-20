// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/components/canvas/canvas-viewport.tsx (touch pinch and pan).
import { useCallback, useEffect, useRef, type RefObject } from 'react';

import { clampZoom } from './canvasGeometry';
import type { Viewport } from './canvasTypes';

export interface TouchPinchOptions {
  enabled?: boolean;
  /** Whether one finger starting on `target` pans the canvas; by default anywhere but on a node or edge. */
  canPanFrom?: (target: Element | null) => boolean;
}

interface Pinch {
  ids: [number, number];
  distance: number;
  worldX: number;
  worldY: number;
  zoom: number;
}

interface Pan {
  id: number;
  startX: number;
  startY: number;
  viewX: number;
  viewY: number;
}

const defaultCanPan = (target: Element | null) => !target?.closest('[data-node-id],[data-edge-id]');

/**
 * Touch gestures on the canvas surface: two fingers pinch-zoom around their midpoint (and pan with it),
 * one finger on empty canvas pans. Mouse and pen pointers are left alone. Gestures this hook claims
 * stop propagating, so the surface's own pointer handlers do not start a marquee under them.
 * The surface needs `touch-action: none` in its CSS so the browser does not scroll or zoom the page itself.
 * Returns whether a touch gesture is in progress.
 */
export function useTouchPinch(
  surface: RefObject<HTMLElement | null>,
  getView: () => Viewport,
  setView: (view: Viewport) => void,
  options: TouchPinchOptions = {},
): () => boolean {
  const { enabled = true } = options;
  const latest = useRef({ getView, setView, canPanFrom: options.canPanFrom ?? defaultCanPan });
  useEffect(() => {
    latest.current = { getView, setView, canPanFrom: options.canPanFrom ?? defaultCanPan };
  });
  const active = useRef(false);

  useEffect(() => {
    const element = surface.current;
    if (!element || !enabled) return;
    const points = new Map<number, { x: number; y: number }>();
    let pinch: Pinch | null = null;
    let pan: Pan | null = null;

    const startPinch = () => {
      const [[firstId, first], [secondId, second]] = Array.from(points.entries());
      const rect = element.getBoundingClientRect();
      const view = latest.current.getView();
      const centerX = (first.x + second.x) / 2 - rect.left;
      const centerY = (first.y + second.y) / 2 - rect.top;
      pinch = {
        ids: [firstId, secondId],
        distance: Math.max(Math.hypot(second.x - first.x, second.y - first.y), 1),
        worldX: (centerX - view.x) / view.zoom,
        worldY: (centerY - view.y) / view.zoom,
        zoom: view.zoom,
      };
      pan = null;
      active.current = true;
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return;
      const target = event.target instanceof Element ? event.target : null;
      points.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (points.size >= 2) {
        if (!pinch) startPinch();
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (!latest.current.canPanFrom(target)) return;
      event.preventDefault();
      event.stopPropagation();
      const view = latest.current.getView();
      pan = { id: event.pointerId, startX: event.clientX, startY: event.clientY, viewX: view.x, viewY: view.y };
      active.current = true;
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType !== 'touch' || !points.has(event.pointerId)) return;
      points.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pinch) {
        const first = points.get(pinch.ids[0]);
        const second = points.get(pinch.ids[1]);
        if (!first || !second) return;
        event.preventDefault();
        const rect = element.getBoundingClientRect();
        const centerX = (first.x + second.x) / 2 - rect.left;
        const centerY = (first.y + second.y) / 2 - rect.top;
        const distance = Math.max(Math.hypot(second.x - first.x, second.y - first.y), 1);
        const zoom = clampZoom(pinch.zoom * (distance / pinch.distance));
        latest.current.setView({ zoom, x: centerX - pinch.worldX * zoom, y: centerY - pinch.worldY * zoom });
        return;
      }
      if (!pan || pan.id !== event.pointerId) return;
      event.preventDefault();
      const view = latest.current.getView();
      latest.current.setView({ zoom: view.zoom, x: pan.viewX + event.clientX - pan.startX, y: pan.viewY + event.clientY - pan.startY });
    };

    const onPointerEnd = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return;
      if (pinch && pinch.ids.includes(event.pointerId)) {
        // Lifting either finger ends the pinch; the remaining finger does not turn into a pan.
        pinch = null;
        pan = null;
        points.clear();
        active.current = false;
        return;
      }
      points.delete(event.pointerId);
      if (pan && pan.id === event.pointerId) {
        pan = null;
        active.current = false;
      }
    };

    element.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove, { passive: false });
    window.addEventListener('pointerup', onPointerEnd);
    window.addEventListener('pointercancel', onPointerEnd);
    return () => {
      element.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerEnd);
      window.removeEventListener('pointercancel', onPointerEnd);
      active.current = false;
    };
  }, [surface, enabled]);

  return useCallback(() => active.current, []);
}
