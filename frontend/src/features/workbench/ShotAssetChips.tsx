/**
 * 本镜用到哪些资产(人物、场景、道具、特效)：一眼看清，资产改过要重画或重跑时标黄。
 *
 * 只渲染 span：分镜格和镜头列表本身就是按钮，里面不能再套按钮或链接。
 */
import { t } from '../../i18n';
import { MENTION_KIND_LABELS } from './promptMentions';
import './ShotAssetChips.css';

/** 镜头工作区接口给的一条资产(backend shots/visual 的 assets)；分镜格的 asset_bindings 也按它读。 */
export interface ShotAssetRef {
  kind?: string;
  name?: string;
  element_id?: string | null;
  element_version?: number | null;
  image_number?: number | null;
  in_storyboard?: boolean;
  in_video?: boolean;
  stale?: boolean;
}

export interface ShotAssetChipsProps {
  assets?: ShotAssetRef[] | null;
  characters?: string[] | null;
  props?: string[] | null;
  effects?: string[] | null;
  scene?: string | null;
  /** 旧数据：提示词里 @[名字] → 资产类型；只在没有 assets 时用。 */
  kinds?: Record<string, string> | null;
  /** @[名字] → 随请求上传的第几张参考图。 */
  referenceNumbers?: Record<string, number> | null;
  /** 整镜的资产改过(分镜格的 asset_stale)，显示「资产已改」。 */
  stale?: boolean;
  compact?: boolean;
  /** 叠在分镜画面上(分镜格)；默认随文字排。 */
  overlay?: boolean;
}

type Group = 'people' | 'scene' | 'prop' | 'effect' | 'other';

const GROUP_ORDER: Group[] = ['people', 'scene', 'prop', 'effect', 'other'];
const GROUP_LABELS: Record<Group, string> = { people: '人物', scene: '场景', prop: '道具', effect: '特效', other: '其他' };
const GROUP_OF_KIND: Record<string, Group> = {
  actor: 'people', character: 'people', costume: 'people', extra: 'people', makeup: 'people',
  scene: 'scene', set_dressing: 'scene',
  prop: 'prop', product: 'prop', vehicle: 'prop',
  effect: 'effect',
};
const COMPACT_LIMIT = 4;
const STALE_TITLE = '资产已改，需重画或重跑';

interface Chip {
  key: string;
  kind: string;
  group: Group;
  name: string;
  imageNumber: number | null;
  inStoryboard?: boolean;
  inVideo?: boolean;
  stale: boolean;
}

// 分镜表里「本格无额外道具」「空镜（无人物）」这类占位不是资产；规则与后端 asset_dependents._PLACEHOLDER 一致。
const PLACEHOLDER = /^(?:本格无|本镜无|空镜|无$|无人|无出场|[—-]$)/;

function groupOf(kind: string): Group {
  return GROUP_OF_KIND[kind] ?? 'other';
}

/** 各路输入合成一张去重的表：同类同名只留一个，先来的 assets 定属性，后来的只补空缺。 */
function normaliseShotAssets(input: ShotAssetChipsProps): Chip[] {
  const chips = new Map<string, Chip>();
  const numbers = input.referenceNumbers ?? {};
  const add = (ref: ShotAssetRef) => {
    const name = String(ref.name ?? '').trim();
    if (!name || PLACEHOLDER.test(name)) return;
    const kind = String(ref.kind ?? '').trim() || 'other';
    const group = groupOf(kind);
    const key = `${group}:${name}`;
    const fromRef = typeof ref.image_number === 'number' ? ref.image_number : null;
    const imageNumber = fromRef ?? (typeof numbers[name] === 'number' ? numbers[name] : null);
    const existing = chips.get(key);
    if (existing) {
      existing.imageNumber ??= imageNumber;
      existing.stale = existing.stale || Boolean(ref.stale);
      if (ref.in_storyboard !== undefined) existing.inStoryboard = Boolean(existing.inStoryboard) || ref.in_storyboard;
      if (ref.in_video !== undefined) existing.inVideo = Boolean(existing.inVideo) || ref.in_video;
      return;
    }
    chips.set(key, {
      key, kind, group, name, imageNumber,
      inStoryboard: ref.in_storyboard, inVideo: ref.in_video, stale: Boolean(ref.stale),
    });
  };
  const assets = Array.isArray(input.assets) ? input.assets : [];
  assets.forEach(add);
  (input.characters ?? []).forEach(name => add({ kind: 'actor', name }));
  if (input.scene) add({ kind: 'scene', name: input.scene });
  (input.props ?? []).forEach(name => add({ kind: 'prop', name }));
  (input.effects ?? []).forEach(name => add({ kind: 'effect', name }));
  if (assets.length === 0) {
    Object.entries(input.kinds ?? {}).forEach(([name, kind]) => add({ kind, name }));
  }
  return [...chips.values()].sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group));
}

