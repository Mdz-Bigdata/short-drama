/**
 * 输入框里的「@」补全：找出光标前正在打的 @名字，选中后写成 @[名字]。
 *
 * 纯函数，不碰 DOM；写法与 promptMentions.ts 的 @[名字] 一致(1–40 字，不含方括号和换行)。
 */

/** 一个可以 @ 的项目资产(人物、场景、道具……)。 */
export interface MentionCandidate {
  name: string;
  /** actor / scene / prop / costume / effect / product / extra / vehicle / set_dressing */
  kind: string;
  elementId?: string;
  aliases?: string[];
  description?: string;
  /** 后端给的缩略图地址(相对路径或完整 URL)，显示前过 apiUrl。 */
  thumbUrl?: string;
}

/** 光标处正在打的 @ 引用：[start, end) 是要被替换掉的那段，query 是光标前已经打出的字。 */
export interface MentionQuery {
  start: number;
  end: number;
  query: string;
}

export const MENTION_NAME_MAX = 40;

/** 裸 @ 后面能算进名字的字：不含空白、方括号、@ 和常见标点(打到标点就当这句话已经往下写了)。 */
const PLAIN_CHAR = /[^\s[\]@,.!?;:，。！？、；：（）()「」『』“”"'‘’<>《》]/;
/** 半截 @[ 里能出现的字：promptMentions 的规则，不含方括号和换行。 */
const BRACKET_CHAR = /[^[\]\n]/;
/** @ 前面紧挨着英文字母、数字或下划线就是邮箱一类，不弹菜单。 */
const WORD_CHAR = /[A-Za-z0-9_]/;
/** 插入后紧跟着这些字就不再补空格。 */
const FOLLOWING_STOP = /^[\s,.!?;:，。！？、；：）)」』”’"'》>]/;

function allMatch(text: string, pattern: RegExp): boolean {
  for (const char of text) if (!pattern.test(char)) return false;
  return true;
}

/** 光标前若是 @ + 至多 40 个名字字符，或者打了一半的 @[……，返回要替换的范围；否则 null。 */
export function activeMentionQuery(text: string, caret: number): MentionQuery | null {
  const position = Math.max(0, Math.min(caret, text.length));
  const before = text.slice(0, position);
  const start = before.lastIndexOf('@');
  if (start < 0) return null;
  if (start > 0 && WORD_CHAR.test(text[start - 1])) return null;
  const typed = before.slice(start + 1);

  if (typed.startsWith('[')) {
    const inner = typed.slice(1);
    if (inner.length > MENTION_NAME_MAX || !allMatch(inner, BRACKET_CHAR)) return null;
    // 光标后面还有「……]」把它合上，就是在一个写好的 @[名字] 里面，不弹。
    const after = text.slice(position);
    const close = after.search(/[[\]\n]/);
    if (close >= 0 && after[close] === ']' && inner.length + close >= 1 && inner.length + close <= MENTION_NAME_MAX) return null;
    return { start, end: position, query: inner };
  }

  if (typed.length > MENTION_NAME_MAX || !allMatch(typed, PLAIN_CHAR)) return null;
  // 光标夹在 @ 和 [ 之间：那是一个已经写好(或正在写)的 @[……]，不弹。
  if (!typed && text[position] === '[') return null;
  // 光标停在名字中间时，把光标后面同一个词也算进要替换的范围。
  let end = position;
  while (end < text.length && end - start - 1 < MENTION_NAME_MAX && PLAIN_CHAR.test(text[end])) end += 1;
  return { start, end, query: typed };
}

/** 把 range 换成 @[name]，后面没有空白或标点就补一个空格；返回新文本和光标位置。 */
export function insertMention(text: string, range: Pick<MentionQuery, 'start' | 'end'>, name: string): { text: string; caret: number } {
  const clean = name.replace(/[[\]\n\r]/g, '').trim().slice(0, MENTION_NAME_MAX);
  const token = `@[${clean}]`;
  const head = text.slice(0, range.start);
  const tail = text.slice(range.end);
  const spacer = FOLLOWING_STOP.test(tail) ? '' : ' ';
  return { text: `${head}${token}${spacer}${tail}`, caret: head.length + token.length + spacer.length };
}

const KIND_ORDER: Record<string, number> = { actor: 0, scene: 1, prop: 2 };
const kindRank = (kind: string) => KIND_ORDER[kind] ?? 3;

/**
 * 按打出的字排候选：名字前缀命中 > 名字包含 > 别名命中；同一档按 人物、场景、道具、其他；
 * 再同就保持原来的顺序。同名只留第一个。
 */
export function rankMentionCandidates(items: MentionCandidate[], query: string, limit = 8): MentionCandidate[] {
  const needle = query.trim().toLowerCase();
  const seen = new Set<string>();
  const scored: Array<{ item: MentionCandidate; tier: number; index: number }> = [];
  items.forEach((item, index) => {
    if (!item.name || seen.has(item.name)) return;
    const name = item.name.toLowerCase();
    let tier: number;
    if (!needle || name.startsWith(needle)) tier = 0;
    else if (name.includes(needle)) tier = 1;
    else if ((item.aliases ?? []).some(alias => alias.toLowerCase().includes(needle))) tier = 2;
    else return;
    seen.add(item.name);
    scored.push({ item, tier, index });
  });
  scored.sort((a, b) => a.tier - b.tier || kindRank(a.item.kind) - kindRank(b.item.kind) || a.index - b.index);
  return scored.slice(0, Math.max(0, limit)).map(entry => entry.item);
}
