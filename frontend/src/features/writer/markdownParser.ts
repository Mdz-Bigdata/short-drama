export interface MarkdownTextBlock {
  kind: 'text';
  source: string;
}

export interface MarkdownTableBlock {
  kind: 'table';
  source: string;
  caption: string;
  headers: string[];
  rows: string[][];
}

export type MarkdownBlock = MarkdownTextBlock | MarkdownTableBlock;

const TABLE_DIVIDER = /^:?-{3,}:?$/;

function splitPipeRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells: string[] = [];
  let cell = '';
  let escaped = false;
  for (const character of trimmed) {
    if (escaped) {
      cell += character;
      escaped = false;
    } else if (character === '\\') {
      escaped = true;
    } else if (character === '|') {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += character;
    }
  }
  cells.push(cell.trim());
  return cells;
}

function isTableAt(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length || !lines[index].includes('|')) return false;
  const separators = splitPipeRow(lines[index + 1]);
  return separators.length > 1 && separators.every(cell => TABLE_DIVIDER.test(cell));
}

function headingText(line: string): string | null {
  const match = line.trim().match(/^#{1,6}\s+(.+)$/);
  return match ? match[1].replace(/\*\*/g, '').trim() : null;
}

export function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  let textLines: string[] = [];
  let latestHeading = '';

  const flushText = () => {
    const text = textLines.join('\n').trim();
    if (text) blocks.push({ kind: 'text', source: text });
    textLines = [];
  };

  for (let index = 0; index < lines.length;) {
    if (!isTableAt(lines, index)) {
      const heading = headingText(lines[index]);
      if (heading) latestHeading = heading;
      textLines.push(lines[index]);
      index += 1;
      continue;
    }
    flushText();
    const tableLines = [lines[index], lines[index + 1]];
    const headers = splitPipeRow(lines[index]);
    index += 2;
    const rows: string[][] = [];
    while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
      tableLines.push(lines[index]);
      const values = splitPipeRow(lines[index]);
      rows.push(headers.map((_, cellIndex) => values[cellIndex] || ''));
      index += 1;
    }
    blocks.push({
      kind: 'table',
      source: tableLines.join('\n'),
      caption: latestHeading || `剧本数据表 ${blocks.filter(block => block.kind === 'table').length + 1}`,
      headers,
      rows,
    });
  }
  flushText();
  return blocks;
}

function splitTextBlock(source: string, targetCharacters: number): string[] {
  const chunks: string[] = [];
  let remaining = source.trim();
  const minimumBreak = Math.floor(targetCharacters * 0.55);
  while (remaining.length > targetCharacters) {
    const window = remaining.slice(0, targetCharacters + 1);
    const candidates = ['\n', '。', '！', '？', ';', '；'].map(token => window.lastIndexOf(token));
    const best = Math.max(...candidates);
    const breakAt = best >= minimumBreak ? best + 1 : targetCharacters;
    chunks.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
}

export function paginateMarkdown(source: string, targetCharacters = 1200): MarkdownBlock[][] {
  const target = Math.max(320, targetCharacters);
  const pages: MarkdownBlock[][] = [];
  let current: MarkdownBlock[] = [];
  let currentLength = 0;
  const flush = () => {
    if (current.length) pages.push(current);
    current = [];
    currentLength = 0;
  };
  parseMarkdownBlocks(source).forEach(block => {
    const pieces: MarkdownBlock[] = block.kind === 'text'
      ? splitTextBlock(block.source, target).map(piece => ({ kind: 'text', source: piece }))
      : [block];
    pieces.forEach(piece => {
      const length = piece.source.length;
      if (current.length && currentLength + length > target) flush();
      current.push(piece);
      currentLength += length;
      if (length >= target) flush();
    });
  });
  flush();
  return pages.length ? pages : [[]];
}
