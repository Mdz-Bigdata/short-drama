import type { CanvasNode, NodeKind, NodeParams, RunAssessment } from './canvasTypes';

export type BatchKind = 'image_gen' | 'video_gen';

export interface BatchRow {
  key: string;
  kind: BatchKind;
  title: string;
  prompt: string;
  model: string;
  durationSeconds?: number;
  size?: string;
  count: number;
}

export const MAX_BATCH_ROWS = 50;
const NODE_SIZE: Record<BatchKind, { width: number; height: number }> = {
  image_gen: { width: 300, height: 320 }, video_gen: { width: 320, height: 340 },
};
const GAP = 40;

let serial = 0;
export function newRow(kind: BatchKind = 'image_gen', over: Partial<BatchRow> = {}): BatchRow {
  serial += 1;
  return { key: `row-${Date.now().toString(36)}-${serial}`, kind, title: '', prompt: '', model: '', count: 1, ...over };
}

/**
 * Rows pasted from a spreadsheet: one row per line, cells split by tabs. The cells are read in order as
 * prompt, then optionally title, kind (图片 / 视频 / image / video), and seconds; an empty line is skipped.
 */
export function rowsFromPaste(text: string, fallbackKind: BatchKind = 'image_gen'): BatchRow[] {
  return text.split(/\r?\n/).map(line => line.split('\t').map(cell => cell.trim())).filter(cells => cells[0])
    .slice(0, MAX_BATCH_ROWS)
    .map(([prompt, title = '', kindCell = '', seconds = '']) => {
      const kind: BatchKind = /视频|video/i.test(kindCell) ? 'video_gen' : /图|image/i.test(kindCell) ? 'image_gen' : fallbackKind;
      const duration = Number.parseInt(seconds, 10);
      return newRow(kind, { prompt, title, ...(kind === 'video_gen' && duration > 0 ? { durationSeconds: duration } : {}) });
    });
}

export type RowProblem = 'empty_prompt' | 'count';

/** What keeps each row from being created; a row with none can be created. */
export function rowProblems(row: BatchRow, maxCount: number): RowProblem[] {
  const problems: RowProblem[] = [];
  if (!row.prompt.trim()) problems.push('empty_prompt');
  if (!Number.isInteger(row.count) || row.count < 1 || row.count > Math.max(1, maxCount)) problems.push('count');
  return problems;
}

/** The nodes the rows become, laid in a grid of up to `columns` from `origin`, in row order. */
export function nodesFromRows(
  rows: BatchRow[], origin: { x: number; y: number }, makeId: () => string, columns = 5,
): CanvasNode[] {
  const width = Math.max(...Object.values(NODE_SIZE).map(size => size.width)) + GAP;
  const height = Math.max(...Object.values(NODE_SIZE).map(size => size.height)) + GAP;
  return rows.map((row, index) => {
    const params: NodeParams = { count: row.count };
    if (row.model) params.model = row.model;
    if (row.size) params.size = row.size;
    if (row.kind === 'video_gen' && row.durationSeconds) params.durationSeconds = row.durationSeconds;
    return {
      id: makeId(),
      kind: row.kind as NodeKind,
      track: 'freezone',
      x: Math.round(origin.x + (index % columns) * width),
      y: Math.round(origin.y + Math.floor(index / columns) * height),
      ...NODE_SIZE[row.kind],
      artifact_id: null,
      payload: { prompt: row.prompt.trim(), params, ...(row.title.trim() ? { title: row.title.trim() } : {}) },
    };
  });
}

/** The total the confirmation shows: per currency what is priced, and how many items have no price. */
export function totalsOf(assessment: RunAssessment): { totals: Array<{ currency: string; cost: number }>; unpriced: number; blocked: number; items: number } {
  return {
    totals: assessment.estimate.totals,
    unpriced: assessment.estimate.unpriced_items,
    blocked: assessment.nodes.filter(node => node.quote === 'blocked').length,
    items: assessment.estimate.items,
  };
}
