/** Points inside an excerpt where a sentence ends, as offsets relative to the excerpt. */
export function sentenceBoundaries(text: string): number[] {
  const points: number[] = [];
  const pattern = /[。！？!?]+[”’」』]?|\n+/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    const point = match.index + match[0].length;
    if (point > 0 && point < text.length && text.slice(0, point).trim() && text.slice(point).trim()) points.push(point);
  }
  return points;
}

export function around(text: string, point: number, width = 14): { before: string; after: string } {
  return {
    before: text.slice(Math.max(0, point - width), point).replace(/\s+/g, ' '),
    after: text.slice(point, point + width).replace(/\s+/g, ' '),
  };
}

