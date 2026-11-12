import { describe, expect, it, vi } from 'vitest';

import {
  bindMenu, canvasMenu, clampMenuPosition, edgeMenu, isSubmenu, menuIds, nodeMenu, selectionMenu, shortcutLabel, submenuPosition, tidy,
  type MenuAction, type MenuSpec,
} from './canvasMenus';
import type { CanvasNode } from './canvasTypes';

const node = (kind: CanvasNode['kind'], payload: CanvasNode['payload'] = {}): CanvasNode => ({
  id: 'n', kind, track: 'freezone', x: 0, y: 0, width: 100, height: 100, artifact_id: null, payload,
});

function find(spec: readonly MenuSpec[], id: string): MenuSpec | null {
  for (const item of spec) {
    if (item === 'separator') continue;
    if (isSubmenu(item)) {
      const inner = find(item.submenu, id);
      if (inner) return inner;
    } else if (item.id === id) return item;
  }
  return null;
}

describe('menu builders', () => {
  it('offers adding, paste and the view on empty canvas', () => {
    const spec = canvasMenu({ canPaste: false, addKinds: ['image_gen', 'note'], mac: true });
    expect(menuIds(spec)).toEqual(['add:image_gen', 'add:note', 'paste', 'select-all', 'fit-view']);
    expect(find(spec, 'paste')).toMatchObject({ label: '粘贴', shortcut: '⌘V', disabled: true });
    expect((spec[0] as { submenu: Array<{ label: string }> }).submenu.map(item => item.label)).toEqual(['图像生成', '文本注释']);
    const withHistory = canvasMenu({ canPaste: true, addKinds: [], canUndo: true, canRedo: false, mac: false });
    expect(menuIds(withHistory)).toEqual(['paste', 'select-all', 'fit-view', 'undo', 'redo']);
    expect(withHistory[0]).not.toBe('separator');
    expect(find(withHistory, 'redo')).toMatchObject({ shortcut: 'Ctrl+Shift+Z', disabled: true });
  });

  it('offers run only on runnable nodes and the group actions only on groups', () => {
    expect(menuIds(nodeMenu({ node: node('image_gen'), selectionCount: 1, canRun: false }))).toEqual(['run', 'rename', 'copy', 'duplicate', 'delete']);
    expect(find(nodeMenu({ node: node('image_gen'), selectionCount: 1, canRun: false }), 'run')).toMatchObject({ disabled: true });
    expect(menuIds(nodeMenu({ node: node('note'), selectionCount: 0 }))).toEqual(['rename', 'copy', 'duplicate', 'delete']);
    const groupSpec = nodeMenu({ node: node('group'), selectionCount: 1 });
    expect(menuIds(groupSpec)).toEqual(['rename', 'toggle-collapse', 'fit-group', 'ungroup', 'copy', 'duplicate', 'delete']);
    expect(find(groupSpec, 'toggle-collapse')).toMatchObject({ label: '折叠分组' });
    expect(find(nodeMenu({ node: node('group', { collapsed: true }), selectionCount: 1 }), 'toggle-collapse')).toMatchObject({ label: '展开分组' });
    expect(find(groupSpec, 'delete')).toMatchObject({ danger: true });
  });

  it('gives the selection menu for a multi-selection', () => {
    const spec = nodeMenu({ node: node('note'), selectionCount: 2, canRun: true });
    expect(menuIds(spec)).toEqual(menuIds(selectionMenu({ count: 2, canRun: true })));
    expect(menuIds(spec)).toContain('align:left');
    expect(menuIds(spec)).toContain('arrange:edges');
    expect(find(spec, 'distribute:horizontal')).toMatchObject({ disabled: true });
    expect(find(selectionMenu({ count: 3 }), 'distribute:horizontal')).toMatchObject({ disabled: false });
    expect(menuIds(selectionMenu({ count: 2 }))).not.toContain('ungroup');
    expect(menuIds(selectionMenu({ count: 2, hasGroup: true }))).toContain('ungroup');
    expect(menuIds(selectionMenu({ count: 2 }))[0]).toBe('align:left');
  });

  it('offers edge actions', () => {
    expect(menuIds(edgeMenu({ edge: { id: 'e', source: 'a', target: 'b', kind: 'reference', payload: {} } }))).toEqual(['select-source', 'select-target', 'delete-edge']);
  });

  it('binds every id to one handler, submenus included', () => {
    const onSelect = vi.fn();
    const items = bindMenu(canvasMenu({ canPaste: true, addKinds: ['note'] }), onSelect);
    const add = items[0] as { submenu: MenuAction[] };
    add.submenu[0].onSelect();
    (items.find(item => item !== 'separator' && !isSubmenu(item) && item.id === 'paste') as MenuAction).onSelect();
    expect(onSelect.mock.calls).toEqual([['add:note'], ['paste']]);
  });

  it('drops leading, trailing and doubled separators', () => {
    expect(tidy<MenuSpec>(['separator', { id: 'a', label: 'a' }, 'separator', 'separator', { id: 'b', label: 'b' }, 'separator'])).toEqual([
      { id: 'a', label: 'a' }, 'separator', { id: 'b', label: 'b' },
    ]);
  });
});

describe('menu placement and shortcuts', () => {
  it('clamps a menu inside the viewport', () => {
    expect(clampMenuPosition(100, 100, 200, 300, 1000, 800)).toEqual({ x: 100, y: 100 });
    expect(clampMenuPosition(950, 700, 200, 300, 1000, 800)).toEqual({ x: 792, y: 492 });
    expect(clampMenuPosition(-20, -20, 200, 300, 1000, 800)).toEqual({ x: 8, y: 8 });
  });

  it('opens a submenu right of its item, or left when there is no room', () => {
    expect(submenuPosition({ left: 100, right: 300, top: 50 }, 200, 100, 1000, 800)).toEqual({ x: 302, y: 46 });
    expect(submenuPosition({ left: 700, right: 900, top: 50 }, 200, 100, 1000, 800)).toEqual({ x: 498, y: 46 });
  });

  it('writes shortcuts for the platform', () => {
    expect(shortcutLabel('mod+shift+g', true)).toBe('⇧⌘G');
    expect(shortcutLabel('mod+shift+g', false)).toBe('Ctrl+Shift+G');
    expect(shortcutLabel('mod+c', false)).toBe('Ctrl+C');
  });
});
