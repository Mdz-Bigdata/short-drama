// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/components/canvas/canvas-context-menu.tsx.
import { t } from '../../i18n';
import { RUNNABLE_KINDS } from './canvasGraph';
import { kindLabel } from './canvasLabels';
import type { CanvasEdge, CanvasNode, NodeKind } from './canvasTypes';

// ---------------------------------------------------------------- what a menu holds

export interface MenuAction {
  id: string;
  label: string;
  shortcut?: string;
  disabled?: boolean;
  danger?: boolean;
  onSelect: () => void;
}

export interface MenuSubmenu {
  id?: string;
  label: string;
  disabled?: boolean;
  submenu: MenuItem[];
}

export type MenuItem = MenuAction | 'separator' | MenuSubmenu;

/** A menu as the builders describe it: ids only, the integration maps each id to an action. */
export type MenuSpecAction = Omit<MenuAction, 'onSelect'>;
export interface MenuSpecSubmenu {
  id?: string;
  label: string;
  disabled?: boolean;
  submenu: MenuSpec[];
}
export type MenuSpec = MenuSpecAction | 'separator' | MenuSpecSubmenu;

export function isSubmenu<T extends MenuItem | MenuSpec>(item: T): item is Extract<T, { submenu: unknown }> {
  return typeof item === 'object' && 'submenu' in item;
}

/** Attach one handler to every action id in a described menu. */
export function bindMenu(spec: readonly MenuSpec[], onSelect: (id: string) => void): MenuItem[] {
  return spec.map(item => {
    if (item === 'separator') return item;
    if (isSubmenu(item)) return { ...item, submenu: bindMenu(item.submenu, onSelect) };
    return { ...item, onSelect: () => onSelect(item.id) };
  });
}

/** Every action id in a described menu, submenus included: what the integration has to handle. */
export function menuIds(spec: readonly MenuSpec[]): string[] {
  return spec.flatMap(item => (item === 'separator' ? [] : isSubmenu(item) ? menuIds(item.submenu) : [item.id]));
}

/** Separators only between items: none leading, trailing or doubled after items were left out. */
export function tidy<T extends MenuItem | MenuSpec>(items: readonly T[]): T[] {
  const out: T[] = [];
  for (const item of items) {
    if (item === 'separator' && (!out.length || out[out.length - 1] === 'separator')) continue;
    out.push(item);
  }
  while (out.length && out[out.length - 1] === 'separator') out.pop();
  return out;
}

// ---------------------------------------------------------------- where a menu goes

export const MENU_MARGIN = 8;

/** Keep a menu of this size wholly inside the viewport, preferring to open at (x, y). */
export function clampMenuPosition(x: number, y: number, width: number, height: number, viewWidth: number, viewHeight: number, margin = MENU_MARGIN) {
  return {
    x: Math.max(margin, Math.min(x, viewWidth - width - margin)),
    y: Math.max(margin, Math.min(y, viewHeight - height - margin)),
  };
}

/** A submenu opens to the right of its item, or to the left when the right has no room. */
export function submenuPosition(anchor: { left: number; right: number; top: number }, width: number, height: number, viewWidth: number, viewHeight: number, margin = MENU_MARGIN) {
  const right = anchor.right + 2;
  const x = right + width + margin <= viewWidth ? right : anchor.left - width - 2;
  return clampMenuPosition(x, anchor.top - 4, width, height, viewWidth, viewHeight, margin);
}

// ---------------------------------------------------------------- shortcuts

export function isMac() {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
}

/** `mod+shift+g` as ⇧⌘G on a Mac and Ctrl+Shift+G elsewhere. */
export function shortcutLabel(keys: string, mac = isMac()) {
  const parts = keys.split('+');
  const key = parts.pop()!.toUpperCase();
  const shift = parts.includes('shift');
  const mod = parts.includes('mod');
  if (mac) return `${shift ? '⇧' : ''}${mod ? '⌘' : ''}${key}`;
  return [mod ? 'Ctrl' : '', shift ? 'Shift' : '', key].filter(Boolean).join('+');
}

// ---------------------------------------------------------------- the canvas menus

export interface CanvasMenuOptions {
  canPaste: boolean;
  /** Kinds the 添加节点 submenu offers; each item's id is `add:<kind>`. */
  addKinds: readonly NodeKind[];
  canUndo?: boolean;
  canRedo?: boolean;
  mac?: boolean;
}

/** Right-click on empty canvas. Ids: add:<kind>, paste, select-all, fit-view, undo, redo. */
export function canvasMenu({ canPaste, addKinds, canUndo, canRedo, mac }: CanvasMenuOptions): MenuSpec[] {
  return tidy<MenuSpec>([
    ...(addKinds.length ? [{ id: 'add', label: t('添加节点'), submenu: addKinds.map(kind => ({ id: `add:${kind}`, label: kindLabel(kind) })) }] : []),
    'separator',
    { id: 'paste', label: t('粘贴'), shortcut: shortcutLabel('mod+v', mac), disabled: !canPaste },
    { id: 'select-all', label: t('全选'), shortcut: shortcutLabel('mod+a', mac) },
    { id: 'fit-view', label: t('显示全部') },
    ...(canUndo !== undefined || canRedo !== undefined ? ['separator' as const,
      { id: 'undo', label: t('撤销'), shortcut: shortcutLabel('mod+z', mac), disabled: !canUndo },
      { id: 'redo', label: t('重做'), shortcut: shortcutLabel('mod+shift+z', mac), disabled: !canRedo },
    ] : []),
  ]);
}

