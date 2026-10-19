// 数字演员设定集的五个身份锚点：三张全身 + 两张头部。
// 与后端 app/schema/production.py 的 IDENTITY_VIEW_ORDER 逐项对应。
export const FIVE_VIEW_KEYS = [
  'front',
  'profile',
  'back',
  'face_front',
  'face_three_quarter',
] as const;

export type FiveViewKey = (typeof FIVE_VIEW_KEYS)[number];

// 设定集 25 格的切图顺序，与后端 core/actor_sheet_layout.py 的 ACTOR_SHEET_CELL_ORDER 一致。
export const ACTOR_SHEET_CELL_KEYS = [
  'portrait',
  'full_body',
  'front',
  'profile',
  'back',
  'element_shoe',
  'element_waist',
  'element_wrist',
  'element_collar',
  'element_fabric',
  'element_hair',
  'element_hand',
  'element_hem',
  'face_front',
  'face_three_quarter',
  'face_three_quarter_right',
  'face_back_hair',
  'detail_collar',
  'detail_chest',
  'detail_waist_knot',
  'detail_cuff',
  'detail_texture',
  'detail_shoe',
  'detail_eye',
  'detail_accessory',
] as const;

export type ActorSheetCellKey = (typeof ACTOR_SHEET_CELL_KEYS)[number];
export type ActorSheetCellGroup =
  | 'main_portrait'
  | 'full_body'
  | 'three_view'
  | 'elements'
  | 'detail_matrix';

export interface ActorSheetCell {
  key: ActorSheetCellKey;
  order: number;
  group: ActorSheetCellGroup;
  imageUrl: string | null;
  available: boolean;
  /** 模型没单独画这一格时，从哪个身份面板按部位补裁(full_body / portrait / back)。 */
  derivedFrom?: ActorSheetCellKey | null;
}

// 格子 → 它在版面上属于哪个区域，与后端 ACTOR_SHEET_LAYOUT 的区域划分一致。
export const ACTOR_SHEET_CELL_GROUPS: Record<ActorSheetCellKey, ActorSheetCellGroup> = {
  portrait: 'main_portrait',
  full_body: 'full_body',
  front: 'three_view',
  profile: 'three_view',
  back: 'three_view',
  element_shoe: 'elements',
  element_waist: 'elements',
  element_wrist: 'elements',
  element_collar: 'elements',
  element_fabric: 'elements',
  element_hair: 'elements',
  element_hand: 'elements',
  element_hem: 'elements',
  face_front: 'detail_matrix',
  face_three_quarter: 'detail_matrix',
  face_three_quarter_right: 'detail_matrix',
  face_back_hair: 'detail_matrix',
  detail_collar: 'detail_matrix',
  detail_chest: 'detail_matrix',
  detail_waist_knot: 'detail_matrix',
  detail_cuff: 'detail_matrix',
  detail_texture: 'detail_matrix',
  detail_shoe: 'detail_matrix',
  detail_eye: 'detail_matrix',
  detail_accessory: 'detail_matrix',
};
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

/** 单角色重新生成：sheet 重出设定集；hd 补高清身份视图；details 把补位裁切的细节格真正画出来。 */
export type CharacterRegenerateMode = 'sheet' | 'hd' | 'details';

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
  /** 设定集的其余格子；旧五视图记录为空数组。 */
  sheetCells: ActorSheetCell[];
  quality: CharacterFiveViewQuality;
  /** 单个角色「重新生成设定集」正在后台跑。 */
  regenerating?: boolean;
  /** 上一次重新生成失败的原因；成功或从未重新生成为空。 */
  regenerationError?: string;
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
    { key: 'front', order: 1, angleDegrees: 0, labelZh: '正面全身', labelEn: 'Front full body' },
    { key: 'profile', order: 2, angleDegrees: 90, labelZh: '侧面全身', labelEn: 'Profile full body' },
    { key: 'back', order: 3, angleDegrees: 180, labelZh: '背面全身', labelEn: 'Back full body' },
    { key: 'face_front', order: 4, angleDegrees: 0, labelZh: '正脸特写', labelEn: 'Face front close-up' },
    { key: 'face_three_quarter', order: 5, angleDegrees: 45, labelZh: '左侧45°侧脸', labelEn: 'Face left 45°' },
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

// 存量记录里的旧角度键，只在新锚点自己没图时顶上（见 resolveIdentityViews）。
const LEGACY_VIEW_KEYS = ['front_three_quarter', 'rear_three_quarter'] as const;
type LegacyViewKey = (typeof LEGACY_VIEW_KEYS)[number];
type StoredViewKey = FiveViewKey | LegacyViewKey;

const LEGACY_VIEW_ALIASES: Record<LegacyViewKey, FiveViewKey> = {
  front_three_quarter: 'face_three_quarter',  // 旧 45° 全身 → 3-4 侧脸锚点
  rear_three_quarter: 'back',                 // 旧 135° 全身 → 背面全身
};
// 旧整板没有单独的头部裁切，正面全身兼任正脸锚点；只对旧记录生效。
const LEGACY_VIEW_FALLBACKS: Partial<Record<FiveViewKey, FiveViewKey>> = {
  face_front: 'front',
};

