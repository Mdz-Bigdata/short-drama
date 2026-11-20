import { t } from '../../i18n';

/**
 * 捏脸数据的形状与小工具。控件表、预设、特征种类与部位、造型编辑器的版面都来自服务端
 * (backend app/data/prompt/face_sculpt.json，经 /api/face-sculpt/catalog)。
 */

export interface SculptOption { value: string; label: string; group?: string; swatch?: string }
export interface SculptControl {
  key: string;
  layer: string;
  label: string;
  /** choice：选一个；scale：-2..2，0 是沿用原描述；level：0..档数-1，0 是不加。 */
  type: 'choice' | 'scale' | 'level';
  options?: SculptOption[];
  steps?: string[];
}
export interface MarkKind { key: string; label: string; region: boolean; text: boolean; swatch?: string }
export interface MarkRegion { key: string; label: string; area: 'face' | 'body'; x: number; y: number }
export interface StudioSection { key: string; label: string; controls: string[]; presets?: boolean }
export interface StudioPanel {
  key: string;
  label: string;
  sections?: StudioSection[];
  marks?: boolean;
  voice?: boolean;
  expression?: boolean;
}
export interface SculptCatalog {
  layers: { key: string; label: string }[];
  controls: SculptControl[];
  /** scope：预设只铺这几层(年龄、皮肤、毛发照旧)；没有就整张脸重铺。focus：预设自带的突出点。 */
  presets: { key: string; label: string; values: Record<string, string | number>; scope?: string[]; focus?: string }[];
  focus_layers?: string[];
  expression_controls: { key: string; label: string; options: SculptOption[] }[];
  expressions: { key: string; label: string; words: string[] }[];
  limits: { note_chars: number; tell_chars: number; habit_chars: number };
  marks?: { kinds: MarkKind[]; regions: MarkRegion[]; limit: number; text_chars: number };
  studio?: { panels: StudioPanel[] };
}

export interface ExpressionValue { choices: Record<string, string>; tell: string; habit: string }
export interface SculptMark { kind: string; region: string; text: string }
export interface FaceSculptValue {
  face: Record<string, string | number>;
  notes: Record<string, string>;
  expressions: Record<string, ExpressionValue>;
  preset: string;
  /** 这张脸的突出点：一个骨相或五官控件键，其余控件围着它做配合。 */
  focus: string;
  /** 痣、疤、雀斑、纹身。 */
  marks: SculptMark[];
}
export interface SculptPreview {
  description: string;
  face_text: string;
  layers: Record<string, string>;
  issues: { code: string; message: string }[];
  expressions: Record<string, string>;
  sheet_stale: boolean;
  stale_note: string;
}
export interface SculptHistoryEntry { id: string; label: string; at: number; revision: number }
export interface SculptCurrent {
  name: string;
  sculpt: Partial<FaceSculptValue>;
  revision: number;
  preview: SculptPreview;
  label?: string;
  updated_at?: number;
  history?: SculptHistoryEntry[];
  downstream?: { clips_marked: number; sheet_stale: boolean };
  library?: { updated: boolean; element_id?: string; error?: string };
}

export const EMPTY_SCULPT: FaceSculptValue = { face: {}, notes: {}, expressions: {}, preset: '', focus: '', marks: [] };
export const EMPTY_EXPRESSION: ExpressionValue = { choices: {}, tell: '', habit: '' };
const HISTORY_SHOWN = 6;

export function sculptBase(taskId: string, name: string) {
  return `/api/drama/${encodeURIComponent(taskId)}/characters/${encodeURIComponent(name)}/face-sculpt`;
}

export function normalizeSculpt(value: Partial<FaceSculptValue> | undefined): FaceSculptValue {
  const expressions: Record<string, ExpressionValue> = {};
  for (const [key, item] of Object.entries(value?.expressions || {})) {
    expressions[key] = { choices: { ...(item?.choices || {}) }, tell: item?.tell || '', habit: item?.habit || '' };
  }
  const marks = Array.isArray(value?.marks)
    ? value.marks.filter(mark => mark && mark.kind).map(mark => ({ kind: mark.kind, region: mark.region || '', text: mark.text || '' }))
    : [];
  return {
    face: { ...(value?.face || {}) }, notes: { ...(value?.notes || {}) }, expressions, preset: value?.preset || '', focus: value?.focus || '', marks,
  };
}

export function historyOf(current: SculptCurrent): SculptHistoryEntry[] {
  if (!Array.isArray(current.history)) return [];
  return current.history.filter(item => item && item.id && Number.isFinite(item.at)).slice(0, HISTORY_SHOWN);
}

/** 「3 分钟前」：at 是服务端的 unix 秒。 */
export function relativeTime(at: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.floor(now / 1000 - at));
  if (seconds < 60) return t('刚刚');
  if (seconds < 3600) return t('{n} 分钟前', { n: Math.floor(seconds / 60) });
  if (seconds < 86400) return t('{n} 小时前', { n: Math.floor(seconds / 3600) });
  return t('{n} 天前', { n: Math.floor(seconds / 86400) });
}

/** 落盘之后下游的结果：要重跑几段视频、元素库有没有同步。 */
export function downstreamNotes(current: SculptCurrent): string[] {
  const notes: string[] = [];
  const clips = Number(current.downstream?.clips_marked || 0);
  if (clips > 0) notes.push(t('{n} 段视频需重跑第 5 阶段才会换上新脸', { n: clips }));
  if (current.library?.updated) notes.push(t('元素库里的演员描述已同步'));
  return notes;
}

/** 一个控件当前的值；0 和空都算没动。 */
export function controlValue(value: FaceSculptValue, key: string): string | number {
  return value.face[key] ?? '';
}

/** 铺一个预设：只铺 scope 里的层，没有 scope 就整张脸重铺；预设自带突出点就用它的。 */
export function withPreset(catalog: SculptCatalog, value: FaceSculptValue, key: string): FaceSculptValue {
  const preset = catalog.presets.find(item => item.key === key);
  if (!preset) return value;
  const scope = preset.scope;
  const kept = scope
    ? Object.fromEntries(Object.entries(value.face).filter(([control]) => {
      const layer = catalog.controls.find(item => item.key === control)?.layer;
      return !layer || !scope.includes(layer);
    }))
    : {};
  const face = { ...kept, ...preset.values };
  const focus = preset.focus || (value.focus in face ? value.focus : '');
  return { ...value, face, preset: key, focus };
}

/** 改一个控件：空值、0 都是去掉这一项(沿用原描述)；手动改过就不再算某个预设。 */
export function withControl(value: FaceSculptValue, key: string, next: string | number): FaceSculptValue {
  const face = { ...value.face };
  if (next === '' || next === 0) delete face[key];
  else face[key] = next;
  return { ...value, face, preset: '' };
}
