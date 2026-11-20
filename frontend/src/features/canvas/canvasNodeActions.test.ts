// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { canvasMenu, menuIds, nodeMenu, selectionMenu, type MenuSpec } from './canvasMenus';
import {
  copyText, downloadFileName, downloadMedia, downloadableOutput, mediaExtension, nodeActionItems, promptOf, safeFileStem, withBatchConnect, withNodeActions, withTemplates,
} from './canvasNodeActions';
import type { CanvasDoc, CanvasNode, NodeKind, NodeOutput, NodePayload } from './canvasTypes';

const node = (kind: NodeKind, payload: NodePayload = {}, id = 'n'): CanvasNode => ({
  id, kind, track: 'freezone', x: 0, y: 0, width: 100, height: 100, artifact_id: null, payload,
});
const image = (url: string): NodeOutput => ({ medium: 'image', url });

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('a download\'s file name', () => {
  it('is the node\'s label and the file\'s own extension', () => {
    expect(downloadFileName(node('media', { label: '雨街全景' }), image('/media/canvas_abc.jpg'))).toBe('雨街全景.jpg');
    expect(downloadFileName(node('video_gen', { label: '镜头 3' }), { medium: 'video', url: 'https://cdn.example.com/a/b/clip.webm?sig=1#t=2' })).toBe('镜头 3.webm');
    expect(downloadFileName(node('audio_gen', { title: '配音' }), { medium: 'audio', url: '/media/x.wav' })).toBe('配音.wav');
  });

  it('falls back to the medium\'s usual extension when the address has none it knows', () => {
    expect(mediaExtension('/media/blob', 'image')).toBe('png');
    expect(mediaExtension('https://cdn.example.com/get?id=7', 'video')).toBe('mp4');
    expect(mediaExtension('/media/x.exe', 'audio')).toBe('mp3');
    // A clip's address ending in .png is not a clip's extension.
    expect(mediaExtension('/media/x.png', 'video')).toBe('mp4');
    expect(mediaExtension('data:image/jpeg;base64,AAAA', 'image')).toBe('jpg');
    expect(mediaExtension('/media/UPPER.PNG', 'image')).toBe('png');
  });

  it('uses the kind\'s name for a node with no label, and never doubles an extension', () => {
    expect(downloadFileName(node('image_gen'), image('/media/a.png'))).toBe('图像生成.png');
    expect(downloadFileName(node('media', { label: 'board.png' }), image('/media/canvas_1.png'))).toBe('board.png');
    expect(downloadFileName(node('media', { label: 'photo.JPG' }), image('/media/canvas_1.webp'))).toBe('photo.webp');
  });

  it('carries nothing a file system refuses', () => {
    expect(safeFileStem('  a/b\\c:d*e?f"g<h>i|j \n k  ')).toBe('a b c d e f g h i j k');
    expect(safeFileStem('...隐藏. ')).toBe('隐藏');
    expect(safeFileStem('长'.repeat(300))).toHaveLength(80);
    expect(downloadFileName(node('media', { label: '///' }), image('/media/a.png'))).toBe('上传素材.png');
  });
});

describe('what a node has to act on', () => {
  const doc: CanvasDoc = { nodes: [], edges: [] };

  it('finds the media a node shows: its active generation first, else the file it holds', () => {
    const held = node('media', { output: image('/media/held.png') });
    expect(downloadableOutput(held, doc, {})?.url).toBe('/media/held.png');
    expect(downloadableOutput(held, doc, { n: { medium: 'video', url: '/media/run.mp4' } })).toMatchObject({ medium: 'video', url: '/media/run.mp4' });
    expect(downloadableOutput(node('image_gen'), doc, {})).toBeNull();
    expect(downloadableOutput(node('tool'), doc, { n: { medium: 'text', url: '', text: '写好的词' } })).toBeNull();
    expect(downloadableOutput(node('note', { output: image('/media/a.png') }), doc, {})).toBeNull();
    expect(downloadableOutput(undefined, doc, {})).toBeNull();
  });

  it('finds the prompt worth copying', () => {
    expect(promptOf(node('image_gen', { prompt: '  雨夜的街  ' }))).toBe('雨夜的街');
    expect(promptOf(node('image_gen', { prompt: '   ' }))).toBe('');
    expect(promptOf(node('note', { text: '不是提示词' }))).toBe('');
    expect(promptOf(undefined)).toBe('');
  });
});

