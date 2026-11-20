// Ready-made node arrangements dropped onto the canvas as one edit. Capability after NovaNova Studio's
// canvas templates (MIT); built from this project's own nodes, connection rules and frames.
import { FRAME_HEADER, FRAME_PADDING, groupNodes2 } from './canvasFrames';
import { CANVAS_MAX_EDGES, CANVAS_MAX_NODES, clampCoord } from './canvasGeometry';
import { DEFAULT_SIZES, connect, newNode, roleChoices } from './canvasGraph';
import type { CanvasDoc, CanvasEdge } from './canvasTypes';

/** Room between the two frames, and between them and the video node. */
export const TEMPLATE_GAP = 40;

export interface FirstLastLabels {
  group: string;
  first: string;
  last: string;
}

export type TemplateResult =
  | { ok: true; doc: CanvasDoc; groupId: string; firstId: string; lastId: string; videoId: string }
  | { ok: false; reason: 'limit' | 'refused' };

/**
 * First frame and last frame, stacked, feeding one video node on their right; all three in a group
 * whose top-left corner is `at`. The two edges carry the roles `first_frame` and `last_frame`, and
 * each is checked against the connection rules: if either is refused nothing is added.
 */
export function firstLastFrameTemplate(doc: CanvasDoc, at: { x: number; y: number }, labels: FirstLastLabels): TemplateResult {
  if (doc.nodes.length + 4 > CANVAS_MAX_NODES || doc.edges.length + 2 > CANVAS_MAX_EDGES) return { ok: false, reason: 'limit' };
  const [frameWidth, frameHeight] = DEFAULT_SIZES.image_gen;
  const [, videoHeight] = DEFAULT_SIZES.video_gen;
  const left = clampCoord(Math.round(at.x) + FRAME_PADDING);
  const top = clampCoord(Math.round(at.y) + FRAME_HEADER + FRAME_PADDING);
  const first = newNode('image_gen', left, top, { label: labels.first });
  const last = newNode('image_gen', left, top + frameHeight + TEMPLATE_GAP, { label: labels.last });
  // The video sits level with the middle of the pair, so the two edges fan into it evenly.
  const video = newNode('video_gen', left + frameWidth + TEMPLATE_GAP * 2, top + Math.round((frameHeight * 2 + TEMPLATE_GAP - videoHeight) / 2));

  let next: CanvasDoc = { ...doc, nodes: [...doc.nodes, first, last, video] };
  for (const [source, role] of [[first, 'first_frame'], [last, 'last_frame']] as const) {
    const wired = connect(next, source.id, video.id);
    if (!wired.ok || !roleChoices(source, video).includes(role)) return { ok: false, reason: 'refused' };
    const edge: CanvasEdge = { ...wired.edge, payload: { ...wired.edge.payload, role } };
    next = { ...next, edges: [...next.edges, edge] };
  }
  const grouped = groupNodes2(next, new Set([first.id, last.id, video.id]), labels.group);
  if (!grouped) return { ok: false, reason: 'refused' };
  return { ok: true, doc: grouped.doc, groupId: grouped.groupId, firstId: first.id, lastId: last.id, videoId: video.id };
}
