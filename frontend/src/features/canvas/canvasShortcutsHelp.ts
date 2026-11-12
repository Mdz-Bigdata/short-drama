// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-shortcuts.ts.
//
// The help panel's table. It lists only what the canvas does: the keys handled in CanvasWorkspace and
// CanvasSurface, plus the view keys, search and node menu that the workspace wires in alongside this.
import { t } from '../../i18n';

export type ShortcutPlatform = 'mac' | 'other';
export type ShortcutGroupId = 'view' | 'select' | 'edit' | 'run';

export interface ShortcutItem {
  id: string;
  /** Each entry is one way to do it, already spelled for the platform. */
  keys: string[];
  what: string;
}

export interface ShortcutGroup {
  id: ShortcutGroupId;
  label: string;
  items: ShortcutItem[];
}

interface Spec {
  id: string;
  group: ShortcutGroupId;
  /** `Mod` is ⌘ on a Mac and Ctrl elsewhere; `Shift`/`Alt` are spelled per platform too. */
  keys: string[] | (() => string[]);
  what: () => string;
}

const SPECS: Spec[] = [
  { id: 'pan', group: 'view', keys: () => [t('空格 + 拖动'), t('中键拖动')], what: () => t('平移画布') },
  { id: 'wheel-zoom', group: 'view', keys: () => [t('滚轮')], what: () => t('以光标为中心缩放') },
  { id: 'zoom-in', group: 'view', keys: ['Mod + +'], what: () => t('放大') },
  { id: 'zoom-out', group: 'view', keys: ['Mod + -'], what: () => t('缩小') },
  { id: 'zoom-reset', group: 'view', keys: ['Mod + 0'], what: () => t('缩放到 100%') },
  { id: 'fit-all', group: 'view', keys: ['Mod + 1'], what: () => t('显示全部') },
  { id: 'fit-selection', group: 'view', keys: ['Mod + 2'], what: () => t('显示所选') },
  { id: 'fit', group: 'view', keys: ['F'], what: () => t('显示全部（有选中时显示所选）') },
  { id: 'bookmark-jump', group: 'view', keys: ['1 … 9'], what: () => t('跳到视图书签') },
  { id: 'bookmark-save', group: 'view', keys: ['Shift + 1 … 9'], what: () => t('保存视图书签') },
  { id: 'search', group: 'view', keys: ['Mod + F'], what: () => t('搜索节点并跳过去') },
  { id: 'help', group: 'view', keys: ['?'], what: () => t('打开或关闭快捷键说明') },

  { id: 'select-add', group: 'select', keys: () => [t('Shift + 点击或框选')], what: () => t('追加到所选') },
  { id: 'select-all', group: 'select', keys: ['Mod + A'], what: () => t('全选') },
  { id: 'deselect', group: 'select', keys: ['Esc'], what: () => t('取消当前操作，再按取消选择') },
  { id: 'nudge', group: 'select', keys: () => [t('方向键')], what: () => t('微调所选（Shift 走 10 格）') },
  { id: 'no-snap', group: 'select', keys: () => [t('Alt + 拖动')], what: () => t('拖动时不吸附') },
  { id: 'align', group: 'select', keys: () => [t('多选后用工具栏')], what: () => t('对齐与分布所选节点') },

  { id: 'undo', group: 'edit', keys: ['Mod + Z'], what: () => t('撤销') },
  { id: 'redo', group: 'edit', keys: ['Mod + Shift + Z', 'Mod + Y'], what: () => t('重做') },
  { id: 'copy', group: 'edit', keys: ['Mod + C'], what: () => t('复制') },
  { id: 'cut', group: 'edit', keys: ['Mod + X'], what: () => t('剪切') },
  { id: 'paste', group: 'edit', keys: ['Mod + V'], what: () => t('粘贴（也可以粘贴图片、视频、音频或文本）') },
  { id: 'duplicate', group: 'edit', keys: ['Mod + D'], what: () => t('就地复制') },
  { id: 'group', group: 'edit', keys: ['Mod + G'], what: () => t('成组') },
  { id: 'ungroup', group: 'edit', keys: ['Mod + Shift + G'], what: () => t('解组') },
  { id: 'delete', group: 'edit', keys: ['Delete', 'Backspace'], what: () => t('删除所选') },
  { id: 'context-menu', group: 'edit', keys: () => [t('右键')], what: () => t('打开节点或画布菜单') },
  { id: 'save', group: 'edit', keys: ['Mod + S'], what: () => t('立即保存') },

  { id: 'run-selected', group: 'run', keys: () => [t('工具栏「运行所选」')], what: () => t('运行所选节点（先估价，付费项会先确认）') },
  { id: 'run-node', group: 'run', keys: () => [t('节点上的「运行」')], what: () => t('只运行这一个节点') },
  { id: 'run-menu', group: 'run', keys: () => [t('右键节点')], what: () => t('从菜单运行或停止') },
];

/** One key cap: a letter, digit, sign or F-key. */
const SINGLE_KEY = /^([A-Za-z0-9=+\-?]|F\d{1,2}|Delete|Backspace|Esc)$/;
const MAC_WORDS: Record<string, string> = { Mod: '⌘', Shift: '⇧', Alt: '⌥', Delete: '⌦', Backspace: '⌫', Esc: 'Esc' };
const OTHER_WORDS: Record<string, string> = { Mod: 'Ctrl', Shift: 'Shift', Alt: 'Alt', Delete: 'Delete', Backspace: 'Backspace', Esc: 'Esc' };

/** Spell a combo for a platform: "Mod + Shift + Z" is "⌘⇧Z" on a Mac and "Ctrl + Shift + Z" elsewhere. */
export function spellKeys(combo: string, platform: ShortcutPlatform): string {
  const parts = combo.split(' + ');
  // Only a leading run of known modifiers is rewritten; whatever follows them is kept as written.
  if (!parts.slice(0, -1).every(part => part in MAC_WORDS)) return combo;
  if (platform === 'mac') {
    const spelled = parts.map(part => MAC_WORDS[part] ?? part);
    // ⌘⇧Z reads as one chord; "⇧ 1 … 9" or "⇧ 点击或框选" keep a space before the words.
    return SINGLE_KEY.test(parts[parts.length - 1]) ? spelled.join('') : spelled.join(' ');
  }
  return parts.map(part => OTHER_WORDS[part] ?? part).join(' + ');
}

export function detectPlatform(): ShortcutPlatform {
  if (typeof navigator === 'undefined') return 'other';
  const data = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData;
  const name = data?.platform || navigator.platform || navigator.userAgent || '';
  return /mac|iphone|ipad|ipod/i.test(name) ? 'mac' : 'other';
}

const GROUP_LABELS: Record<ShortcutGroupId, () => string> = {
  view: () => t('视图'),
  select: () => t('选择'),
  edit: () => t('编辑'),
  run: () => t('运行'),
};

/** The help panel's table, grouped 视图 / 选择 / 编辑 / 运行, with keys spelled for the platform. */
export function shortcutGroups(platform: ShortcutPlatform = detectPlatform()): ShortcutGroup[] {
  return (Object.keys(GROUP_LABELS) as ShortcutGroupId[]).map(id => ({
    id,
    label: GROUP_LABELS[id](),
    items: SPECS.filter(spec => spec.group === id).map(spec => ({
      id: spec.id,
      keys: (typeof spec.keys === 'function' ? spec.keys() : spec.keys).map(combo => spellKeys(combo, platform)),
      what: spec.what(),
    })),
  }));
}
