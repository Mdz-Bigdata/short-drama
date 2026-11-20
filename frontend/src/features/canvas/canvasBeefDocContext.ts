import { createContext, useContext } from 'react';

import { producedMedium } from './canvasBeefReferences';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

/** The board's document, for additions that sit inside another session's components (the composer dock). */
export const CanvasBeefDocContext = createContext<CanvasDoc | null>(null);

export const useCanvasBeefDoc = () => useContext(CanvasBeefDocContext);

/** What a node is connected to that the prompt optimizer can use: the text of notes, and how many pictures. */
export function referencesFor(node: CanvasNode, doc: CanvasDoc | null): { texts: string[]; images: number } {
  if (!doc) return { texts: [], images: 0 };
  const byId = new Map(doc.nodes.map(item => [item.id, item]));
  const sources = doc.edges.filter(edge => edge.target === node.id).map(edge => byId.get(edge.source)).filter((item): item is CanvasNode => Boolean(item));
  return {
    texts: sources.filter(item => item.kind === 'note').map(item => String(item.payload.text ?? '').trim()).filter(Boolean),
    images: sources.filter(item => producedMedium(item) === 'image').length,
  };
}