function placeMarker(chip: Chip): string {
  if (chip.inVideo === true && chip.inStoryboard !== true) return '视频';
  if (chip.inStoryboard === true && chip.inVideo !== true) return '分镜';
  return '';
}

function chipTitle(chip: Chip): string {
  const kindLabel = MENTION_KIND_LABELS[chip.kind] ?? GROUP_LABELS[chip.group];
  const marker = placeMarker(chip);
  return [
    `${t(kindLabel)}：${chip.name}`,
    chip.imageNumber !== null ? t('第 {0} 张参考图', [String(chip.imageNumber)]) : '',
    marker === '视频' ? t('只在视频里用到') : marker === '分镜' ? t('只在分镜里用到') : '',
    chip.stale ? t(STALE_TITLE) : '',
  ].filter(Boolean).join('\n');
}

function AssetChip({ chip }: { chip: Chip }) {
  const marker = placeMarker(chip);
  return (
    <span className={`shot-assets__chip is-${chip.group}${chip.stale ? ' is-stale' : ''}`} title={chipTitle(chip)}>
      <span className="shot-assets__name">{chip.name}</span>
      {chip.imageNumber !== null && <span className="shot-assets__badge">{t('图{0}', [String(chip.imageNumber)])}</span>}
      {marker && <span className="shot-assets__marker">{t(marker)}</span>}
    </span>
  );
}

export function ShotAssetChips(props: ShotAssetChipsProps) {
  const chips = normaliseShotAssets(props);
  if (chips.length === 0 && !props.stale) return null;
  const className = ['shot-assets', props.compact ? 'is-compact' : '', props.overlay ? 'is-overlay' : ''].filter(Boolean).join(' ');
  const staleBadge = props.stale && (
    <span className="shot-assets__stale" title={t(STALE_TITLE)}>{t('资产已改')}</span>
  );

  if (props.compact) {
    const shown = chips.slice(0, COMPACT_LIMIT);
    const rest = chips.slice(COMPACT_LIMIT);
    return (
      <span className={className} role="group" aria-label={t('本镜用到的资产')}>
        {staleBadge}
        {shown.map(chip => <AssetChip key={chip.key} chip={chip} />)}
        {rest.length > 0 && (
          <span className="shot-assets__more" title={rest.map(chip => chip.name).join('、')}>+{rest.length}</span>
        )}
      </span>
    );
  }

  return (
    <span className={className} role="group" aria-label={t('本镜用到的资产')}>
      {staleBadge}
      {GROUP_ORDER.map(group => {
        const members = chips.filter(chip => chip.group === group);
        if (members.length === 0) return null;
        return (
          <span key={group} className={`shot-assets__group is-${group}`}>
            <span className="shot-assets__group-label">{t(GROUP_LABELS[group])}</span>
            {members.map(chip => <AssetChip key={chip.key} chip={chip} />)}
          </span>
        );
      })}
    </span>
  );
}
