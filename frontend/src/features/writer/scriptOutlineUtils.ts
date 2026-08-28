import type { WriterScene } from './types';

export interface SceneDialogueLine {
  kind: '台词' | '旁白';
  speaker?: string;
  text: string;
}

export interface ScriptEpisodeText {
  number: number;
  title: string;
  text: string;
}

const DIALOGUE_MARKER = /([一-龥A-Za-z·]{1,14})(?:（[^（）]{0,30}）)?\s*[：:]/g;
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

/**
 * Pull spoken lines back out of a flattened scene body. A marker only counts
 * as dialogue when its speaker is a known scene character (or 旁白); every
 * other `标签：` marker still terminates the previous spoken line.
 */
export function extractSceneDialogues(scene: WriterScene): SceneDialogueLine[] {
  const content = String(scene.content || '').replace(/\*\*/g, '').replace(/`/g, '');
  if (!content.trim()) return [];
  const speakers = new Set(
    (scene.characters || []).map(name => String(name).trim()).filter(Boolean),
  );
  const markers = [...content.matchAll(DIALOGUE_MARKER)].map(match => ({
    name: match[1],
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
  }));
  const lines: SceneDialogueLine[] = [];
  markers.forEach((marker, index) => {
    const isNarration = marker.name === '旁白';
    if (!isNarration && !speakers.has(marker.name)) return;
    const nextStart = index + 1 < markers.length ? markers[index + 1].start : content.length;
    let text = content.slice(marker.end, nextStart).trim();
    const boundary = text.search(/[【\n]/);
    if (boundary >= 0) text = text.slice(0, boundary).trim();
    if (!text) return;
    lines.push(
      isNarration
        ? { kind: '旁白', text }
        : { kind: '台词', speaker: marker.name, text },
    );
  });
  return lines.slice(0, 24);
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
