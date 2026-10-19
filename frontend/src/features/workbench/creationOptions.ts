/**
 * Choices and defaults of the "new project" form.
 *
 * Every screen that names a director style or a shot style reads it from here,
 * so the create dialog, the task defaults and the director's planning page
 * cannot drift apart.
 */
export interface CreationOption {
  id: string;
  /** Full label in the create dialog. */
  label: string;
  /** Short name used where the style is mentioned in running text. */
  name: string;
}

export const DIRECTOR_STYLES: readonly CreationOption[] = [
  { id: 'cyberpunk', label: 'Cyberpunk 赛博朋克', name: '赛博霓虹' },
  { id: 'retro', label: 'Retro 怀旧经典', name: '怀旧经典' },
  { id: 'realistic', label: 'Realistic 电影写实', name: '现实主义' },
  { id: 'sci_fi_future', label: 'Sci-Fi Future 科幻未来', name: '科幻未来' },
  { id: 'palace', label: 'Ancient Palace 古风宫廷', name: '古风宫廷' },
  { id: 'mystery_dark', label: 'Dark Mystery 悬疑暗黑', name: '悬疑暗黑' },
  { id: 'anime', label: 'Anime Niji 动漫二次元', name: '动漫二次元' },
  { id: 'horror_folk', label: 'Horror Folk 民俗惊悚', name: '民俗惊悚' },
];

export const SHOT_STYLES: readonly CreationOption[] = [
  { id: 'cinematic', label: 'Cinematic 36运镜系统', name: '电影级叙事' },
  { id: 'standard', label: 'Standard 普通分镜', name: '经典叙事' },
];

export const DEFAULT_DIRECTOR_STYLE = DIRECTOR_STYLES[0].id;
export const DEFAULT_SHOT_STYLE = SHOT_STYLES[0].id;

export interface StylePackOption {
  id: string;
  name: string;
}

/**
 * Style locks shown until `GET /api/production/style-packs` answers; the server's
 * catalogue replaces this list, so a pack added there needs no change here.
 */
export const FALLBACK_STYLE_PACKS: readonly StylePackOption[] = [
  { id: 'cinematic_realism', name: '真人电影写实' },
  { id: 'film_35mm', name: '35mm 胶片电影' },
  { id: 'atom_punk', name: '原子朋克废土' },
  { id: 'anime_2d_cel', name: '2D 赛璐珞漫剧' },
  { id: 'anime_3d_cg', name: '3D 国漫 CG' },
];
export const FALLBACK_STYLE_PACK = FALLBACK_STYLE_PACKS[0].id;

/** Short name of a director or shot style; an id this build does not know is shown as it is. */
export function styleName(id: string | undefined): string | undefined {
  if (!id) return undefined;
  return [...DIRECTOR_STYLES, ...SHOT_STYLES].find(option => option.id === id)?.name ?? id;
}

/** Read the style-pack catalogue, ignoring entries without a usable id and name. */
export function parseStylePacks(raw: unknown): { packs: StylePackOption[]; defaultId: string } | null {
  if (!raw || typeof raw !== 'object') return null;
  const source = raw as { default?: unknown; packs?: unknown };
  if (!Array.isArray(source.packs)) return null;
  const packs = source.packs.flatMap(item => {
    const pack = item as { id?: unknown; name?: unknown } | null;
    return pack && typeof pack.id === 'string' && pack.id && typeof pack.name === 'string' && pack.name
      ? [{ id: pack.id, name: pack.name }]
      : [];
  });
  if (packs.length === 0) return null;
  const defaultId = typeof source.default === 'string' && packs.some(pack => pack.id === source.default)
    ? source.default
    : packs[0].id;
  return { packs, defaultId };
}
