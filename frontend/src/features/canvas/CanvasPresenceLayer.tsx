// Idea from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors): same-account multi-window presence.
import { memo, useEffect, useMemo, useRef, type CSSProperties, type RefObject } from 'react';

import { t } from '../../i18n';
import type { SurfaceHandle } from './CanvasSurface';
import type { Rect } from './canvasTypes';
import type { PresencePeer, PresenceRect } from './useCanvasPresence';
import './CanvasPresenceLayer.css';

const FALLBACK_COLOR = '#7c5cff';

interface LayerProps {
  surface: RefObject<SurfaceHandle | null>;
  peers: readonly PresencePeer[];
  cursors: ReadonlyMap<string, { x: number; y: number }>;
  drags: ReadonlyMap<string, readonly PresenceRect[]>;
  selections: ReadonlyMap<string, readonly string[]>;
  /** Where nodes are, to ring the ones another window has selected. */
  nodes: readonly (Rect & { id: string })[];
}

const colorStyle = (color: string, extra: CSSProperties = {}) => ({ ...extra, '--cpl-color': color }) as CSSProperties;

/**
 * What the other windows on this canvas are doing, drawn over the surface. It follows pan and zoom the
 * way the surface's own world does: a transform written straight onto one element on every view change,
 * so moving the view never re-renders it. Cursors and lines keep their screen size through `--cpl-inv`.
 */
export const CanvasPresenceLayer = memo(function CanvasPresenceLayer({ surface, peers, cursors, drags, selections, nodes }: LayerProps) {
  const root = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);

  useEffect(() => surface.current?.subscribe(view => {
    if (world.current) world.current.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
    root.current?.style.setProperty('--cpl-inv', String(view.zoom > 0 ? 1 / view.zoom : 1));
  }), [surface]);

  const byPeer = useMemo(() => new Map(peers.map(peer => [peer.client_id, peer])), [peers]);
  const byId = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes]);
  const colorOf = (id: string) => byPeer.get(id)?.color || FALLBACK_COLOR;

  // Only windows that are still on the canvas are drawn: a message can outrun the peer list.
  const known = (id: string) => byPeer.has(id);
  const rings = [...selections].filter(([id]) => known(id)).flatMap(([peer, ids]) => ids.map(id => ({ peer, node: byId.get(id) })).filter(item => item.node));
  const outlines = [...drags].filter(([id]) => known(id)).flatMap(([peer, rects]) => rects.map(rect => ({ peer, rect })));
  const pointers = [...cursors].filter(([id]) => known(id));

  return (
    <div ref={root} className="cpl-layer" aria-hidden="true">
      <div ref={world} className="cpl-world">
        {rings.map(({ peer, node }) => (
          <div
            key={`ring:${peer}:${node!.id}`} className="cpl-ring" data-peer={peer}
            style={colorStyle(colorOf(peer), { transform: `translate(${node!.x}px, ${node!.y}px)`, width: node!.width, height: node!.height })}
          />
        ))}
        {outlines.map(({ peer, rect }) => (
          <div
            key={`drag:${peer}:${rect.id}`} className="cpl-drag" data-peer={peer}
            style={colorStyle(colorOf(peer), { transform: `translate(${rect.x}px, ${rect.y}px)`, width: rect.width, height: rect.height })}
          />
        ))}
        {pointers.map(([peer, point]) => (
          <div key={`cursor:${peer}`} className="cpl-cursor" data-peer={peer} style={colorStyle(colorOf(peer), { transform: `translate(${point.x}px, ${point.y}px)` })}>
            <div className="cpl-cursor__body">
              <svg className="cpl-cursor__arrow" width="16" height="20" viewBox="0 0 16 20" aria-hidden="true">
                <path d="M1 1 L1 16 L5 12 L8 19 L11 17.6 L8 11 L14 11 Z" />
              </svg>
              <span className="cpl-cursor__label">{byPeer.get(peer)?.label || t('另一个窗口')}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

/** The toolbar's note of how many other windows have this canvas open, one dot per window in its colour. */
export function CanvasPresencePeers({ peers }: { peers: readonly PresencePeer[] }) {
  if (!peers.length) return null;
  const text = t('同时打开：{0} 个窗口', [peers.length]);
  return (
    <span className="cpl-peers" title={peers.map(peer => peer.label).join('\n')} aria-label={text}>
      <span className="cpl-peers__dots" aria-hidden="true">
        {peers.slice(0, 5).map(peer => <span key={peer.client_id} className="cpl-peers__dot" style={colorStyle(peer.color || FALLBACK_COLOR)} />)}
      </span>
      <span className="cpl-peers__text">{text}</span>
    </span>
  );
}
