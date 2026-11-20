import { describe, expect, it } from 'vitest';

import { shortcutGroups, spellKeys } from './canvasShortcutsHelp';

describe('spellKeys', () => {
  it('spells modifiers per platform', () => {
    expect(spellKeys('Mod + Shift + Z', 'mac')).toBe('⌘⇧Z');
    expect(spellKeys('Mod + Shift + Z', 'other')).toBe('Ctrl + Shift + Z');
    expect(spellKeys('Mod + +', 'mac')).toBe('⌘+');
    expect(spellKeys('Shift + 1 … 9', 'mac')).toBe('⇧ 1 … 9');
    expect(spellKeys('Shift + 点击或框选', 'mac')).toBe('⇧ 点击或框选');
    expect(spellKeys('Shift + 点击或框选', 'other')).toBe('Shift + 点击或框选');
    expect(spellKeys('空格 + 拖动', 'mac')).toBe('空格 + 拖动');
    expect(spellKeys('F', 'mac')).toBe('F');
  });
});

describe('shortcutGroups', () => {
  it('groups the table as 视图 / 选择 / 编辑 / 运行', () => {
    expect(shortcutGroups('mac').map(group => group.label)).toEqual(['视图', '选择', '编辑', '运行']);
    for (const group of shortcutGroups('other')) expect(group.items.length).toBeGreaterThan(0);
  });

  it('keeps every existing shortcut and lists the new ones', () => {
    const items = shortcutGroups('other').flatMap(group => group.items);
    const byId = new Map(items.map(item => [item.id, item]));
    expect(new Set(items.map(item => item.id)).size).toBe(items.length);
    for (const id of ['undo', 'redo', 'copy', 'cut', 'paste', 'duplicate', 'select-all', 'group', 'ungroup', 'delete', 'select-add', 'pan', 'wheel-zoom', 'no-snap',
      'fit', 'bookmark-jump', 'bookmark-save', 'nudge', 'save', 'deselect', 'help', 'enlarge', 'play-large', 'open-shot']) {
      expect(byId.has(id), id).toBe(true);
    }
    expect(byId.get('zoom-in')!.keys).toEqual(['Ctrl + +']);
    expect(byId.get('zoom-reset')!.keys).toEqual(['Ctrl + 0']);
    expect(byId.get('fit-all')!.keys).toEqual(['Ctrl + 1']);
    expect(byId.get('fit-selection')!.keys).toEqual(['Ctrl + 2']);
    expect(byId.get('search')!.keys).toEqual(['Ctrl + F']);
    expect(byId.get('redo')!.keys).toEqual(['Ctrl + Shift + Z', 'Ctrl + Y']);
    expect(byId.has('context-menu') && byId.has('align')).toBe(true);
    const mac = new Map(shortcutGroups('mac').flatMap(group => group.items).map(item => [item.id, item]));
    expect(mac.get('search')!.keys).toEqual(['⌘F']);
    expect(mac.get('ungroup')!.keys).toEqual(['⌘⇧G']);
  });
});
