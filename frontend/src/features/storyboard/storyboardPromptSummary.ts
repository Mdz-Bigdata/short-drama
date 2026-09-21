import type { StoryboardPromptDetail } from './storyboardPromptTypes';


const GENERIC_GOAL = /^第\d+个(?:因果\/情绪)?信息单元$/;

export function conciseNarrativeGoal(detail: StoryboardPromptDetail) {
  const original = detail.foundation.narrative_goal?.trim() || '';
  const parts = original.split(/[；;]/).map(item => item.trim()).filter(Boolean);
  if (!parts.length || !parts.every(item => GENERIC_GOAL.test(item))) return original || '未注明';

  const events = Array.from(new Set(detail.beats.map(beat => beat.core_event.trim()).filter(Boolean)));
  if (events.length <= 3) return events.join(' → ') || '未注明';
  return [events[0], events[Math.floor(events.length / 2)], events[events.length - 1]].join(' → ');
}

const EPISODE_MARKER = /第\s*(\d{1,3}|[一二三四五六七八九十]{1,4})\s*集/g;
const SCENE_MARKER = /(?:场景|SCENE)\s*(\d{1,4})\s*[:：]/gi;
const SHOT_MARKER = /\bE(\d{1,3})S(\d{1,4})\b/gi;

function episodeNumber(label: string): number {
  if (/^\d+$/.test(label)) return Number(label);
  const digit = (value: string) => '一二三四五六七八九'.indexOf(value) + 1;
  if (!label.includes('十')) return digit(label);
  const [tens, ones] = label.split('十');
  return (tens ? digit(tens) : 1) * 10 + (ones ? digit(ones) : 0);
}

function matchingSection(text: string, markers: RegExpMatchArray[], position: number): string {
  return text.slice(markers[position].index, markers[position + 1]?.index ?? text.length).trim();
}

/** Add reading breaks without discarding or rewriting any source characters. */
function readingParagraphs(text: string): string[] {
  if (!text) return [];
  const boundaries = new Set([0, text.length]);
  for (const marker of text.matchAll(/第\s*(?:\d{1,3}|[一二三四五六七八九十]{1,4})\s*集|(?:场景|SCENE)\s*\d{1,4}\s*[:：]|\n+/gi)) {
    boundaries.add(marker.index);
  }
  const starts = [...boundaries].sort((left, right) => left - right);
  const paragraphs: string[] = [];
  for (let index = 0; index < starts.length - 1; index += 1) {
    let remaining = text.slice(starts[index], starts[index + 1]);
    while (remaining.length > 240) {
      const window = remaining.slice(0, 240);
      const punctuation = Math.max(...['。', '！', '？', '；', '\n'].map(mark => window.lastIndexOf(mark)));
      let end = punctuation >= 80 ? punctuation + 1 : 240;
      // Paragraph boundaries must not split an emoji or other supplementary character.
      const before = remaining.charCodeAt(end - 1);
      const after = remaining.charCodeAt(end);
      if (before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff) end += 1;
      paragraphs.push(remaining.slice(0, end));
      remaining = remaining.slice(end);
    }
    if (remaining) paragraphs.push(remaining);
  }
  return paragraphs;
}

export function scriptReadingView(detail: StoryboardPromptDetail) {
  const source = detail.foundation.script_text || '';
  const shot = /^E(\d{1,3})S(\d{1,4})$/i.exec(detail.shot_number || '');
  const episode = shot ? Number(shot[1]) : episodeNumber(detail.episode?.match(EPISODE_MARKER)?.[0]?.replace(/[第集\s]/g, '') || '1');
  const scene = shot ? Number(shot[2]) : detail.scene_number;
  const episodes = [...source.matchAll(EPISODE_MARKER)];
  const explicitShots = [...source.matchAll(SHOT_MARKER)];
  const shotPosition = explicitShots.findIndex(marker => Number(marker[1]) === episode && Number(marker[2]) === scene);
  let excerpt = source.trim();
  let scope: 'scene' | 'episode' | 'source' = 'scene';

  if (shotPosition >= 0) {
    excerpt = matchingSection(source, explicitShots, shotPosition);
  } else {
    const episodePosition = episodes.findIndex(marker => episodeNumber(marker[1]) === episode);
    if (episodes.length && episodePosition < 0) {
      scope = 'source';
    } else {
      if (episodePosition >= 0) {
        excerpt = matchingSection(source, episodes, episodePosition);
        scope = 'episode';
      }
      const scenes = [...excerpt.matchAll(SCENE_MARKER)];
      // An outline can split one screenplay scene into several E...S... shots.
      // Without an explicit shot ID, only the first shot has an unambiguous
      // opening-scene mapping; never assume E1S02 means screenplay 场景2.
      const scenePosition = !episodes.length && !explicitShots.length && scenes.length === 1
        ? 0
        : scene === 1 ? scenes.findIndex(marker => Number(marker[1]) === 1) : -1;
      if (scenePosition >= 0) {
        excerpt = matchingSection(excerpt, scenes, scenePosition);
        scope = 'scene';
      } else if (scenes.length || explicitShots.length || (!episodes.length && source.length > 1200)) {
        scope = episodePosition >= 0 ? 'episode' : 'source';
      }
    }
  }

  const excerptParagraphs = readingParagraphs(excerpt);
  return {
    source,
    excerpt,
    excerptParagraphs,
    sourceParagraphs: readingParagraphs(source),
    scope,
    heading: `第${episode}集 · ${detail.shot_number || `场景 ${scene}`}`,
    label: scope === 'scene' ? '当前场景原文' : scope === 'episode' ? '本集原文参考 · 未定位到独立镜头段落' : '剧本原文预览 · 未定位到当前场景',
    // Even a modest paragraph can exceed eight lines on a narrow mobile panel.
    expandable: source.trim() !== excerpt || excerpt.length > 80 || excerptParagraphs.length > 3,
  };
}
