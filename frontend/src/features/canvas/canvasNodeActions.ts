// What a node's own menu offers beyond the editing basics: crop, grid split, download, copy the prompt;
// the template submenu of the empty-canvas menu; and "connect to a video node" for a multi-selection.
// Capabilities after NovaNova Studio's canvas (MIT); the menus, node model and wording are this project's own.
import { API_BASE, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { effectiveOutput } from './canvasGraph';
import { kindLabel } from './canvasLabels';
import { isSubmenu, tidy, type MenuSpec } from './canvasMenus';
import type { CanvasDoc, CanvasNode, Medium, NodeOutput } from './canvasTypes';

export type Outputs = Readonly<Record<string, NodeOutput>>;

// ---------------------------------------------------------------- what a node has to act on

/** The picture, clip or sound a node shows now (its active generation, else the file it holds); null when it has none. */
export function downloadableOutput(node: CanvasNode | undefined, doc: CanvasDoc, outputs: Outputs): (NodeOutput & { medium: Medium }) | null {
  if (!node || node.kind === 'group' || node.kind === 'note') return null;
  const output = effectiveOutput(node, doc, outputs);
  if (!output?.url || output.medium === 'text') return null;
  return output as NodeOutput & { medium: Medium };
}

/** The prompt a node carries, or '' when it has none worth copying. */
export function promptOf(node: CanvasNode | undefined): string {
  return typeof node?.payload.prompt === 'string' ? node.payload.prompt.trim() : '';
}

// ---------------------------------------------------------------- file names

const DEFAULT_EXTENSION: Record<Medium, string> = { image: 'png', video: 'mp4', audio: 'mp3' };
const KNOWN_EXTENSIONS: Record<Medium, readonly string[]> = {
  image: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'avif', 'bmp'],
  video: ['mp4', 'webm', 'mov', 'm4v', 'mkv', 'gif'],
  audio: ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'opus'],
};
const NAME_LIMIT = 80;

