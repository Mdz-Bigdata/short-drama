interface ScriptTitleConfig {
  titleSuggestion?: string | null;
  scriptName?: string | null;
}

// A project is created from a chat prompt, so titleSuggestion is frequently the
// request itself ("请帮我生成一个古装权谋短剧"). That is never the drama's name.
const INSTRUCTION_TITLE = /(?:^|[\s，。、])(?:请|帮我|帮忙|给我|替我|麻烦|我想|我要|需要|来一个|来一部)|(?:生成|创作|编写|写|做|来)(?:一)?(?:个|部|篇|集|下)/;

export function isInstructionLike(value: unknown): boolean {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return false;
  return INSTRUCTION_TITLE.test(text) || text.length > 32;
}

function baseFileName(value: string): string {
  const normalized = value.trim().replace(/\\/g, '/');
  const fileName = normalized.slice(normalized.lastIndexOf('/') + 1).trim();
  const extensionIndex = fileName.lastIndexOf('.');
  if (extensionIndex === 0) return '';
  return (extensionIndex > 0 ? fileName.slice(0, extensionIndex) : fileName).trim();
}

function cleanTitle(value: string): string {
  return value
    .replace(/^\s*[《“"']+|[》”"']+\s*$/g, '')
    .replace(/[*_`#]/g, '')
    .trim();
}

export function normalizeScriptTitle(value: unknown): string {
  if (typeof value !== 'string') return '';
  const title = cleanTitle(value);
  if (!title || title === '未命名剧本' || title === '未命名短剧' || title.length > 32) return '';
  return isInstructionLike(title) ? '' : title;
}

function screenplayTitle(value: unknown): string {
  if (typeof value !== 'string') return '';
  const lines = value.slice(0, 256_000).split('\u0000').join('').split(/\r?\n/, 800);

  for (const line of lines) {
    const explicit = line.match(/^\s*(?:#{1,6}\s*)?(?:\*{1,3}\s*)?(?:剧名|片名|剧本名|剧本名称|作品名|项目名称)\s*[：:]\s*(.+?)\s*$/);
    if (explicit) {
      const title = normalizeScriptTitle(explicit[1]);
      if (title) return title;
    }
  }

  // Screenplays open with 《流氓天子》分集剧本; that is the series name.
  // 《…结构》 style references point at guideline documents, not the drama.
  for (const line of lines.slice(0, 40)) {
    for (const match of line.matchAll(/《([^》]{1,32})》/g)) {
      const title = normalizeScriptTitle(match[1]);
      if (title && !title.includes('结构')) return title;
    }
  }

  // Last resort only: an episode subtitle names one episode, not the series.
  for (const line of lines) {
    const episode = line.match(/^\s*(?:#{1,6}\s*)?(?:\*{1,3}\s*)?(?:【\s*)?第\s*(?:\d{1,3}|[一二三四五六七八九十]{1,4})\s*集(?:\s*】)?\s*[：:\-—]?\s*(.+?)\s*$/);
    if (episode) {
      const title = normalizeScriptTitle(episode[1].replace(/[*＊]+\s*$/, ''));
      if (title) return title;
    }
  }

  return '';
}

export function getScriptDisplayName(
  config?: ScriptTitleConfig | null,
  script?: unknown,
  analysedTitle?: unknown,
): string {
  const scriptName = config?.scriptName ? normalizeScriptTitle(baseFileName(config.scriptName)) : '';
  if (scriptName) return scriptName;

  // The backend's structured analysis names the drama; trust it over any guess.
  const analysed = normalizeScriptTitle(analysedTitle);
  if (analysed) return analysed;

  const generatedTitle = screenplayTitle(script);
  if (generatedTitle) return generatedTitle;

  const suggestedTitle = normalizeScriptTitle(config?.titleSuggestion);
  return suggestedTitle || '未命名剧本';
}
