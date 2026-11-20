import { useCallback, useRef, useState } from 'react';

import { CanvasLightbox, type LightboxMedia } from './CanvasLightbox';
import { nodeTitle } from './canvasLabels';
import { useOpenGestures, type OpenTarget } from './canvasOpenGestures';
import type { CanvasNode } from './canvasTypes';

export interface BoundShot { sceneId: string; shotId: number | null }

/** The scene and shot a card belongs to in the project, or null when it stands on its own. */
export function boundShot(node: Pick<CanvasNode, 'payload'>): BoundShot | null {
  const binding = node.payload.binding;
  if (binding?.sceneId) return { sceneId: binding.sceneId, shotId: binding.shotId ?? null };
  if (node.payload.sceneId) return { sceneId: node.payload.sceneId, shotId: node.payload.shotId ?? null };
  return null;
}

/**
 * What opens from a card: its picture large on a click, its clip in a player on a double click,
 * and on a double click anywhere else the shot it is tied to, in the project.
 */
export function useCanvasOpen({ nodes, onOpenShot }: { nodes: readonly CanvasNode[]; onOpenShot?: (shot: BoundShot) => void }) {
  const [media, setMedia] = useState<LightboxMedia | null>(null);
  const latest = useRef({ nodes, onOpenShot });
  latest.current = { nodes, onOpenShot };

  const open = useCallback((target: OpenTarget) => {
    const node = latest.current.nodes.find(item => item.id === target.nodeId);
    if (!node) return;
    if (target.kind === 'node') {
      const shot = boundShot(node);
      if (shot) latest.current.onOpenShot?.(shot);
      return;
    }
    // One player at a time: the card's own stops when the large one starts.
    if (target.kind === 'video') target.player.pause();
    setMedia({ medium: target.kind, url: target.url, title: nodeTitle(node) });
  }, []);

  const close = useCallback(() => setMedia(null), []);
  const gestures = useOpenGestures(open);
  return { gestures, dialog: media ? <CanvasLightbox media={media} onClose={close} /> : null };
}