/** The extension a media address ends in when it is one this medium comes in, else the medium's usual one. */
export function mediaExtension(url: string, medium: Medium): string {
  const fromData = /^data:(image|video|audio)\/([a-z0-9.+-]+)/i.exec(url);
  const path = fromData ? '' : url.split(/[?#]/, 1)[0];
  const found = (fromData ? fromData[2].replace('jpeg', 'jpg').replace(/\+.*$/, '') : /\.([a-z0-9]{2,5})$/i.exec(path)?.[1] ?? '').toLowerCase();
  return KNOWN_EXTENSIONS[medium].includes(found) ? found : DEFAULT_EXTENSION[medium];
}

/** A label as a file name: nothing a file system refuses, no stray dots or spaces, not too long. */
export function safeFileStem(label: string): string {
  // eslint-disable-next-line no-control-regex -- control characters are exactly what a file name must not carry
  const cleaned = label.replace(/[\u0000-\u001f\u007f\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/^\.+|[. ]+$/g, '');
  return [...cleaned].slice(0, NAME_LIMIT).join('').trim();
}

/** `label.ext` for a node's file: the node's own title, or its kind when it has none; an extension already there is not doubled. */
export function downloadFileName(node: Pick<CanvasNode, 'kind' | 'payload'>, output: Pick<NodeOutput, 'url'> & { medium: Medium }): string {
  const extension = mediaExtension(output.url, output.medium);
  const label = String(node.payload.label || node.payload.title || '');
  const known = new RegExp(`\\.(${KNOWN_EXTENSIONS[output.medium].join('|')})$`, 'i');
  const stem = safeFileStem(label.replace(known, '')) || safeFileStem(kindLabel(node.kind)) || 'canvas';
  return `${stem}.${extension}`;
}

// ---------------------------------------------------------------- download and copy

function clickLink(href: string, filename: string, newTab: boolean) {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  if (newTab) {
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  }
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * Save a media file under `filename`. The file is fetched and handed over as a blob, so the name
 * holds even when the media is on another origin (the API base, a CDN that allows it). Where the
 * fetch is not allowed, the address is opened with a download hint instead: 'opened', not 'saved'.
 */
export async function downloadMedia(url: string, filename: string): Promise<'saved' | 'opened'> {
  const address = apiUrl(url);
  if (address.startsWith('data:')) {
    clickLink(address, filename, false);
    return 'saved';
  }
  // The session cookie goes only to this app's own backend, never to a provider's CDN.
  const relative = !/^[a-z][a-z\d+.-]*:/i.test(url) && !url.startsWith('//');
  const own = relative || (Boolean(API_BASE) && address.startsWith(`${API_BASE}/`));
  try {
    const response = await fetch(address, { credentials: own ? 'include' : 'omit' });
    if (!response.ok) throw new Error(String(response.status));
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    clickLink(href, filename, false);
    setTimeout(() => URL.revokeObjectURL(href), 0);
    return 'saved';
  } catch {
    clickLink(address, filename, true);
    return 'opened';
  }
}

/** Put text on the system clipboard; false when the browser will not allow it. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Falls through to the older way, which works without the permission.
  }
  const field = document.createElement('textarea');
  field.value = text;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.appendChild(field);
  try {
    field.select();
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    field.remove();
  }
}

// ---------------------------------------------------------------- menus

export const NODE_ACTION_IDS = ['crop', 'grid-split', 'download', 'copy-prompt'] as const;
export const TEMPLATE_FIRST_LAST = 'template:first-last';
export const CONNECT_TO_VIDEO = 'connect-to-video';

export interface NodeActionOptions {
  /** The node shows a picture: 裁剪 and 宫格拆分. */
  hasPicture: boolean;
  /** The node shows a picture, clip or sound: 下载. */
  hasMedia: boolean;
  /** The node carries a prompt: 复制提示词. */
  hasPrompt: boolean;
}

/** The items a single node's menu gains. Ids: crop, grid-split, download, copy-prompt. */
export function nodeActionItems({ hasPicture, hasMedia, hasPrompt }: NodeActionOptions): MenuSpec[] {
  return [
    ...(hasPicture ? [{ id: 'crop', label: t('裁剪') }, { id: 'grid-split', label: t('宫格拆分') }] : []),
    ...(hasMedia ? [{ id: 'download', label: t('下载') }] : []),
    ...(hasPrompt ? [{ id: 'copy-prompt', label: t('复制提示词') }] : []),
  ];
}

function idOf(item: MenuSpec) {
  return item === 'separator' ? '' : item.id ?? '';
}

/** Put `items` in a section of their own just above the menu's closing section (the one that deletes). */
function beforeDelete(spec: readonly MenuSpec[], items: readonly MenuSpec[]): MenuSpec[] {
  if (!items.length) return [...spec];
  const last = spec.findIndex(item => idOf(item) === 'delete');
  let at = last < 0 ? spec.length : last;
  while (at > 0 && spec[at - 1] !== 'separator') at -= 1;
  // `at` is the first item of the closing section (or the end): the new section goes in front of its separator.
  const cut = last < 0 ? spec.length : Math.max(0, at - 1);
  return tidy<MenuSpec>([...spec.slice(0, cut), 'separator', ...items, 'separator', ...spec.slice(cut)]);
}

/** A node's menu with the picture, download and prompt actions it has earned. */
export function withNodeActions(spec: readonly MenuSpec[], options: NodeActionOptions): MenuSpec[] {
  return beforeDelete(spec, nodeActionItems(options));
}

/** A multi-selection's menu with 连到视频节点… (id `connect-to-video`) right after 成组/解组. */
export function withBatchConnect(spec: readonly MenuSpec[], enabled: boolean): MenuSpec[] {
  if (!enabled) return [...spec];
  const item: MenuSpec = { id: CONNECT_TO_VIDEO, label: t('连到视频节点…') };
  const anchor = Math.max(spec.findIndex(entry => idOf(entry) === 'ungroup'), spec.findIndex(entry => idOf(entry) === 'group'));
  if (anchor < 0) return beforeDelete(spec, [item]);
  return [...spec.slice(0, anchor + 1), item, ...spec.slice(anchor + 1)];
}

/** The empty-canvas menu with a 模板 submenu (id `template`, items `template:<name>`) after 添加节点. */
export function withTemplates(spec: readonly MenuSpec[]): MenuSpec[] {
  const submenu: MenuSpec = { id: 'template', label: t('模板'), submenu: [{ id: TEMPLATE_FIRST_LAST, label: t('首尾帧生视频') }] };
  const add = spec.findIndex(item => item !== 'separator' && isSubmenu(item) && item.id === 'add');
  return [...spec.slice(0, add + 1), submenu, ...spec.slice(add + 1)];
}
