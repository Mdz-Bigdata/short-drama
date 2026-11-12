// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-node-search.ts.
//
// Upstream filters by substring and sorts by last update; our nodes carry no timestamps, so hits are
// ranked by where the words were found instead: a title that starts with them, a title that holds
// them, then the node's other text.
import { labelOf } from './canvasGraph';
import { kindLabel } from './canvasLabels';
import type { CanvasNode, NodeKind } from './canvasTypes';

export type SearchField = 'title' | 'prompt' | 'text' | 'styleText' | 'output' | 'filename';

export interface SearchHit {
  id: string;
  kind: NodeKind;
  /** The node's own name, else its kind's. */
  title: string;
  field: SearchField;
  /** A stretch of the matching field; `start`..`end` is the match inside `text`. */
  snippet: { text: string; start: number; end: number };
}

const FIELD_ORDER: readonly SearchField[] = ['title', 'prompt', 'text', 'styleText', 'output', 'filename'];
const BEFORE = 24;
const AFTER = 64;
const TITLE_MAX = 80;

function fields(node: CanvasNode): Array<[SearchField, string]> {
  const { payload } = node;
  const output = payload.output;
  const values: Array<[SearchField, unknown]> = [
    ['title', labelOf(node)],
    ['prompt', payload.prompt],
    ['text', payload.text],
    ['styleText', payload.styleText],
    // An HTML page's text is markup, not something a person would look for.
    ['output', output?.html ? '' : output?.text],
    ['filename', output?.filename],
  ];
  return values.filter((entry): entry is [SearchField, string] => typeof entry[1] === 'string' && entry[1].trim() !== '');
}

/** Lower-cased without whitespace, with where each kept character sat in the original. */
function fold(text: string): { folded: string; at: number[] } {
  let folded = '';
  const at: number[] = [];
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (/\s/.test(char)) continue;
    const lower = char.toLocaleLowerCase();
    // Keep one entry per folded code unit so the two stay aligned.
    for (let unit = 0; unit < lower.length; unit += 1) at.push(index);
    folded += lower;
  }
  return { folded, at };
}

function locate(text: string, needle: string): { start: number; end: number; prefix: boolean } | null {
  const { folded, at } = fold(text);
  const found = folded.indexOf(needle);
  if (found < 0) return null;
  return { start: at[found], end: at[found + needle.length - 1] + 1, prefix: found === 0 };
}

function snippetOf(text: string, start: number, end: number, field: SearchField) {
  // Same length replacement, so the match range still points at the same characters.
  const flat = text.replace(/\s/g, ' ');
  const from = field === 'title' ? 0 : Math.max(0, start - BEFORE);
  const to = field === 'title' ? Math.min(flat.length, Math.max(end, TITLE_MAX)) : Math.min(flat.length, end + AFTER);
  const lead = from > 0 ? '…' : '';
  const tail = to < flat.length ? '…' : '';
  return { text: `${lead}${flat.slice(from, to)}${tail}`, start: start - from + lead.length, end: end - from + lead.length };
}

/** Nodes whose name or text holds the query, ignoring case and spaces, best matches first. */
export function searchNodes(nodes: readonly CanvasNode[], query: string, options: { limit?: number } = {}): SearchHit[] {
  const limit = options.limit ?? 80;
  const needle = fold(query).folded;
  if (!needle) return [];
  const ranked: Array<{ hit: SearchHit; rank: number; order: number }> = [];
  nodes.forEach((node, order) => {
    for (const [field, value] of fields(node)) {
      const match = locate(value, needle);
      if (!match) continue;
      const rank = field === 'title' ? (match.prefix ? 0 : 1) : 1 + FIELD_ORDER.indexOf(field);
      ranked.push({
        hit: { id: node.id, kind: node.kind, title: labelOf(node) || kindLabel(node.kind), field, snippet: snippetOf(value, match.start, match.end, field) },
        rank,
        order,
      });
      // The first field that matches speaks for the node.
      return;
    }
  });
  return ranked
    .sort((left, right) => left.rank - right.rank || left.order - right.order)
    .slice(0, limit)
    .map(item => item.hit);
}
