export const FIVE_VIEW_KEYS = [
  'front',
  'front_three_quarter',
  'profile',
  'rear_three_quarter',
  'back',
] as const;

export type FiveViewKey = (typeof FIVE_VIEW_KEYS)[number];
export type CharacterAssetState = 'MISSING' | 'PARTIAL' | 'NEEDS_REVIEW' | 'FAILED' | 'READY';
export type CharacterDashboardState = 'WAITING' | 'INCOMPLETE' | 'READY';

export interface CharacterViewDefinition {
  key: FiveViewKey;
  order: number;
  angleDegrees: number;
  labelZh: string;
  labelEn: string;
}

export interface CharacterViewContract {
  version: string;
  order: FiveViewKey[];
  views: CharacterViewDefinition[];
}

export interface CharacterViewAsset {
  key: FiveViewKey;
  order: number;
  imageUrl: string | null;
  available: boolean;
}

export interface CharacterColor {
  name: string;
  hex: string | null;
}

export interface CharacterStateAnchor {
  view: FiveViewKey;
  detail: string;
}

export interface CharacterDesignState {
  stateId: string;
  title: string;
  dna: string;
  hair: string;
  body: string;
  clothing: string;
  accessories: string;
  style: string;
  anchors: CharacterStateAnchor[];
}

export interface CharacterQualityIssue {
  code: string;
  message: string;
  viewIndex: number | null;
}

export interface CharacterFiveViewQuality {
  passed: boolean | null;
  paletteSimilarity: number | null;
  uniqueViewHashes: number | null;
  entropy: number[];
  issues: CharacterQualityIssue[];
}

export interface CharacterDashboardCharacter {
  characterId: string;
  name: string;
  role: string;
  description: string;
  identity: string;
  voiceId: string;
  colors: CharacterColor[];
  states: CharacterDesignState[];
  sheetUrl: string | null;
  assetState: CharacterAssetState;
  views: CharacterViewAsset[];
  quality: CharacterFiveViewQuality;
}

export interface CharacterDashboardStats {
  characterCount: number;
  readyCount: number;
  needsReviewCount: number;
  partialCount: number;
  missingCount: number;
  failedCount: number;
  availableViewCount: number;
  expectedViewCount: number;
}

export interface CharacterDashboardProject {
  genre: string;
  platform: string;
  deliverySpec: string;
  constraints: string;
}

export interface CharacterDashboardRisk {
  item: string;
  status: 'BLOCKED' | 'PENDING' | 'PASS';
  note: string;
}

export interface CharacterDashboardResponse {
  schemaVersion: 'character-dashboard.v1';
  taskId: string;
  sourceHash: string;
  title: string;
  state: CharacterDashboardState;
  viewContract: CharacterViewContract;
  stats: CharacterDashboardStats;
  project: CharacterDashboardProject;
  assumptions: string[];
  risks: CharacterDashboardRisk[];
  characters: CharacterDashboardCharacter[];
  rawText: string;
}

export const DEFAULT_VIEW_CONTRACT: CharacterViewContract = {
  version: 'five-view.v1',
  order: [...FIVE_VIEW_KEYS],
  views: [
    { key: 'front', order: 1, angleDegrees: 0, labelZh: '正面', labelEn: 'Front view' },
    { key: 'front_three_quarter', order: 2, angleDegrees: 45, labelZh: '正面四分之三', labelEn: 'Front three-quarter view' },
    { key: 'profile', order: 3, angleDegrees: 90, labelZh: '标准侧面', labelEn: 'Standard profile view' },
    { key: 'rear_three_quarter', order: 4, angleDegrees: 135, labelZh: '背面四分之三', labelEn: 'Rear three-quarter view' },
    { key: 'back', order: 5, angleDegrees: 180, labelZh: '背面', labelEn: 'Back view' },
  ],
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback;
}

function hasUnsafeUrlCharacter(value: string): boolean {
  return [...value].some(character => {
    const code = character.charCodeAt(0);
    return character === '\\' || code <= 31 || code === 127;
  });
}

