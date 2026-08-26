export interface ParsedMarkdownTable {
  caption?: string;
  headers: string[];
  rows: string[][];
}

const isDivider = (value: string) => /^:?-{3,}:?$/.test(value.trim());

function splitTableRow(value: string) {
  const cells = value.split('|').map(cell => cell.trim());
  while (cells[0] === '') cells.shift();
  while (cells.at(-1) === '') cells.pop();
  return cells;
}

export function parseMarkdownTable(value: string): ParsedMarkdownTable | null {
  const lines = value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length >= 3) {
    const separatorIndex = lines.findIndex(line => {
      const cells = splitTableRow(line);
      return cells.length >= 2 && cells.every(isDivider);
    });
    if (separatorIndex > 0) {
      const headers = splitTableRow(lines[separatorIndex - 1]);
      const rows = lines.slice(separatorIndex + 1).map(splitTableRow).filter(row => row.length === headers.length);
      if (headers.length >= 2 && rows.length > 0) {
        return {
          caption: lines.slice(0, separatorIndex - 1).join(' ').replace(/[：:]$/, '') || undefined,
          headers,
          rows,
        };
      }
    }
  }

  const firstPipe = value.indexOf('|');
  if (firstPipe < 0) return null;
  const tokens = value.slice(firstPipe).split('|').map(token => token.trim());
  const separatorStart = tokens.findIndex(isDivider);
  if (separatorStart < 0) return null;
  let separatorEnd = separatorStart;
  while (separatorEnd < tokens.length && isDivider(tokens[separatorEnd])) separatorEnd += 1;
  const headers = tokens.slice(0, separatorStart).filter(Boolean);
  const columnCount = separatorEnd - separatorStart;
  if (headers.length < 2 || headers.length !== columnCount) return null;

  const data = tokens.slice(separatorEnd).filter(Boolean);
  if (data.length < columnCount || data.length % columnCount !== 0) return null;
  const rows = Array.from({ length: data.length / columnCount }, (_, index) => (
    data.slice(index * columnCount, (index + 1) * columnCount)
  ));
  return {
    caption: value.slice(0, firstPipe).trim().replace(/[：:]$/, '') || undefined,
    headers,
    rows,
  };
}
