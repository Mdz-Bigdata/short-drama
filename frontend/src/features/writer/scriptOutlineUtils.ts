import type { WriterScene } from './types';

export interface SceneDialogueLine {
  kind: '台词' | '旁白' | '内心独白';
  speaker?: string;
  /**
   * 角色名与冒号之间的动作/舞台提示（如「针尖一停」「垂眼继续刺绣」），
   * 与台词正文分开保存，绝不拼进 text。
   */
  cue?: string;
  text: string;
}

export interface ScriptEpisodeText {
  number: number;
  title: string;
  text: string;
}

// “集”后必须是行尾或显式分隔符，避免把“第1集结尾埋钩子”这类正文句子当作分集标题。
const EPISODE_HEADING = /^\s*(?:#{1,6}\s*)?(?:【\s*)?第\s*([0-9]{1,3}|[一二三四五六七八九十]{1,3})\s*集(?:\s*】)?(?:\s*$|[\s:：\-—]+(.*)$)/;
const CHINESE_DIGITS: Record<string, number> = {
  一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9,
};

function episodeNumber(value: string): number {
  if (/^\d+$/.test(value)) return Math.min(200, Math.max(1, Number(value)));
  if (value === '十') return 10;
  const tensIndex = value.indexOf('十');
  if (tensIndex >= 0) {
    const tens = tensIndex === 0 ? 1 : CHINESE_DIGITS[value[0]] || 1;
    const ones = value.endsWith('十') ? 0 : CHINESE_DIGITS[value[value.length - 1]] || 0;
    return Math.min(200, tens * 10 + ones);
  }
  return CHINESE_DIGITS[value] || 1;
}

/** 说话人段向前回溯时的句边界字符（逗号/顿号除外：动作提示允许「放下针，抬眼」）。 */
const SEGMENT_BOUNDARY = new Set([...'。！？!?；;…\n\r\t【】「」『』“”"‘’：:（）()']);

/** 结构标签词根黑名单：说话人段命中即视为段落标签，只终止上一句、不产出行。 */
const LABEL_MORPHEMES = [
  '对白', '台词', '动作', '冲突', '高光', '爆点', '钩子', '视觉', '场景', '内景', '外景',
  '画面', '时间', '地点',
  '人物', '角色', '音效', '音乐', '配乐', '镜头', '特写', '时长', '节奏', '情节轨', '情绪轨',
  '双轨', '本集', '景别', '转场', '格式', '要求', '备注', '告示', '闪回', '剧本', '标题',
  '大纲', '梗概', '主题', '风格', '基调', '预估', '道具', '灯光', '服装', '妆造', '造型',
  '机位', 'BGM', 'bgm',
];

/** 无角色归属的叙述声标签 → 旁白。 */
const NARRATION_LABELS = new Set(['旁白', '画外音', '旁白画外音', '画外', '解说', 'VO', 'V.O.', 'V.O', 'NARRATION']);

/** 无角色名的心声标签 → 内心独白。 */
const MONOLOGUE_LABELS = new Set(['内心独白', '内心', '心声', '独白']);

/** 括注/动作尾巴中命中即判独白（自语/喃喃/嘟囔是说出口的，故意不收）。 */
const MONOLOGUE_HINT = /内心|心想|心道|心声|心中|心里|默念|暗想|暗道|腹诽|自忖|脑海|独白|(?:^|[^A-Za-z])O\.?S\.?(?![A-Za-z])/;

/** 动作尾巴若以纯言说动词结尾（「谢云谣吩咐：」），把动词从提示里剥掉。 */
const TRAILING_SPEECH_VERB = /(?:说道|问道|答道|喝道|叹道|骂道|喊道|吼道|低声道|沉声道|轻声道|冷冷道|缓缓道|吩咐道|吩咐|命令|嘱咐|追问|反问|回答|开口|说|道|问|答|喊|叫|骂|斥|劝)$/;

/** 二级截断：台词内某个句末标点后紧跟镜头指示词 → 后面是摄影叙述，不属于台词。 */
const CAMERA_TAIL = /^(?:镜头|画面|特写|切至|切换|字幕)/;

const SPEAKER_SEGMENT_CHARSET = /^[一-龥A-Za-z0-9？?·. 　]+$/;

/** 未登记说话人段里出现叙事虚词（摆着/摆了/…的东西）→ 是叙述句主语，不是人名。 */
const NARRATIVE_PARTICLE = /[着了的]/;

/** 时间短语（今晚三更/五更时分…）：台词里冒号前的时间状语，并回正文而非虚构说话人。 */
const TIME_PHRASE = /[今明昨当次每][日晚夜晨早]|[一二三四五六七八九十两\d]更|时分|[子丑寅卯辰巳午未申酉戌亥]时|凌晨|清晨|傍晚|黄昏|正午|深夜|半夜|翌日/;

/** 「小翠OS：」——名字后紧跟 OS/O.S. 记号 → 内心独白，说话人取掉记号。 */
const VOICE_OS_SUFFIX = /^(.+[^A-Za-z.\s])\s*O\.?S\.?$/;

/** 「小翠心想：」——段尾言心动词剥掉后余下说话人。 */
const MONOLOGUE_TAIL_VERB = /^(.{1,6}?)(?:心想|心道|默念|暗想|暗道|腹诽|自忖)$/;
// —— 无冒号转述句受限通道（「灰衣人答丞相」「沈砚问来取什么，黑衣人答星图」）——
// 用户对「对话列」的硬要求是零遗漏；转述句承载真实剧情对话，整场丢弃即违背诉求。
// 但间接引语不能伪装成逐字台词：提取结果一律标 cue=「转述」，UI 以（转述）呈现。
// 守卫（缺一不可）：仅限不含任何冒号的句子；句首必须是在册角色名（不放开到形似人名）；
// 名后 0–4 字内出现言说动词；单字动词从严——取词 ≥2 字且首字不得是虚词/构词字。
const REPORTED_DOUBLE_VERBS = [
  '问道', '答道', '回答', '追问', '反问', '说道', '喊道', '低喃', '议论',
  '嘀咕', '吩咐', '命令', '嘱咐', '求饶', '告知', '禀报', '回禀',
];
const REPORTED_SINGLE_VERBS = ['问', '答', '说', '喊', '骂'];
/** 单字动词后首字命中即拒绝：防「说了算」「答应了他」这类构词误报。 */
const REPORTED_SINGLE_BLOCK = new Set([...'了着过的得是应话服明白道题人']);
const REPORTED_MAX_VERB_GAP = 4;

const MAX_UNKNOWN_SPEAKER_LENGTH = 8;
const MAX_ACTION_CUE_LENGTH = 20;
const MAX_SUFFIX_SEGMENT_LENGTH = 6;
const MAX_PAREN_LENGTH = 40;
// 单场景对话行上限。原实现封顶 24：长场景后半台词整段消失，本身就是一种遗漏，
// 放宽到 200 仅作为防御性安全阀（正常场景远达不到）。
const MAX_LINES = 200;

interface PendingLine {
  kind: SceneDialogueLine['kind'];
  speaker?: string;
  cue?: string;
}

interface Marker {
  /** 说话人段起点：上一行台词正文在此截止。 */
  segStart: number;
  /** 冒号之后的位置：本行台词正文从此开始。 */
  colonEnd: number;
  /** null 表示结构标签：只作为上一句的终止符，不产出行。 */
  line: PendingLine | null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function stripTrailingParens(content: string, endExclusive: number): { start: number; paren: string } {
  let p = endExclusive;
  const parens: string[] = [];
  for (;;) {
    while (p > 0 && /\s/.test(content[p - 1])) p -= 1;
    const close = content[p - 1];
    if (close !== '）' && close !== ')') break;
    const open = close === '）' ? '（' : '(';
    const openIdx = content.lastIndexOf(open, p - 2);
    if (openIdx < 0 || p - 2 - openIdx > MAX_PAREN_LENGTH) break;
    const inner = content.slice(openIdx + 1, p - 1);
    if (inner.includes(close)) break;
    parens.unshift(inner);
    p = openIdx;
  }
  return { start: p, paren: parens.join('，') };
}

/**
 * 'label'  → 结构标签：只终止上一句正文，不产出行。
 * 'absorb' → 台词内部的冒号（时间状语等）：既不当新标记也不截断，正文照常延续。
 */
type SegmentClassification = PendingLine | 'label' | 'absorb';

function classifySegment(
  segment: string,
  paren: string,
  rosterByLength: string[],
): SegmentClassification {
  const upper = segment.toUpperCase();
  if (segment === '字幕') return { kind: '旁白', cue: '字幕' };
  if (NARRATION_LABELS.has(segment) || NARRATION_LABELS.has(upper)) return { kind: '旁白' };
  if (MONOLOGUE_LABELS.has(segment)) return { kind: '内心独白' };
  if (LABEL_MORPHEMES.some(morpheme => segment.includes(morpheme))) return 'label';

  // 「小翠OS」：剥掉 OS 记号后按剩余名字继续分类，类型强制内心独白。
  let core = segment;
  let forcedMonologue = false;
  const osSuffix = segment.match(VOICE_OS_SUFFIX);
  if (osSuffix) {
    core = osSuffix[1].trim();
    forcedMonologue = true;
  }

  const speakerLine = (speaker: string, actionTail: string): PendingLine => {
    const kind: SceneDialogueLine['kind'] =
      forcedMonologue || MONOLOGUE_HINT.test(paren) || MONOLOGUE_HINT.test(actionTail)
        ? '内心独白'
        : '台词';
    const cue = actionTail
      .replace(TRAILING_SPEECH_VERB, '')
      .replace(/^[\s，,、]+|[\s，,、]+$/g, '');
    return cue ? { kind, speaker, cue } : { kind, speaker };
  };

  // 已知角色名段首最长前缀匹配：「谢云谣针尖一停」→ 谢云谣 + 动作提示。
  for (const name of rosterByLength) {
    if (!core.startsWith(name)) continue;
    const rest = core.slice(name.length).trim();
    // 超长动作尾巴仅当以言说动词收尾（「…看着他说道」）才可信；否则按叙述句终止上一句。
    if (rest.length > MAX_ACTION_CUE_LENGTH && !TRAILING_SPEECH_VERB.test(rest)) return 'label';
    return speakerLine(name, rest);
  }
  // 称谓前缀 + 角色名结尾：「老吏王恕」→ 王恕。
  if (core.length <= MAX_SUFFIX_SEGMENT_LENGTH) {
    for (const name of rosterByLength) {
      if (core.length > name.length && core.endsWith(name)) {
        return speakerLine(name, core.slice(0, core.length - name.length));
      }
    }
  }
  // 整段就是心声短语（「脑海中响起」「心中默念」）→ 无主内心独白；
  // 若剥掉言心动词后剩一个不含心声词的短名（「小翠心想」），说话人归它。
  if (core.length <= MAX_UNKNOWN_SPEAKER_LENGTH && MONOLOGUE_HINT.test(core)) {
    const named = core.match(MONOLOGUE_TAIL_VERB);
    if (named && !MONOLOGUE_HINT.test(named[1])) {
      return { kind: '内心独白', speaker: named[1] };
    }
    return { kind: '内心独白' };
  }
  // 未登记但形似人名的短标签（配角常缺席角色表）：为“零遗漏”也收进来。
  // 「老仆，躬身」：首个逗号前是名字候选，其余是动作提示。
  const commaIdx = core.search(/[，,、]/);
  const head = (commaIdx > 0 ? core.slice(0, commaIdx) : core).trim();
  const actionTail = commaIdx > 0 ? core.slice(commaIdx + 1).trim() : '';
  if (
    head.length > 0
    && head.length <= MAX_UNKNOWN_SPEAKER_LENGTH
    && actionTail.length <= MAX_ACTION_CUE_LENGTH
    && SPEAKER_SEGMENT_CHARSET.test(head)
    && !/^\d+$/.test(head)
    && !/^[·. 　]+$/.test(head)
  ) {
    // 「今晚三更：北门见」——时间状语后的冒号仍在台词里，并回正文。
    if (TIME_PHRASE.test(head)) return 'absorb';
    // 「桌上摆着三样东西：」——叙事虚词说明是叙述句主语，不虚构说话人。
    if (NARRATIVE_PARTICLE.test(head)) return 'label';
    const verbless = head.replace(TRAILING_SPEECH_VERB, '');
    const speaker = verbless.length >= 2 ? verbless : head;
    return speakerLine(speaker, actionTail);
  }
  return 'label';
}

/** 台词尾部粘连的叙述句（句末标点后紧跟角色名/镜头词开头的句子）在该标点处截断。 */
function truncateNarrativeTail(text: string, rosterByLength: string[]): string {
  for (let i = 0; i < text.length - 1; i += 1) {
    if (!'。！？!?；;…'.includes(text[i])) continue;
    let j = i + 1;
    while (j < text.length && '”」』’"'.includes(text[j])) j += 1;
    let k = j;
    while (k < text.length && /\s/.test(text[k])) k += 1;
    const tail = text.slice(k);
    if (!tail) return text;
    if (CAMERA_TAIL.test(tail)) return text.slice(0, j);
    for (const name of rosterByLength) {
      if (!tail.startsWith(name)) continue;
      const after = tail[name.length] || '';
      // 「怕。谢云谣，你听我说」里的呼语不算叙述句开头。
      if (after === '，' || after === ',' || after === '、') break;
      return text.slice(0, j);
    }
  }
  return text;
}

interface ReportedHit {
  speaker: string;
  text: string;
  /** 说话人名在句内的偏移，用于与冒号行按文档序合并。 */
  at: number;
}

/** 在一个不含冒号的句子里找「角色名 + 言说动词 + 内容」结构；一句可切出多段。 */
function findReportedSpeech(sentence: string, base: number, rosterByLength: string[]): ReportedHit[] {
  const matchAt = (pos: number): { speaker: string; contentStart: number } | null => {
    for (const name of rosterByLength) {
      if (!sentence.startsWith(name, pos)) continue;
      const rest = sentence.slice(pos + name.length);
      for (let gap = 0; gap <= REPORTED_MAX_VERB_GAP; gap += 1) {
        const gapStr = rest.slice(0, gap);
        if (!/^[^，,、。！？!?\s：:]*$/.test(gapStr)) break;
        for (const verb of REPORTED_DOUBLE_VERBS) {
          if (rest.startsWith(verb, gap)) {
            return { speaker: name, contentStart: pos + name.length + gap + verb.length };
          }
        }
        for (const verb of REPORTED_SINGLE_VERBS) {
          if (!rest.startsWith(verb, gap)) continue;
          const head = rest[gap + verb.length] || '';
          if (!head || REPORTED_SINGLE_BLOCK.has(head)) continue;
          return { speaker: name, contentStart: pos + name.length + gap + verb.length };
        }
      }
      return null; // 命中角色名但无言说动词（「沈砚指向桌上」）：整句放弃。
    }
    return null;
  };

  const first = matchAt(0);
  if (!first) return [];
  const hits: ReportedHit[] = [];
  let current = { speaker: first.speaker, at: 0, contentStart: first.contentStart };
  // 在内容里找下一个「分隔符 + 角色名 + 言说动词」结构，在其处切段（一句两段的转述）。
  for (let i = current.contentStart; i < sentence.length; i += 1) {
    if (!'，,、'.includes(sentence[i])) continue;
    const next = matchAt(i + 1);
    if (!next) continue;
    hits.push({ speaker: current.speaker, at: base + current.at,
      text: sentence.slice(current.contentStart, i) });
    current = { speaker: next.speaker, at: i + 1, contentStart: next.contentStart };
    i = next.contentStart - 1;
  }
  hits.push({ speaker: current.speaker, at: base + current.at,
    text: sentence.slice(current.contentStart) });
  return hits
    .map(hit => ({ ...hit, text: hit.text.replace(/^[\s，,、]+|[\s，,、]+$/g, '') }))
    .filter(hit => hit.text.length >= 2);
}

/**
 * Pull spoken lines back out of a flattened scene body.
 *
 * 对每个冒号：向前回溯到最近的句边界取「说话人段」，剥掉紧贴冒号的括注，
 * 再按 结构标签黑名单 → 已知角色名前缀/称谓后缀 → 形似人名的短标签 分类，
 * 支持 台词 / 旁白 / 内心独白 三类。角色名后的动作提示进 cue，不混入 text。
 * 无冒号的间接转述句（「灰衣人答丞相」）经受限通道提取并标 cue=「转述」——
 * 它承载真实对话信息，丢弃即遗漏；但以（转述）标识与逐字台词区分，不冒充直接引语。
 */
export function extractSceneDialogues(
  scene: WriterScene,
  knownSpeakers?: Iterable<string>,
): SceneDialogueLine[] {
  let content = String(scene.content || '').replace(/\*\*/g, '').replace(/`/g, '');
  if (!content.trim()) return [];
  const roster = new Set<string>();
  for (const name of scene.characters || []) {
    const trimmed = String(name).trim();
    if (trimmed) roster.add(trimmed);
  }
  if (knownSpeakers) {
    for (const name of knownSpeakers) {
      const trimmed = String(name).trim();
      if (trimmed) roster.add(trimmed);
    }
  }
  const rosterByLength = [...roster].sort((left, right) => right.length - left.length);

  // 「谢云谣。你终于来了。」——行首在册角色名 + 句号 + 正文的「角色。台词」写法，
  // 归一成冒号后走统一流程。仅限行首且句号后同行还有正文，避免把叙述句卷进来。
  if (rosterByLength.length) {
    const alternation = rosterByLength.map(escapeRegExp).join('|');
    content = content.replace(
      new RegExp(`(^|\\n)([ \\t\\u3000]*)(${alternation})。(?=.)`, 'g'),
      '$1$2$3：',
    );
  }

  const markers: Marker[] = [];
  const absorbedColons = new Set<number>();
  for (let i = 0; i < content.length; i += 1) {
    const ch = content[i];
    if (ch !== '：' && ch !== ':') continue;
    // 半角冒号夹在数字之间是时刻（12:30），不是对话标记。
    if (ch === ':' && /\d/.test(content[i - 1] || '') && /\d/.test(content[i + 1] || '')) continue;

    const { start: parenStart, paren } = stripTrailingParens(content, i);
    let s = parenStart;
    let boundaryIdx = -1;
    while (s > 0) {
      if (SEGMENT_BOUNDARY.has(content[s - 1])) {
        boundaryIdx = s - 1;
        break;
      }
      s -= 1;
    }

    // 台词内部的冒号（「记住三个字：别回头。」）：与上一个产出行之间没有任何句边界，
    // 说明它仍在同一句台词里——整体并入正文，既不当新标记也不截断。
    const boundaryChar = boundaryIdx >= 0 ? content[boundaryIdx] : '';
    const lastMarker = markers[markers.length - 1];
    const isContinuation =
      (boundaryChar === '：' || boundaryChar === ':')
      && (absorbedColons.has(boundaryIdx)
        || (!!lastMarker && lastMarker.line !== null && boundaryIdx === lastMarker.colonEnd - 1));
    const segment = content.slice(s, parenStart).trim();
    if (isContinuation || !segment) {
      // 同行仅空格分隔的交替对话（「谢云谣：好 萧策：不好」）：回溯段末一截
      // 以在册角色开头时视作新说话人，而不是并进上一句。
      if (isContinuation) {
        const raw = content.slice(s, parenStart);
        const wsIdx = Math.max(raw.lastIndexOf(' '), raw.lastIndexOf('　'), raw.lastIndexOf('\t'));
        const tail = wsIdx >= 0 ? raw.slice(wsIdx + 1).trim() : '';
        if (tail && rosterByLength.some(name => tail.startsWith(name))) {
          const tailLine = classifySegment(tail, paren, rosterByLength);
          if (tailLine !== 'label' && tailLine !== 'absorb') {
            markers.push({ segStart: s + wsIdx + 1, colonEnd: i + 1, line: tailLine });
            continue;
          }
        }
      }
      absorbedColons.add(i);
      continue;
    }

    const classified = classifySegment(segment, paren, rosterByLength);
    if (classified === 'absorb') {
      absorbedColons.add(i);
      continue;
    }
    markers.push({
      segStart: s,
      colonEnd: i + 1,
      line: classified === 'label' ? null : classified,
    });
  }

  const positioned: Array<{ at: number; line: SceneDialogueLine }> = [];
  markers.forEach((marker, index) => {
    if (!marker.line) return;
    const nextStart = index + 1 < markers.length ? markers[index + 1].segStart : content.length;
    let region = content.slice(marker.colonEnd, nextStart).trim();
    const hardBoundary = region.indexOf('【');
    if (hardBoundary >= 0) region = region.slice(0, hardBoundary).trim();
    // 换行不再一刀切：无说话人的续行并回同一句台词，
    // 但空行、以在册角色名或镜头词开头的行仍视作叙述/新块的开始。
    const regionLines = region.split(/\r?\n/);
    let text = regionLines[0].trim();
    for (let li = 1; li < regionLines.length; li += 1) {
      const continuation = regionLines[li].trim();
      if (!continuation) break;
      if (CAMERA_TAIL.test(continuation)) break;
      if (rosterByLength.some(name => continuation.startsWith(name))) break;
      text += continuation;
    }
    text = truncateNarrativeTail(text, rosterByLength).trim();
    if (!text) return;
    const { kind, speaker, cue } = marker.line;
    const line: SceneDialogueLine = { kind, text };
    if (speaker) line.speaker = speaker;
    if (cue) line.cue = cue;
    positioned.push({ at: marker.segStart, line });
  });

  // 转述通道：逐句扫描；含任何冒号的句子一律跳过（冒号通道已负责，绝不重复计）。
  const SENTENCE_BOUNDARY = /[。！？!?；;…\n【】]/;
  let sentenceStart = 0;
  for (let i = 0; i <= content.length; i += 1) {
    const atEnd = i === content.length;
    if (!atEnd && !SENTENCE_BOUNDARY.test(content[i])) continue;
    const rawSentence = content.slice(sentenceStart, i);
    const leading = rawSentence.length - rawSentence.replace(/^\s+/, '').length;
    const sentence = rawSentence.trim();
    if (sentence && !/[：:]/.test(sentence)) {
      for (const hit of findReportedSpeech(sentence, sentenceStart + leading, rosterByLength)) {
        positioned.push({
          at: hit.at,
          line: { kind: '台词', speaker: hit.speaker, cue: '转述', text: hit.text },
        });
      }
    }
    sentenceStart = i + 1;
  }

  positioned.sort((left, right) => left.at - right.at);
  return positioned.map(entry => entry.line).slice(0, MAX_LINES);
}

/** Split the raw screenplay into per-episode plain-text chunks. */
export function splitScriptEpisodes(script: string): ScriptEpisodeText[] {
  const source = String(script || '').split('\u0000').join('');
  if (!source.trim()) return [];
  const episodes: ScriptEpisodeText[] = [];
  let current: ScriptEpisodeText | null = null;
  for (const line of source.split(/\r?\n/)) {
    const match = line.match(EPISODE_HEADING);
    if (match) {
      if (current) {
        current.text = current.text.trim();
        episodes.push(current);
      }
      const number = episodeNumber(match[1]);
      current = {
        number,
        title: (match[2] || '').replace(/[*#]+/g, '').trim() || `第 ${number} 集`,
        text: `${line}\n`,
      };
      continue;
    }
    if (current) current.text += `${line}\n`;
  }
  if (current) {
    current.text = current.text.trim();
    episodes.push(current);
  }
  if (!episodes.length) {
    return [{ number: 1, title: '完整剧本', text: source.trim() }];
  }
  // A synopsis line can repeat an episode heading; keep the fullest chunk per episode.
  const byNumber = new Map<number, ScriptEpisodeText>();
  for (const episode of episodes) {
    const existing = byNumber.get(episode.number);
    if (!existing || episode.text.length > existing.text.length) {
      byNumber.set(episode.number, episode);
    }
  }
  return [...byNumber.values()].sort((left, right) => left.number - right.number);
}