function safeRelativeMediaPath(value: string): string | null {
  if (!value.startsWith('/media/') || hasUnsafeUrlCharacter(value) || /[?#]/.test(value)) {
    return null;
  }

  let decoded = value;
  for (let depth = 0; depth < 12; depth += 1) {
    if (!decoded.startsWith('/media/') || hasUnsafeUrlCharacter(decoded) || /[?#]/.test(decoded)) {
      return null;
    }
    if (decoded.split('/').some(segment => segment === '.' || segment === '..')) {
      return null;
    }

    let next: string;
    try {
      next = decodeURIComponent(decoded);
    } catch {
      return null;
    }
    if (next === decoded) return value;
    decoded = next;
  }

  return null;
}

/** Restrict character artwork to remote HTTP(S) images or same-service media paths. */
export function sanitizeCharacterMediaUrl(value: unknown): string | null {
  const candidate = text(value);
  if (!candidate || hasUnsafeUrlCharacter(candidate)) return null;

  if (candidate.startsWith('/')) return safeRelativeMediaPath(candidate);

  try {
    const url = new URL(candidate);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function booleanOrNull(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => text(item)).filter(Boolean) : [];
}

function viewKey(value: unknown): FiveViewKey | null {
  const normalized = text(value).toLowerCase().replace(/[\s-]+/g, '_');
  const aliases: Record<string, FiveViewKey> = {
    front: 'front', front_view: 'front', '正面': 'front',
    front_three_quarter: 'front_three_quarter', three_quarter_front: 'front_three_quarter',
    '正面四分之三': 'front_three_quarter', '正面3/4': 'front_three_quarter',
    profile: 'profile', side: 'profile', standard_profile: 'profile', standard_profile_view: 'profile',
    '侧面': 'profile', '标准侧面': 'profile',
    rear_three_quarter: 'rear_three_quarter', back_three_quarter: 'rear_three_quarter',
    '背面四分之三': 'rear_three_quarter', '背面3/4': 'rear_three_quarter',
    back: 'back', back_view: 'back', '背面': 'back',
  };
  return aliases[normalized] || null;
}

function normalizeViewContract(value: unknown): CharacterViewContract {
  const raw = record(value);
  const provided = Array.isArray(raw.views) ? raw.views.map(record) : [];
  const views = DEFAULT_VIEW_CONTRACT.views.map(defaultView => {
    const match = provided.find(item => viewKey(item.key ?? item.view) === defaultView.key);
    if (!match) return defaultView;
    return {
      key: defaultView.key,
      order: defaultView.order,
      angleDegrees: numberOrNull(match.angleDegrees ?? match.angle_degrees) ?? defaultView.angleDegrees,
      labelZh: text(match.labelZh ?? match.label_zh, defaultView.labelZh),
      labelEn: text(match.labelEn ?? match.label_en, defaultView.labelEn),
    };
  });
  return { version: text(raw.version, 'five-view.v1'), order: [...FIVE_VIEW_KEYS], views };
}

function normalizeViews(value: unknown): CharacterViewAsset[] {
  const provided = Array.isArray(value) ? value.map(record) : [];
  return FIVE_VIEW_KEYS.map((key, index) => {
    const raw = provided.find(item => viewKey(item.key ?? item.view) === key);
    const imageUrl = sanitizeCharacterMediaUrl(raw?.imageUrl ?? raw?.image_url);
    return { key, order: index + 1, imageUrl, available: Boolean(imageUrl) };
  });
}

function normalizeColors(value: unknown): CharacterColor[] {
  if (!Array.isArray(value)) return [];
  return value.map(item => {
    const raw = record(item);
    const hex = text(raw.hex);
    return { name: text(raw.name), hex: /^#[0-9a-f]{6}$/i.test(hex) ? hex : null };
  }).filter(color => color.name || color.hex);
}

function normalizeStates(value: unknown): CharacterDesignState[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const raw = record(item);
    const anchors = Array.isArray(raw.anchors) ? raw.anchors.map(anchor => {
      const rawAnchor = record(anchor);
      const view = viewKey(rawAnchor.view ?? rawAnchor.key);
      return view ? { view, detail: text(rawAnchor.detail) } : null;
    }).filter((anchor): anchor is CharacterStateAnchor => Boolean(anchor)) : [];
    return {
      stateId: text(raw.stateId ?? raw.state_id, `state-${index + 1}`),
      title: text(raw.title, `状态 ${index + 1}`),
      dna: text(raw.dna),
      hair: text(raw.hair),
      body: text(raw.body),
      clothing: text(raw.clothing),
      accessories: text(raw.accessories),
      style: text(raw.style),
      anchors,
    };
  });
}

function normalizeQuality(value: unknown): CharacterFiveViewQuality {
  const raw = record(value);
  const issues = Array.isArray(raw.issues) ? raw.issues.map(item => {
    const issue = record(item);
    return {
      code: text(issue.code, 'quality_issue'),
      message: text(issue.message),
      viewIndex: numberOrNull(issue.viewIndex ?? issue.view_index),
    };
  }) : [];
  return {
    passed: booleanOrNull(raw.passed),
    paletteSimilarity: numberOrNull(raw.paletteSimilarity ?? raw.palette_similarity),
    uniqueViewHashes: numberOrNull(raw.uniqueViewHashes ?? raw.unique_view_hashes),
    entropy: Array.isArray(raw.entropy) ? raw.entropy.filter((item): item is number => typeof item === 'number' && Number.isFinite(item)) : [],
    issues,
  };
}

function requestedAssetState(value: unknown): CharacterAssetState | null {
  const normalized = text(value).toUpperCase();
  return ['MISSING', 'PARTIAL', 'NEEDS_REVIEW', 'FAILED', 'READY'].includes(normalized)
    ? normalized as CharacterAssetState
    : null;
}

function safeAssetState(
  requested: CharacterAssetState | null,
  views: CharacterViewAsset[],
  sheetUrl: string | null,
  quality: CharacterFiveViewQuality,
): CharacterAssetState {
  const available = views.filter(view => view.available).length;
  if (requested === 'FAILED') return 'FAILED';
  if (available === 5 && quality.passed === true) return 'READY';
  if (available === 5) return requested === 'PARTIAL' ? 'PARTIAL' : 'NEEDS_REVIEW';
  if (available > 0) return 'PARTIAL';
  if (sheetUrl) return 'NEEDS_REVIEW';
  return 'MISSING';
}

function normalizeCharacter(value: unknown, index: number): CharacterDashboardCharacter {
  const raw = record(value);
  const views = normalizeViews(raw.views);
  const quality = normalizeQuality(raw.quality);
  const sheetUrl = sanitizeCharacterMediaUrl(raw.sheetUrl ?? raw.sheet ?? raw.sheet_url);
  return {
    characterId: text(raw.characterId ?? raw.character_id, `legacy-character-${index + 1}`),
    name: text(raw.name, `未命名角色 ${index + 1}`),
    role: text(raw.role ?? raw.position, '剧情角色'),
    description: text(raw.description ?? raw.desc),
    identity: text(raw.identity),
    voiceId: text(raw.voiceId ?? raw.voice_id),
    colors: normalizeColors(raw.colors),
    states: normalizeStates(raw.states),
    sheetUrl,
    assetState: safeAssetState(requestedAssetState(raw.assetState ?? raw.asset_state), views, sheetUrl, quality),
    views,
    quality,
  };
}

function statsFor(characters: CharacterDashboardCharacter[]): CharacterDashboardStats {
  const count = (state: CharacterAssetState) => characters.filter(character => character.assetState === state).length;
  return {
    characterCount: characters.length,
    readyCount: count('READY'),
    needsReviewCount: count('NEEDS_REVIEW'),
    partialCount: count('PARTIAL'),
    missingCount: count('MISSING'),
    failedCount: count('FAILED'),
    availableViewCount: characters.flatMap(character => character.views).filter(view => view.available).length,
    expectedViewCount: characters.length * FIVE_VIEW_KEYS.length,
  };
}

export function normalizeCharacterDashboard(value: unknown): CharacterDashboardResponse {
  const raw = record(value);
  const characters = Array.isArray(raw.characters)
    ? raw.characters.map((character, index) => normalizeCharacter(character, index))
    : [];
  const projectRaw = record(raw.project);
  const risks = Array.isArray(raw.risks) ? raw.risks.map(item => {
    const risk = record(item);
    const status = text(risk.status).toUpperCase();
    return {
      item: text(risk.item),
      status: (['BLOCKED', 'PENDING', 'PASS'].includes(status) ? status : 'PENDING') as CharacterDashboardRisk['status'],
      note: text(risk.note),
    };
  }).filter(risk => risk.item) : [];
  const requestedState = text(raw.state).toUpperCase();
  return {
    schemaVersion: 'character-dashboard.v1',
    taskId: text(raw.taskId ?? raw.task_id),
    sourceHash: text(raw.sourceHash ?? raw.source_hash),
    title: text(raw.title, '角色设定集'),
    state: (['WAITING', 'INCOMPLETE', 'READY'].includes(requestedState) ? requestedState : characters.length ? 'INCOMPLETE' : 'WAITING') as CharacterDashboardState,
    viewContract: normalizeViewContract(raw.viewContract ?? raw.view_contract),
    stats: statsFor(characters),
    project: {
      genre: text(projectRaw.genre),
      platform: text(projectRaw.platform),
      deliverySpec: text(projectRaw.deliverySpec ?? projectRaw.delivery_spec),
      constraints: text(projectRaw.constraints),
    },
    assumptions: stringList(raw.assumptions),
    risks,
    characters,
    rawText: text(raw.rawText ?? raw.raw_text),
  };
}

export function buildLegacyCharacterDashboard({
  title,
  characters: characterValue,
  sheets: sheetValue,
  dna: dnaValue,
  raw: rawValue,
}: {
  title?: string;
  characters?: unknown;
  sheets?: unknown;
  dna?: unknown;
  raw?: unknown;
}): CharacterDashboardResponse {
  const dna = record(dnaValue);
  const dnaCharacters = Array.isArray(dna.characters) ? dna.characters.map(record) : [];
  const cards = Array.isArray(characterValue) ? characterValue.map(record) : [];
  const sheets = record(sheetValue);
  const names = new Set<string>();
  cards.forEach(card => names.add(text(card.name)));
  dnaCharacters.forEach(character => names.add(text(character.name)));
  Object.keys(sheets).forEach(name => names.add(name));
  names.delete('');
  const merged = [...names].map(name => {
    const card = cards.find(item => text(item.name) === name) || {};
    const dnaCharacter = dnaCharacters.find(item => text(item.name) === name) || {};
    return {
      ...dnaCharacter,
      ...card,
      name,
      sheetUrl: card.sheet ?? sheets[name],
      characterId: dnaCharacter.character_id ?? dnaCharacter.characterId,
      description: card.desc ?? card.description,
      assetState: card.assetState ?? card.asset_state,
      quality: card.quality ?? card.fiveViewQuality ?? card.five_view_quality,
    };
  });
  const project = record(dna.project);
  return normalizeCharacterDashboard({
    title: title || '角色设定集',
    state: merged.length ? 'INCOMPLETE' : 'WAITING',
    project,
    assumptions: dna.assumptions,
    risks: dna.risks,
    characters: merged,
    rawText: typeof rawValue === 'string' ? rawValue : rawValue ? JSON.stringify(rawValue, null, 2) : '',
  });
}

export const CHARACTER_STATE_LABELS: Record<CharacterAssetState, string> = {
  MISSING: '缺少资产',
  PARTIAL: '部分完成',
  NEEDS_REVIEW: '待质量审核',
  FAILED: '生成失败',
  READY: '可交付',
};
