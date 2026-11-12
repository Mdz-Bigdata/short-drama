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
  omittedRows?: number;
}

export type MarkdownBlock = MarkdownTextBlock | MarkdownTableBlock;

const TABLE_DIVIDER = /^:?-{3,}:?$/;
export const MARKDOWN_PARSE_BUDGETS = {
  maxTables: 200,
  maxTotalTableRows: 5_000,
  maxTableColumns: 64,
  maxTotalTableCells: 32_000,
  maxTextLinesPerBlock: 1_000,
  maxTextCharactersPerBlock: 64 * 1_024,
  maxTableRowsPerPage: 100,
  maxTableCellsPerPage: 2_048,
} as const;

export const MARKDOWN_RENDER_BUDGETS = {
  maxBlocks: 100,
  maxTextLines: 800,
  maxTableCells: 2_048,
  maxContentUnits: 2_400,
  // Includes structural wrappers such as rows, lists and table regions. The
  // content-unit limits above keep the actual subtree below this ceiling.
  maxDomNodes: 5_000,
} as const;

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
      if (cells.length < MARKDOWN_PARSE_BUDGETS.maxTableColumns) cells.push(cell.trim());
      cell = '';
    } else if (cells.length < MARKDOWN_PARSE_BUDGETS.maxTableColumns) {
      cell += character;
    }
  }
  if (cells.length < MARKDOWN_PARSE_BUDGETS.maxTableColumns) cells.push(cell.trim());
  return cells;
}

function isTableAt(line: string | undefined, nextLine: string | undefined): boolean {
  if (line === undefined || nextLine === undefined || !line.includes('|')) return false;
  const separators = splitPipeRow(nextLine);
  return separators.length > 1 && separators.every(cell => TABLE_DIVIDER.test(cell));
}

function headingText(line: string): string | null {
  const match = line.trim().match(/^#{1,6}\s+(.+)$/);
  return match ? match[1].replace(/\*\*/g, '').trim() : null;
}

export function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  return scanMarkdown(source).blocks;
}

/** The blocks, and for each table where its header line and every kept row line start in the source. */
function scanMarkdown(source: string): { blocks: MarkdownBlock[]; tableLineStarts: number[][] } {
  const cursor = createLineCursor(String(source || ''));
  const blocks: MarkdownBlock[] = [];
  const tableLineStarts: number[][] = [];
  let textLines: string[] = [];
  let textCharacters = 0;
  let latestHeading = '';
  let tableCount = 0;
  let totalTableRows = 0;
  let totalTableCells = 0;

  const flushText = () => {
    const text = textLines.join('\n').trim();
    if (text) blocks.push({ kind: 'text', source: text });
    textLines = [];
    textCharacters = 0;
  };

  const appendText = (line: string) => {
    const nextLength = textCharacters + line.length + (textLines.length ? 1 : 0);
    if (
      textLines.length >= MARKDOWN_PARSE_BUDGETS.maxTextLinesPerBlock
      || (textLines.length > 0 && nextLength > MARKDOWN_PARSE_BUDGETS.maxTextCharactersPerBlock)
    ) {
      flushText();
    }
    textLines.push(line);
    textCharacters += line.length + (textLines.length > 1 ? 1 : 0);
  };

  while (cursor.peek() !== undefined) {
    const line = cursor.peek() as string;
    if (!isTableAt(line, cursor.peek(1)) || tableCount >= MARKDOWN_PARSE_BUDGETS.maxTables) {
      const heading = headingText(line);
      if (heading) latestHeading = heading;
      appendText(line);
      cursor.take();
      continue;
    }
    flushText();
    const lineStarts = [cursor.position()];
    const headerLine = cursor.take() as string;
    const dividerLine = cursor.take() as string;
    const tableLines = [headerLine, dividerLine];
    const headers = splitPipeRow(headerLine);
    const rows: string[][] = [];
    let omittedRows = 0;
    while (cursor.peek() !== undefined && cursor.peek()?.trim() && cursor.peek()?.includes('|')) {
      const rowStart = cursor.position();
      const rowLine = cursor.take() as string;
      if (
        totalTableRows < MARKDOWN_PARSE_BUDGETS.maxTotalTableRows
        && totalTableCells + headers.length <= MARKDOWN_PARSE_BUDGETS.maxTotalTableCells
      ) {
        tableLines.push(rowLine);
        lineStarts.push(rowStart);
        const values = splitPipeRow(rowLine);
        rows.push(headers.map((_, cellIndex) => values[cellIndex] || ''));
        totalTableRows += 1;
        totalTableCells += headers.length;
      } else {
        omittedRows += 1;
      }
    }
    tableCount += 1;
    tableLineStarts.push(lineStarts);
    blocks.push({
      kind: 'table',
      source: tableLines.join('\n'),
      caption: latestHeading || `剧本数据表 ${tableCount}`,
      headers,
      rows,
      ...(omittedRows > 0 ? { omittedRows } : {}),
    });
  }
  flushText();
  return { blocks, tableLineStarts };
}

