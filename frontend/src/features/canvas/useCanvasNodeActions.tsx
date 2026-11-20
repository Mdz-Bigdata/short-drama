import { useCallback, useMemo, useState, type ReactNode, type RefObject } from 'react';
import { LayoutTemplate } from 'lucide-react';

import { t } from '../../i18n';
import { CanvasBatchConnectDialog } from './CanvasBatchConnectDialog';
import { CanvasCropDialog, CanvasGridSplitDialog } from './CanvasImageOpsDialogs';
import { batchSources, canBatchConnect, planBatchConnect, planBatchConnectNew, videoTargets, type VideoTarget } from './canvasBatchConnect';
import { savablePicture } from './canvasElementsApi';
import { CANVAS_MAX_EDGES, CANVAS_MAX_NODES } from './canvasGeometry';
import type { ImagePieces } from './canvasImageOpsApi';
import { nodeTitle } from './canvasLabels';
import type { MenuSpec } from './canvasMenus';
import {
  CONNECT_TO_VIDEO, TEMPLATE_FIRST_LAST, copyText, downloadFileName, downloadMedia, downloadableOutput, promptOf, withBatchConnect, withNodeActions, withTemplates,
  type Outputs,
} from './canvasNodeActions';
import { firstLastFrameTemplate } from './canvasTemplates';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

export interface NodeActionContext {
  world: { x: number; y: number };
  ids: ReadonlySet<string>;
  nodeId?: string;
}

interface Options {
  projectId: string;
  canvasId: string;
  currentDoc: () => CanvasDoc;
  /** What each node shows now, as the run history has it. */
  outputs: RefObject<Outputs>;
  edit: (change: (doc: CanvasDoc) => CanvasDoc, coalesce?: string | null) => void;
  flush: () => Promise<boolean>;
  currentVersion: () => number;
  /** Catch up with the stored canvas after the server added nodes to it. */
  reloadAndShow: () => Promise<void>;
  say: (message: string) => void;
  select: (nodes: ReadonlySet<string>, edges: ReadonlySet<string>) => void;
  /** The surface, for the world point at the middle of the view: where a toolbar action places things. */
  surface: RefObject<{ centre: () => { x: number; y: number } } | null>;
}

interface ImageTarget { nodeId: string; label: string; url: string }

const NO_EDGES: ReadonlySet<string> = new Set();

/**
 * The node actions the canvas gained after its editing basics, kept out of the workspace file: crop and
 * grid split (the server cuts, the canvas catches up), download, copy the prompt, the first/last-frame
 * template and "connect to a video node" (both one undoable document edit).
 *
 * The workspace asks three things of this: extend a menu, run a menu id, and render the dialogs.
 */
