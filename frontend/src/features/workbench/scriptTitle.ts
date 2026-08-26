interface ScriptTitleConfig {
  titleSuggestion?: string | null;
  scriptName?: string | null;
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
  return title && title !== '未命名剧本' && title.length <= 32 ? title : '';
}

function screenplayTitle(value: unknown): string {
  if (typeof value !== 'string') return '';
  const lines = value.slice(0, 256_000).split('\u0000').join('').split(/\r?\n/, 800);

  for (const line of lines) {
    const explicit = line.match(/^\s*(?:#{1,6}\s*)?(?:剧名|片名|剧本名称|项目名称)\s*[：:]\s*(.+?)\s*$/);
    if (explicit) return normalizeScriptTitle(explicit[1]);
  }

  for (const line of lines) {
    const episode = line.match(/^\s*(?:#{1,6}\s*)?(?:【\s*)?第\s*(?:\d{1,3}|[一二三四五六七八九十]{1,3})\s*集(?:\s*】)?\s*[：:\-—]?\s*(.+?)\s*$/);
    if (episode) return normalizeScriptTitle(episode[1]);
  }

  return '';
}

export function getScriptDisplayName(config?: ScriptTitleConfig | null, script?: unknown): string {
  const scriptName = config?.scriptName ? normalizeScriptTitle(baseFileName(config.scriptName)) : '';
  if (scriptName) return scriptName;

  const generatedTitle = screenplayTitle(script);
  if (generatedTitle) return generatedTitle;

  const suggestedTitle = normalizeScriptTitle(config?.titleSuggestion);
  return suggestedTitle || '未命名剧本';
}
