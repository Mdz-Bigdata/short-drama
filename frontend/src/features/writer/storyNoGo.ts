// 创作禁区的条数与字数上限，与 backend/app/data/prompt/story_direction.json 的 limits 一致。
export const NO_GO_ITEMS = 8;
export const NO_GO_CHARS = 60;

/** One line per thing the story must not do; blank lines and repeats are dropped (the server does the same). */
export function noGoLines(text: string): string[] {
  const lines = text.split('\n').map(line => line.replace(/^\s*(?:[-*•·]|\d+[.、)）])\s*/, '').trim().slice(0, NO_GO_CHARS));
  return [...new Set(lines.filter(Boolean))].slice(0, NO_GO_ITEMS);
}