export function useCanvasNodeActions({ projectId, canvasId, currentDoc, outputs, edit, flush, currentVersion, reloadAndShow, say, select, surface }: Options) {
  const [cropping, setCropping] = useState<ImageTarget | null>(null);
  const [splitting, setSplitting] = useState<ImageTarget | null>(null);
  const [connecting, setConnecting] = useState<{ ids: string[]; targets: VideoTarget[] } | null>(null);

  const closeCrop = useCallback(() => setCropping(null), []);
  const closeSplit = useCallback(() => setSplitting(null), []);
  const closeConnect = useCallback(() => setConnecting(null), []);

  const prepare = useCallback(async () => {
    if (!await flush()) throw new Error(t('画布还没保存成功，先解决保存问题。'));
    return currentVersion();
  }, [currentVersion, flush]);

  const pictureOf = useCallback((nodeId: string): ImageTarget | null => {
    const doc = currentDoc();
    const node = doc.nodes.find(item => item.id === nodeId);
    const picture = savablePicture(node, doc, outputs.current ?? {});
    return node && picture ? { nodeId, label: nodeTitle(node), url: picture.url } : null;
  }, [currentDoc, outputs]);

  const openCrop = useCallback((nodeId: string) => {
    const target = pictureOf(nodeId);
    if (target) setCropping(target);
    else say(t('这个节点还没有图片，裁不了。'));
  }, [pictureOf, say]);

  const openSplit = useCallback((nodeId: string) => {
    const target = pictureOf(nodeId);
    if (target) setSplitting(target);
    else say(t('这个节点还没有图片，拆不了。'));
  }, [pictureOf, say]);

  const onCropped = useCallback(async (result: ImagePieces) => {
    await reloadAndShow();
    select(new Set(result.node_ids), NO_EDGES);
    say(t('已裁剪为新的素材节点。'));
  }, [reloadAndShow, say, select]);

  const onSplit = useCallback(async (result: ImagePieces) => {
    await reloadAndShow();
    select(new Set(result.node_ids), NO_EDGES);
    say(t('已拆成 {0} 个素材节点。', [result.node_ids.length]));
  }, [reloadAndShow, say, select]);

  const download = useCallback((nodeId: string) => {
    const doc = currentDoc();
    const node = doc.nodes.find(item => item.id === nodeId);
    const output = downloadableOutput(node, doc, outputs.current ?? {});
    if (!node || !output) {
      say(t('这个节点还没有可以下载的内容。'));
      return;
    }
    const name = downloadFileName(node, output);
    downloadMedia(output.url, name)
      .then(how => say(how === 'saved' ? t('已下载：{0}', [name]) : t('浏览器不让直接保存这个文件，已在新标签页打开。')))
      .catch(() => say(t('下载失败')));
  }, [currentDoc, outputs, say]);

  const copyPrompt = useCallback((nodeId: string) => {
    const prompt = promptOf(currentDoc().nodes.find(item => item.id === nodeId));
    if (!prompt) {
      say(t('这个节点没有提示词。'));
      return;
    }
    void copyText(prompt).then(done => say(done ? t('提示词已复制。') : t('复制失败：浏览器没有给剪贴板权限。')));
  }, [currentDoc, say]);

  const addTemplate = useCallback((at?: { x: number; y: number }) => {
    const made = firstLastFrameTemplate(currentDoc(), at ?? surface.current?.centre() ?? { x: 0, y: 0 }, { group: t('首尾帧生视频'), first: t('首帧'), last: t('尾帧') });
    if (!made.ok) {
      say(made.reason === 'limit' ? t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]) : t('模板放不上去：连接规则不允许。'));
      return;
    }
    // One edit, so one undo takes the whole template back.
    edit(() => made.doc);
    select(new Set([made.groupId]), NO_EDGES);
  }, [currentDoc, edit, say, select, surface]);

  const openConnect = useCallback((ids: ReadonlySet<string>) => {
    const doc = currentDoc();
    const sources = batchSources(doc, ids);
    if (sources.length < 2) {
      say(t('至少选中两个图片或视频节点。'));
      return;
    }
    setConnecting({ ids: sources.map(node => node.id), targets: videoTargets(doc) });
  }, [currentDoc, say]);

  const confirmConnect = useCallback((targetId: string | null) => {
    const picked = connecting;
    setConnecting(null);
    if (!picked) return;
    const doc = currentDoc();
    const plan = targetId ? planBatchConnect(doc, picked.ids, targetId) : planBatchConnectNew(doc, picked.ids);
    if (!plan) {
      say(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
      return;
    }
    // Nothing connected and nothing made: the document is left alone, and so is the undo stack.
    if (plan.connected.length) {
      edit(() => plan.doc);
      select(new Set([plan.targetId]), NO_EDGES);
    }
    say(t('已连接 {0} 条，跳过 {1} 条', [plan.connected.length, plan.skipped.length]));
  }, [connecting, currentDoc, edit, say, select]);

  /** Runs a menu id this hook owns; false when the id is somebody else's. */
  const run = useCallback((id: string, context: NodeActionContext): boolean => {
    switch (id) {
      case 'crop': if (context.nodeId) openCrop(context.nodeId); return true;
      case 'grid-split': if (context.nodeId) openSplit(context.nodeId); return true;
      case 'download': if (context.nodeId) download(context.nodeId); return true;
      case 'copy-prompt': if (context.nodeId) copyPrompt(context.nodeId); return true;
      case TEMPLATE_FIRST_LAST: addTemplate(context.world); return true;
      case CONNECT_TO_VIDEO: openConnect(context.ids); return true;
      default: return false;
    }
  }, [addTemplate, copyPrompt, download, openConnect, openCrop, openSplit]);

  /** A node's menu (or, with several selected, the selection's) with the actions this node or selection has earned. */
  const nodeMenu = useCallback((spec: MenuSpec[], node: CanvasNode, ids: ReadonlySet<string>): MenuSpec[] => {
    const doc = currentDoc();
    if (ids.size >= 2) return withBatchConnect(spec, canBatchConnect(doc, ids));
    const shown = outputs.current ?? {};
    return withNodeActions(spec, {
      hasPicture: Boolean(savablePicture(node, doc, shown)), hasMedia: Boolean(downloadableOutput(node, doc, shown)), hasPrompt: Boolean(promptOf(node)),
    });
  }, [currentDoc, outputs]);

  const paneMenu = useCallback((spec: MenuSpec[]): MenuSpec[] => withTemplates(spec), []);

  /** For the floating selection toolbar: the action when this selection can be batch-connected, else undefined. */
  const connectAction = useCallback((ids: ReadonlySet<string>) => (canBatchConnect(currentDoc(), ids) ? () => openConnect(ids) : undefined), [currentDoc, openConnect]);

  /** The same actions as buttons, for the inspector's action row. */
  const inspectorActions = useCallback((node: CanvasNode, doc: CanvasDoc, shown: Outputs): ReactNode => {
    const picture = Boolean(savablePicture(node, doc, shown));
    const media = Boolean(downloadableOutput(node, doc, shown));
    const prompt = Boolean(promptOf(node));
    if (!picture && !media && !prompt) return null;
    return (
      <>
        {picture && <button type="button" className="cn-button" onClick={() => openCrop(node.id)}>{t('裁剪')}</button>}
        {picture && <button type="button" className="cn-button" onClick={() => openSplit(node.id)}>{t('宫格拆分')}</button>}
        {media && <button type="button" className="cn-button" onClick={() => download(node.id)}>{t('下载')}</button>}
        {prompt && <button type="button" className="cn-button" onClick={() => copyPrompt(node.id)}>{t('复制提示词')}</button>}
      </>
    );
  }, [copyPrompt, download, openCrop, openSplit]);

  const toolbar = useMemo(() => (
    <button type="button" className="cn-icon" onClick={() => addTemplate()} aria-label={t('模板：首尾帧生视频')} title={t('模板：首尾帧生视频')}>
      <LayoutTemplate aria-hidden="true" />
    </button>
  ), [addTemplate]);

  const dialogs = (
    <>
      {cropping && (
        <CanvasCropDialog
          projectId={projectId} canvasId={canvasId} nodeId={cropping.nodeId} nodeLabel={cropping.label} imageUrl={cropping.url}
          prepare={prepare} onApplied={onCropped} onClose={closeCrop}
        />
      )}
      {splitting && (
        <CanvasGridSplitDialog
          projectId={projectId} canvasId={canvasId} nodeId={splitting.nodeId} nodeLabel={splitting.label} imageUrl={splitting.url}
          prepare={prepare} onApplied={onSplit} onClose={closeSplit}
        />
      )}
      {connecting && <CanvasBatchConnectDialog count={connecting.ids.length} targets={connecting.targets} onConfirm={confirmConnect} onClose={closeConnect} />}
    </>
  );

  return {
    /** A dialog of this hook is open: the canvas's own shortcuts yield. */
    modal: Boolean(cropping || splitting || connecting),
    dialogs, toolbar, run, nodeMenu, paneMenu, connectAction, inspectorActions, addTemplate,
  };
}