describe('the menus', () => {
  it('a node\'s menu gains only what the node has earned, above delete', () => {
    const base = nodeMenu({ node: node('image_gen', { prompt: '雨夜' }), selectionCount: 1, canRun: true, canSaveElement: true });
    const full = withNodeActions(base, { hasPicture: true, hasMedia: true, hasPrompt: true });
    expect(menuIds(full)).toEqual(['run', 'rename', 'copy', 'duplicate', 'save-element', 'crop', 'grid-split', 'download', 'copy-prompt', 'delete']);
    // In a section of their own, and delete still closes the menu.
    const at = full.findIndex(item => item !== 'separator' && item.id === 'crop');
    expect(full[at - 1]).toBe('separator');
    expect(full.slice(-2)).toEqual(['separator', expect.objectContaining({ id: 'delete' })]);
    expect(full.some((item, index) => item === 'separator' && full[index + 1] === 'separator')).toBe(false);

    expect(menuIds(withNodeActions(base, { hasPicture: false, hasMedia: true, hasPrompt: false }))).toEqual(['run', 'rename', 'copy', 'duplicate', 'save-element', 'download', 'delete']);
    expect(withNodeActions(base, { hasPicture: false, hasMedia: false, hasPrompt: false })).toEqual(base);
    expect(nodeActionItems({ hasPicture: true, hasMedia: false, hasPrompt: true }).map(item => (item as { label: string }).label)).toEqual(['裁剪', '宫格拆分', '复制提示词']);
  });

  it('a multi-selection\'s menu gains 连到视频节点… only when it can be connected', () => {
    const base = selectionMenu({ count: 3, canRun: true, hasGroup: false, mac: true });
    const offered = withBatchConnect(base, true);
    expect(menuIds(offered)).toContain('connect-to-video');
    const ids = offered.map(item => (item === 'separator' ? '|' : item.id));
    expect(ids.indexOf('connect-to-video')).toBe(ids.indexOf('group') + 1);
    expect(withBatchConnect(base, false)).toEqual(base);
    const withGroup = withBatchConnect(selectionMenu({ count: 2, hasGroup: true }), true).map(item => (item === 'separator' ? '|' : item.id));
    expect(withGroup.indexOf('connect-to-video')).toBe(withGroup.indexOf('ungroup') + 1);
  });

  it('the empty-canvas menu gains a 模板 submenu after 添加节点', () => {
    const spec = withTemplates(canvasMenu({ canPaste: true, addKinds: ['image_gen', 'note'], canUndo: false, canRedo: false }));
    expect(menuIds(spec)).toEqual(['add:image_gen', 'add:note', 'template:first-last', 'paste', 'select-all', 'fit-view', 'undo', 'redo']);
    const [add, template] = spec as Array<Extract<MenuSpec, { submenu: unknown }>>;
    expect([add.label, template.label]).toEqual(['添加节点', '模板']);
    expect(template.submenu).toEqual([{ id: 'template:first-last', label: '首尾帧生视频' }]);
    // With no kinds to add the submenu still comes first.
    expect(menuIds(withTemplates(canvasMenu({ canPaste: true, addKinds: [] })))[0]).toBe('template:first-last');
  });
});

describe('downloading', () => {
  function watchLinks() {
    const clicked: Array<{ href: string; download: string; target: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) {
      clicked.push({ href: this.getAttribute('href') ?? '', download: this.download, target: this.target });
    });
    return clicked;
  }

  it('fetches the file from the API origin with the session and saves the blob under the name', async () => {
    const clicked = watchLinks();
    const fetched = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['png']) } as Response);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:made'), revokeObjectURL: vi.fn() }));

    expect(await downloadMedia('/media/canvas_a.png', '雨街.png')).toBe('saved');
    expect(fetched).toHaveBeenCalledWith('http://localhost:8000/media/canvas_a.png', { credentials: 'include' });
    expect(clicked).toEqual([{ href: 'blob:made', download: '雨街.png', target: '' }]);
    expect(document.querySelector('a')).toBeNull();
  });

  it('never sends the session to somebody else\'s host', async () => {
    watchLinks();
    const fetched = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['mp4']) } as Response);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:made'), revokeObjectURL: vi.fn() }));
    await downloadMedia('https://cdn.example.com/clip.mp4', 'clip.mp4');
    expect(fetched).toHaveBeenCalledWith('https://cdn.example.com/clip.mp4', { credentials: 'omit' });
    await downloadMedia('http://localhost:8000/media/clip.mp4', 'clip.mp4');
    expect(fetched).toHaveBeenLastCalledWith('http://localhost:8000/media/clip.mp4', { credentials: 'include' });
  });

  it('opens the address with a download hint when the fetch is not allowed', async () => {
    const clicked = watchLinks();
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await downloadMedia('https://cdn.example.com/clip.mp4', '镜头.mp4')).toBe('opened');
    expect(clicked).toEqual([{ href: 'https://cdn.example.com/clip.mp4', download: '镜头.mp4', target: '_blank' }]);

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, status: 403 } as Response);
    expect(await downloadMedia('/media/gone.png', 'gone.png')).toBe('opened');
    expect(clicked[1]).toEqual({ href: 'http://localhost:8000/media/gone.png', download: 'gone.png', target: '_blank' });
  });
});

describe('copying', () => {
  it('writes to the clipboard, and says when it could not', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    expect(await copyText('雨夜的街')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('雨夜的街');

    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => { throw new Error('denied'); }) } });
    // jsdom has no execCommand: the older way fails too, and that is reported rather than thrown.
    expect(await copyText('雨夜的街')).toBe(false);
    expect(document.querySelector('textarea')).toBeNull();
  });
});
