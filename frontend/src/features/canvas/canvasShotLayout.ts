// A shot table (拆镜头表) laid out as shots: per row, a first frame to draw feeding a video node that carries the
// shot's length and lines, left to right beside the table. The same pair the storyboard layout makes, so the
// one-click film takes these clips the same way (backend/app/core/canvas_film.py reads lines after 台词：).
// One face per character: each character seen in more than one shot gets a look sheet of their own (a picture of
// them alone, drawn from the words the server writes, `sheet_prompt`), fed to every first frame they are in as a
// reference picture. The frames share the face and the clothes, not the framing, which feeding a whole earlier frame
// also handed on. Each frame's words carry the looks and say the reference is for those only (the server's beats).
import { t } from '../../i18n';
import { connect, DEFAULT_SIZES, newNode } from './canvasGraph';
import type { CanvasDoc, CanvasEdge, CanvasNode, TableCast, TableShot } from './canvasTypes';

export const SHOT_COLUMN = 360;
export const SHOT_PAIR_GAP = 40;
export const SHOT_MARGIN = 80;
/** Room between the row of look sheets and the row of first frames below it. */
export const SHEET_GAP = 60;
/** The lead the lines follow in a clip's text. Not translated: the server finds the lines by it (canvas_storyboard.json `dialogue_lead`). */
export const LINES_LEAD = '台词：';

/** The words a shot's first frame is drawn from: what is seen, then the camera. */
export function framePrompt(shot: TableShot) {
  const camera = [shot.size, shot.motion].filter(Boolean).join('，');
  return `${shot.desc}${camera ? `，${camera}` : ''}`.slice(0, 800);
}

/** The words a shot's clip is made from: what happens, then its lines after the lead the film reads them by. */
export function clipPrompt(shot: TableShot) {
  return [shot.desc, shot.dialogue ? `${LINES_LEAD}${shot.dialogue}` : ''].filter(Boolean).join('\n').slice(0, 4000);
}

/** The nodes and connections for these shots, placed to the right of `source` (the table they came from).
 *  `framePrompts` are the server's words for each first frame (the table's beats, with who is in it described);
 *  a shot without one is drawn from what is seen and the camera. */
export function shotPairs(
  source: CanvasNode, shots: readonly TableShot[], framePrompts: readonly string[] = [], cast: readonly TableCast[] = [],
): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  const [, frameHeight] = DEFAULT_SIZES.image_gen;
  const left = source.x + source.width + SHOT_MARGIN;
  const nodes: CanvasNode[] = [];
  const edges: CanvasEdge[] = [];
  const frames: Array<{ node: CanvasNode; characters: readonly string[] }> = [];
  shots.forEach((shot, index) => {
    const x = left + index * SHOT_COLUMN;
    const frame = newNode('image_gen', x, source.y, { label: t('镜{0} 首帧', [index + 1]), prompt: framePrompts[index] || framePrompt(shot) });
    const seconds = Math.round(Number(shot.seconds));
    const clip = newNode('video_gen', x, source.y + frameHeight + SHOT_PAIR_GAP, {
      label: t('镜{0} 视频', [index + 1]), prompt: clipPrompt(shot), ...(seconds > 0 ? { params: { durationSeconds: seconds } } : {}),
    });
    nodes.push(frame, clip);
    // The same edge the canvas draws for an image into a video node, set to open the clip on that picture.
    const linked = connect({ nodes: [frame, clip], edges: [] }, frame.id, clip.id);
    if (linked.ok) edges.push({ ...linked.edge, payload: { ...linked.edge.payload, role: 'first_frame' } });
    frames.push({ node: frame, characters: shot.characters ?? [] });
  });
  const sheets = castSheets(frames, cast, { x: source.x + source.width + SHOT_MARGIN, y: source.y });
  return { nodes: [...sheets.nodes, ...nodes], edges: [...edges, ...sheets.edges] };
}

/**
 * A look sheet for each character the server wrote one for and who is in these frames, in a row above them, each
 * feeding every frame its character is in as a reference picture.
 */
export function castSheets(
  frames: ReadonlyArray<{ node: CanvasNode; characters: readonly string[] }>, cast: readonly TableCast[], at: { x: number; y: number },
): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  const [, height] = DEFAULT_SIZES.image_gen;
  const nodes: CanvasNode[] = [];
  const edges: CanvasEdge[] = [];
  for (const member of cast) {
    const theirs = frames.filter(frame => frame.characters.includes(member.name));
    if (!member.sheet_prompt || !theirs.length) continue;
    const sheet = newNode('image_gen', at.x + nodes.length * SHOT_COLUMN, at.y - height - SHEET_GAP, {
      label: t('{0}·定妆', [member.name]), prompt: member.sheet_prompt,
    });
    nodes.push(sheet);
    for (const frame of theirs) {
      const linked = connect({ nodes: [sheet, frame.node], edges: [] }, sheet.id, frame.node.id);
      if (linked.ok) edges.push({ ...linked.edge, payload: { ...linked.edge.payload, role: 'ref_image' } });
    }
  }
  return { nodes, edges };
}

/** `doc` with the shots laid out, or null when `sourceId` is gone. */
export function layOutShotTable(
  doc: CanvasDoc, sourceId: string, shots: readonly TableShot[], framePrompts: readonly string[] = [], cast: readonly TableCast[] = [],
): CanvasDoc | null {
  const source = doc.nodes.find(node => node.id === sourceId);
  if (!source || !shots.length) return null;
  const made = shotPairs(source, shots, framePrompts, cast);
  return { ...doc, nodes: [...doc.nodes, ...made.nodes], edges: [...doc.edges, ...made.edges] };
}