export interface SelectionMenuOptions {
  count: number;
  canRun?: boolean;
  /** The selection holds a group: offer 解组. */
  hasGroup?: boolean;
  mac?: boolean;
}

/**
 * Right-click on a multi-selection. Ids: run-selection, align:<left|hcenter|right|top|vcenter|bottom>,
 * distribute:<horizontal|vertical>, arrange:<row|column|grid|edges|spread>, group, ungroup, copy, duplicate, delete.
 */
export function selectionMenu({ count, canRun, hasGroup, mac }: SelectionMenuOptions): MenuSpec[] {
  return tidy<MenuSpec>([
    ...(canRun !== undefined ? [{ id: 'run-selection', label: t('运行所选'), disabled: !canRun }, 'separator' as const] : []),
    {
      id: 'align', label: t('对齐'), submenu: [
        { id: 'align:left', label: t('左对齐') },
        { id: 'align:hcenter', label: t('水平居中') },
        { id: 'align:right', label: t('右对齐') },
        'separator',
        { id: 'align:top', label: t('顶对齐') },
        { id: 'align:vcenter', label: t('垂直居中') },
        { id: 'align:bottom', label: t('底对齐') },
        'separator',
        { id: 'distribute:horizontal', label: t('水平等距'), disabled: count < 3 },
        { id: 'distribute:vertical', label: t('垂直等距'), disabled: count < 3 },
      ],
    },
    {
      id: 'arrange', label: t('排列'), submenu: [
        { id: 'arrange:row', label: t('横向排列') },
        { id: 'arrange:column', label: t('纵向排列') },
        { id: 'arrange:grid', label: t('宫格排列') },
        { id: 'arrange:edges', label: t('按连线整理') },
        { id: 'arrange:spread', label: t('散开重叠') },
      ],
    },
    { id: 'group', label: t('成组'), shortcut: shortcutLabel('mod+g', mac) },
    ...(hasGroup ? [{ id: 'ungroup', label: t('解组'), shortcut: shortcutLabel('mod+shift+g', mac) }] : []),
    'separator',
    { id: 'copy', label: t('复制'), shortcut: shortcutLabel('mod+c', mac) },
    { id: 'duplicate', label: t('就地复制'), shortcut: shortcutLabel('mod+d', mac) },
    { id: 'delete', label: t('删除所选'), shortcut: 'Delete', danger: true },
  ]);
}

export interface NodeMenuOptions {
  node: CanvasNode;
  /** How many nodes are selected; two or more (with this one among them) gives the selection menu. */
  selectionCount: number;
  canRun?: boolean;
  mac?: boolean;
}

/**
 * Right-click on a node. Ids: run, rename, toggle-collapse, fit-group, ungroup, copy, duplicate, delete;
 * with a multi-selection, those of selectionMenu.
 */
export function nodeMenu({ node, selectionCount, canRun, mac }: NodeMenuOptions): MenuSpec[] {
  if (selectionCount >= 2) return selectionMenu({ count: selectionCount, canRun, hasGroup: node.kind === 'group', mac });
  const group = node.kind === 'group';
  return tidy<MenuSpec>([
    ...(RUNNABLE_KINDS.has(node.kind) ? [{ id: 'run', label: t('运行'), disabled: canRun === false }] : []),
    { id: 'rename', label: t('重命名') },
    ...(group ? [
      { id: 'toggle-collapse', label: node.payload.collapsed ? t('展开分组') : t('折叠分组') },
      { id: 'fit-group', label: t('贴合内容'), disabled: Boolean(node.payload.collapsed) },
      { id: 'ungroup', label: t('解组'), shortcut: shortcutLabel('mod+shift+g', mac) },
    ] : []),
    'separator',
    { id: 'copy', label: t('复制'), shortcut: shortcutLabel('mod+c', mac) },
    { id: 'duplicate', label: t('就地复制'), shortcut: shortcutLabel('mod+d', mac) },
    'separator',
    { id: 'delete', label: t('删除'), shortcut: 'Delete', danger: true },
  ]);
}

export interface EdgeMenuOptions {
  edge: CanvasEdge;
}

/** Right-click on a connection. Ids: select-source, select-target, delete-edge. */
export function edgeMenu({ edge }: EdgeMenuOptions): MenuSpec[] {
  return [
    { id: 'select-source', label: t('选中上游'), disabled: !edge.source },
    { id: 'select-target', label: t('选中下游'), disabled: !edge.target },
    'separator',
    { id: 'delete-edge', label: t('删除连接'), danger: true },
  ];
}
