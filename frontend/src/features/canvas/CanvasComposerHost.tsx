import { useCallback, useEffect, useState, type RefObject } from 'react';

import { CanvasComposerDock } from './CanvasComposerDock';
import { dockPlacement, hasComposer } from './canvasComposer';
import type { SurfaceHandle } from './CanvasSurface';
import type { CanvasNode, LatestRun, Viewport } from './canvasTypes';
import { useRunQuote } from './useRunQuote';

const COLLAPSED_KEY = 'canvas.composerDock.collapsed';

function storedCollapsed() {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

interface HostProps {
  surface: RefObject<SurfaceHandle | null>;
  /** The one selected node, or null when none or several are selected. */
  node: CanvasNode | null;
  latest?: LatestRun;
  projectId: string;
  canvasId: string;
  version: number;
  /** The canvas on the server is the canvas on screen: only then does a quote describe what would run. */
  settled: boolean;
  /** Changes when a run starts or ends, so a quote that depended on an input is asked again. */
  refreshKey?: string;
}

/** Keeps the composer dock under the selected node as the view moves, and asks for its quote. */
export function CanvasComposerHost({ surface, node, latest, projectId, canvasId, version, settled, refreshKey }: HostProps) {
  const [state, setState] = useState<{ view: Viewport; width: number; height: number } | null>(null);
  useEffect(() => surface.current?.subscribe((view, size) => setState({ view, width: size.width, height: size.height })), [surface]);
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const toggle = useCallback(() => setCollapsed(value => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, value ? '0' : '1');
    } catch {
      // Private mode: the choice lasts for this visit only.
    }
    return !value;
  }), []);

  const shown = node && hasComposer(node) ? node : null;
  const quote = useRunQuote(projectId, canvasId, shown && !collapsed ? shown.id : null, version, settled, refreshKey);
  if (!shown || !state) return null;
  const placement = dockPlacement(shown, state.view, state);
  if (!placement) return null;
  return <CanvasComposerDock key={shown.id} node={shown} latest={latest} quote={quote} placement={placement} collapsed={collapsed} onToggle={toggle} />;
}