function viewKey(value: unknown): StoredViewKey | null {
  const normalized = text(value).toLowerCase().replace(/[\s-]+/g, '_');
  const aliases: Record<string, StoredViewKey> = {
    front: 'front', front_view: 'front', front_full_body: 'front',
    '正面': 'front', '正面全身': 'front',
    profile: 'profile', side: 'profile', standard_profile: 'profile', standard_profile_view: 'profile',
    profile_full_body: 'profile', '侧面': 'profile', '标准侧面': 'profile', '侧面全身': 'profile',
    back: 'back', back_view: 'back', back_full_body: 'back', '背面': 'back', '背面全身': 'back',
    face_front: 'face_front', front_face: 'face_front', '正脸': 'face_front', '正脸特写': 'face_front',
    face_three_quarter: 'face_three_quarter', three_quarter_face: 'face_three_quarter',
    '3_4侧脸': 'face_three_quarter', '四分之三侧脸': 'face_three_quarter',
    front_three_quarter: 'front_three_quarter', three_quarter_front: 'front_three_quarter',
    '正面四分之三': 'front_three_quarter', '正面3/4': 'front_three_quarter',
    rear_three_quarter: 'rear_three_quarter', back_three_quarter: 'rear_three_quarter',
    '背面四分之三': 'rear_three_quarter', '背面3/4': 'rear_three_quarter',
  };
  return aliases[normalized] || null;
}

function cellKey(value: unknown): ActorSheetCellKey | null {
  const normalized = text(value).toLowerCase().replace(/[\s-]+/g, '_');
  return (ACTOR_SHEET_CELL_KEYS as readonly string[]).includes(normalized)
    ? normalized as ActorSheetCellKey
    : null;
}

/** 把任意一代的 view→url 映射归一到 FIVE_VIEW_KEYS 上。与后端 resolve_identity_views 同一规则。 */
function resolveIdentityViews(stored: Partial<Record<StoredViewKey, string>>): Partial<Record<FiveViewKey, string>> {
  const resolved: Partial<Record<FiveViewKey, string>> = {};
  FIVE_VIEW_KEYS.forEach(key => {
    if (stored[key]) resolved[key] = stored[key];
  });
  LEGACY_VIEW_KEYS.forEach(legacyKey => {
    const target = LEGACY_VIEW_ALIASES[legacyKey];
    if (!resolved[target] && stored[legacyKey]) resolved[target] = stored[legacyKey];
  });
  const isLegacyRecord = LEGACY_VIEW_KEYS.some(key => stored[key])
    && !stored.face_front && !stored.face_three_quarter;
  if (isLegacyRecord) {
    (Object.entries(LEGACY_VIEW_FALLBACKS) as [FiveViewKey, FiveViewKey][]).forEach(([target, source]) => {
      if (!resolved[target] && resolved[source]) resolved[target] = resolved[source];
    });
  }
  return resolved;
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
  const stored: Partial<Record<StoredViewKey, string>> = {};
  provided.forEach(item => {
    const key = viewKey(item.key ?? item.view);
    const imageUrl = sanitizeCharacterMediaUrl(item.imageUrl ?? item.image_url);
    if (key && imageUrl && !stored[key]) stored[key] = imageUrl;
  });
  const resolved = resolveIdentityViews(stored);
  return FIVE_VIEW_KEYS.map((key, index) => ({
    key,
    order: index + 1,
    imageUrl: resolved[key] ?? null,
    available: Boolean(resolved[key]),
  }));
}

function normalizeSheetCells(value: unknown): ActorSheetCell[] {
  const provided = Array.isArray(value) ? value.map(record) : [];
  const urls: Partial<Record<ActorSheetCellKey, string>> = {};
  const derived: Partial<Record<ActorSheetCellKey, ActorSheetCellKey>> = {};
  provided.forEach(item => {
    const key = cellKey(item.key ?? item.cell ?? item.view);
    const imageUrl = sanitizeCharacterMediaUrl(item.imageUrl ?? item.image_url);
    if (key && imageUrl && !urls[key]) {
      urls[key] = imageUrl;
      const source = cellKey(item.derivedFrom ?? item.derived_from);
      if (source) derived[key] = source;
    }
  });
  if (!Object.keys(urls).length) return [];
  return ACTOR_SHEET_CELL_KEYS.map((key, index) => ({
    key,
    order: index + 1,
    group: ACTOR_SHEET_CELL_GROUPS[key],
    imageUrl: urls[key] ?? null,
    available: Boolean(urls[key]),
    derivedFrom: derived[key] ?? null,
  }));
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
    sheetCells: normalizeSheetCells(raw.sheetCells ?? raw.sheet_cells ?? raw.cells),
    quality,
    regenerating: raw.regenerating === true,
    regenerationError: text(raw.regenerationError ?? raw.regeneration_error),
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
