// 视频提示词里的资产引用 @[名字]，与后端 app/core/asset_mentions.py 同一套写法。

const MENTION = /@\[([^[\]\n]{1,40})\]/g;

export const MENTION_KIND_LABELS: Record<string, string> = {
  actor: '数字演员',
  scene: '拍摄场地',
  prop: '拍摄道具',
  costume: '服装',
  effect: '特效',
  product: '商品',
};

export function mentionKindClass(kind: string | undefined): string {
  return kind && kind in MENTION_KIND_LABELS ? `is-${kind}` : 'is-unknown';
}

export function parseMentions(text: string): string[] {
  const names: string[] = [];
  for (const match of text.matchAll(MENTION)) {
    const name = match[1].trim();
    if (!names.includes(name)) names.push(name);
  }
  return names;
}

export interface PromptPart {
  text: string;
  mention?: string;
}

/** 把提示词切成普通文字与 @[名字] 两种片段，供高亮层逐段渲染(字符一个不多一个不少)。 */
export function splitMentions(text: string): PromptPart[] {
  const parts: PromptPart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(MENTION)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push({ text: text.slice(cursor, start) });
    parts.push({ text: match[0], mention: match[1].trim() });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
}

/** 发给模型前的样子：@[名字] 换成「名字（参考图N）」，没有参考图的只留名字。 */
export function resolveMentions(text: string, numbers: Record<string, number>): string {
  return text.replace(MENTION, (_match, raw: string) => {
    const name = raw.trim();
    const number = numbers[name];
    return number ? `${name}（参考图${number}）` : name;
  });
}