interface MarkdownLineCursor {
  peek(offset?: number): string | undefined;
  take(): string | undefined;
  /** Where the line `peek()` returns starts in the source. */
  position(): number;
}

function createLineCursor(source: string): MarkdownLineCursor {
  const buffer: string[] = [];
  const starts: number[] = [];
  let sourceIndex = 0;

  const readLine = (): string | undefined => {
    if (sourceIndex > source.length) return undefined;
    starts.push(sourceIndex);
    if (sourceIndex === source.length) {
      sourceIndex += 1;
      return '';
    }
    let lineEnd = sourceIndex;
    while (lineEnd < source.length && source[lineEnd] !== '\n' && source[lineEnd] !== '\r') {
      lineEnd += 1;
    }
    const line = source.slice(sourceIndex, lineEnd);
    if (lineEnd === source.length) {
      sourceIndex = source.length + 1;
    } else {
      const isCrLf = source[lineEnd] === '\r' && source[lineEnd + 1] === '\n';
      sourceIndex = lineEnd + (isCrLf ? 2 : 1);
    }
    return line;
  };

  return {
    peek(offset = 0) {
      while (buffer.length <= offset) {
        const line = readLine();
        if (line === undefined) break;
        buffer.push(line);
      }
      return buffer[offset];
    },
    take() {
      const line = this.peek();
      if (line !== undefined) {
        buffer.shift();
        starts.shift();
      }
      return line;
    },
    position() {
      return this.peek() === undefined ? source.length : starts[0];
    },
  };
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
      : Array.from(
        {
          length: Math.max(
            1,
            Math.ceil(block.rows.length / tableRowsPerPage(block.headers.length)),
          ),
        },
        (_, pageIndex) => {
          const rowsPerPage = tableRowsPerPage(block.headers.length);
          const rows = block.rows.slice(
            pageIndex * rowsPerPage,
            (pageIndex + 1) * rowsPerPage,
          );
          const isLastPage = (pageIndex + 1) * rowsPerPage >= block.rows.length;
          return {
            ...block,
            caption: pageIndex === 0 ? block.caption : `${block.caption}（续 ${pageIndex + 1}）`,
            rows,
            source: [block.headers.join('|'), ...rows.map(row => row.join('|'))].join('\n'),
            omittedRows: isLastPage ? block.omittedRows : undefined,
          };
        },
      );
    pieces.forEach(piece => {
      const length = piece.source.length;
      if (piece.kind === 'table') {
        // Keep each bounded table slice on its own page. Otherwise many
        // individually-small table blocks can accumulate hundreds of rows in
        // one DOM page even though every block is capped at 100 rows.
        flush();
        current.push(piece);
        currentLength = length;
        flush();
        return;
      }
      if (current.length && currentLength + length > target) flush();
      current.push(piece);
      currentLength += length;
      if (length >= target) flush();
    });
  });
  flush();
  return pages.length ? pages : [[]];
}

/**
 * Where each page of `paginateMarkdown(source)` starts in the source: a text page by its first
 * line, a table page by the header line or the first row it shows. -1 when the start is not found.
 */
export function markdownPageOffsets(source: string, pages: MarkdownBlock[][]): number[] {
  const { tableLineStarts } = scanMarkdown(source);
  let from = 0;
  let table = 0;
  let row = 0;
  return pages.map(page => {
    const first = page[0];
    if (first?.kind === 'table') {
      // Table slices come in source order, one to a page; a slice after the first opens at its first row.
      const lineStarts = tableLineStarts[table] || [];
      const found = lineStarts[row === 0 ? 0 : row + 1] ?? -1;
      row += first.rows.length;
      // Text after the slice is looked for past its last line, so a name in a cell is not taken for it.
      const lastLine = lineStarts[Math.min(row, lineStarts.length - 1)] ?? -1;
      if (lastLine >= 0) {
        const lineBreak = /[\r\n]/g;
        lineBreak.lastIndex = lastLine;
        from = Math.max(from, lineBreak.exec(source)?.index ?? source.length);
      }
      if (row >= lineStarts.length - 1) {
        table += 1;
        row = 0;
      }
      return found;
    }
    let anchor = '';
    let textLength = 0;
    page.forEach(block => {
      if (block.kind !== 'text') return;
      if (!anchor) anchor = block.source.split('\n', 1)[0].slice(0, 80);
      textLength += block.source.length;
    });
    const found = anchor ? source.indexOf(anchor, from) : -1;
    // The page's own text lies between this start and the next one, so a repeated line
    // inside it (a speaker's name, a scene heading) cannot be taken for the next page.
    if (found >= 0) from = found + textLength;
    return found;
  });
}

function tableRowsPerPage(columnCount: number): number {
  const columns = Math.max(1, columnCount);
  const rowsWithinCellBudget = Math.max(
    1,
    Math.floor((MARKDOWN_PARSE_BUDGETS.maxTableCellsPerPage - columns) / columns),
  );
  return Math.min(MARKDOWN_PARSE_BUDGETS.maxTableRowsPerPage, rowsWithinCellBudget);
}
