/** Shared helpers that turn raw screenplay fragments into short display labels. */

const HEADING_NOISE = /(?:^|\s)(?:#{1,6}|[*]{1,3}|[-–—]{3,}|[>`~]+)(?=\s|$)/g;

/** Strip markdown control characters while keeping the prose intact. */
export function stripMarkdown(value: unknown): string {
  return String(value ?? '')
    .split('\u0000').join('')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/~~([^~\n]+)~~/g, '$1')
    .replace(HEADING_NOISE, ' ')
    .replace(/[*#>]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function clip(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}…` : text;
}

/**
 * Extract one short key-event label from a raw scene body.
 *
 * Preference order: the scene heading (场景N：地点), then the first hook or
 * action clause, then the first sentence of the body.
 */
export function summarizeSceneEvent(value: unknown, limit = 22): string {
  const text = stripMarkdown(value);
  if (!text) return '';

  const sceneHeading = text.match(/【?\s*(场景\s*[0-9零一二三四五六七八九十]*\s*[：:][^/【】\n]{1,40})/);
  if (sceneHeading) {
    return clip(sceneHeading[1].replace(/\s+/g, ''), limit);
  }

  const labeled = text.match(
    /(?:钩子|视觉|开场钩子|高光爆点|动作|冲突升级)\s*[/：:][^：:]{0,12}[：:]?\s*([^。！？；]{4,60})/,
  );
  if (labeled) return clip(labeled[1].trim(), limit);

  const firstSentence = text
    .replace(/^[一二三四五六七八九十]+、\s*/, '')
    .split(/[。！？；]/)
    .map(part => part.trim())
    .find(part => part.length >= 4);
  return clip(firstSentence || text, limit);
}

/** A slightly longer supporting description for timeline cards. */
export function summarizeSceneDetail(value: unknown, limit = 72): string {
  const text = stripMarkdown(value)
    .replace(/【[^】]*】/g, ' ')
    .replace(/(?:前3秒钩子|开场钩子|尾5秒钩子|高光爆点|冲突升级|动作|对白|视觉)\s*[/：:]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return clip(text, limit);
}

/** Compact title for an episode card. */
export function summarizeEpisodeTitle(value: unknown, limit = 24): string {
  const text = stripMarkdown(value).replace(/^第\s*\d+\s*集\s*/, '');
  const heading = text.match(/【?\s*(场景\s*[0-9]*\s*[：:][^/【】\n]{1,30})/);
  if (heading) return clip(heading[1].replace(/\s+/g, ''), limit);
  const firstSentence = text.split(/[。！？；]/).map(part => part.trim()).find(Boolean);
  return clip(firstSentence || text, limit);
}
