// Idea from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors): a canvas shared read-only by link.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Eye } from 'lucide-react';

import { ApiError, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { CanvasSurface, type NodeRenderProps, type SurfaceHandle } from '../canvas/CanvasSurface';
import { CanvasZoomControls } from '../canvas/CanvasZoomControls';
import { kindLabel } from '../canvas/canvasLabels';
import { fetchSharedCanvas, shareExpiryText, type SharedCanvas } from '../canvas/canvasShareApi';
import type { CanvasNode, NodeOutput, Viewport } from '../canvas/canvasTypes';
import '../canvas/CanvasWorkspace.css';
import './SharedCanvasPage.css';

type ShareOutput = SharedCanvas['outputs'][string];

type LoadState =
  | { phase: 'loading' }
  | { phase: 'ready'; canvas: SharedCanvas }
  | { phase: 'error'; kind: 'gone' | 'busy' | 'failed' };

const NO_IDS: ReadonlySet<string> = new Set();
const noop = () => undefined;
const never = () => false;
/** What a press may still use on its own inside a node: the media controls and links. */
const OWN_CONTROLS = 'video,audio,a,button,input,textarea,select';

function errorKind(error: unknown): 'gone' | 'busy' | 'failed' {
  if (error instanceof ApiError && error.status === 404) return 'gone';
  if (error instanceof ApiError && error.status === 429) return 'busy';
  return 'failed';
}

function errorText(kind: 'gone' | 'busy' | 'failed') {
  switch (kind) {
    case 'gone': return t('这个分享链接已失效或不存在');
    case 'busy': return t('访问太频繁，请稍后再试');
    case 'failed': return t('加载失败');
  }
}

function nodeTitle(node: CanvasNode) {
  const { title, label } = node.payload;
  return (typeof title === 'string' && title.trim()) || (typeof label === 'string' && label.trim()) || kindLabel(node.kind) || node.kind;
}

function nodeText(node: CanvasNode) {
  const { prompt, text, styleText } = node.payload;
  for (const value of [prompt, text, styleText]) if (typeof value === 'string' && value.trim()) return value;
  return '';
}

function OutputView({ output, title, full }: { output: ShareOutput; title: string; full: boolean }) {
  const url = output.url ? apiUrl(output.url) : '';
  if (output.medium === 'image' && url) {
    return <div className="cn-preview scp-media"><img className="cn-media" src={url} alt={title} loading="lazy" draggable={false} /></div>;
  }
  if (output.medium === 'video' && url) {
    return (
      <div className="cn-preview scp-media">
        {full
          ? <video className="cn-media" src={url} controls preload="metadata" playsInline aria-label={title} />
          : <span className="scp-placeholder">{t('视频')}</span>}
      </div>
    );
  }
  if (output.medium === 'audio' && url) {
    return full ? <audio className="cn-audio" src={url} controls preload="metadata" aria-label={title} /> : <span className="scp-placeholder">{t('音频')}</span>;
  }
  if (output.text) return <p className="scp-text">{output.text}</p>;
  return output.filename ? <p className="scp-text">{output.filename}</p> : null;
}

/** One node as a visitor sees it: its name, and what it produced or, before that, what it was asked. */
function ReadOnlyNode({ node, output, lod }: { node: CanvasNode; output: ShareOutput | undefined; lod: NodeRenderProps['lod'] }) {
  const title = nodeTitle(node);
  if (node.kind === 'group') {
    return <div className="scp-group" data-no-drag><span className="scp-group__label">{title}</span></div>;
  }
  const text = nodeText(node);
  return (
    // data-no-drag: a press on a node never starts a move on the surface.
    <div className="cn-node scp-node" data-no-drag>
      <div className="cn-node__head scp-node__head">
        <strong title={title}>{title}</strong>
        <em className="cn-tag">{kindLabel(node.kind)}</em>
      </div>
      {lod !== 'shell' && (
        <div className="cn-node__body">
          {output ? <OutputView output={output} title={title} full={lod === 'full'} /> : text ? <p className="scp-text">{text}</p> : null}
        </div>
      )}
    </div>
  );
}

interface Pan {
  id: number;
  x: number;
  y: number;
  view: Viewport;
}

/** The read-only canvas behind a share link: anyone with the link may look, pan and zoom, and change nothing. */
export function SharedCanvasPage({ token }: { token: string }) {
  const [state, setState] = useState<LoadState>({ phase: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [grabbing, setGrabbing] = useState(false);
  const surface = useRef<SurfaceHandle>(null);
  const pan = useRef<Pan | null>(null);
  const touches = useRef(new Set<number>());

  useEffect(() => {
    const controller = new AbortController();
    fetchSharedCanvas(token, controller.signal)
      .then(canvas => setState({ phase: 'ready', canvas }))
      .catch(error => {
        if (!controller.signal.aborted) setState({ phase: 'error', kind: errorKind(error) });
      });
    return () => controller.abort();
  }, [token, attempt]);

  const canvas = state.phase === 'ready' ? state.canvas : null;

  useEffect(() => {
    if (canvas?.title) document.title = `${canvas.title} · Novara`;
  }, [canvas?.title]);

  // Show the whole canvas once it is laid out, and follow the zoom for the controls.
  useEffect(() => {
    if (!canvas) return undefined;
    const unsubscribe = surface.current?.subscribe(view => setZoom(view.zoom));
    const frame = requestAnimationFrame(() => surface.current?.fit(undefined, { instant: true }));
    return () => {
      cancelAnimationFrame(frame);
      unsubscribe?.();
    };
  }, [canvas]);

  const outputs = canvas?.outputs;
  const renderNode = useCallback(({ node, lod }: NodeRenderProps) => {
    const output = outputs?.[node.id] ?? (node.payload.output as NodeOutput | undefined);
    return <ReadOnlyNode node={node} output={output} lod={lod} />;
  }, [outputs]);

  const nodes = useMemo(() => canvas?.nodes ?? [], [canvas]);
  const edges = useMemo(() => canvas?.edges ?? [], [canvas]);

  // The surface pans with the middle button, Space or touch on empty canvas; here a plain left-drag
  // (or one finger on a node) pans as well, since there is nothing to select or move.
  const onPointerDownCapture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target instanceof Element ? event.target : null;
    const handle = surface.current;
    if (!target || !handle || !target.closest('.cn-surface') || target.closest(OWN_CONTROLS)) return;
    if (event.pointerType === 'touch') {
      touches.current.add(event.pointerId);
      // Two fingers are a pinch, which the surface handles; one finger on empty canvas pans there too.
      if (touches.current.size > 1 || !target.closest('[data-node-id]')) {
        pan.current = null;
        return;
      }
      pan.current = { id: event.pointerId, x: event.clientX, y: event.clientY, view: handle.getView() };
      return;
    }
    if (event.button !== 0) return;
    // The surface would start a marquee or a move; neither means anything here.
    event.preventDefault();
    event.stopPropagation();
    pan.current = { id: event.pointerId, x: event.clientX, y: event.clientY, view: handle.getView() };
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // A synthetic pointer has nothing to capture.
    }
    setGrabbing(true);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = pan.current;
    if (!current || current.id !== event.pointerId) return;
    surface.current?.setView({ ...current.view, x: current.view.x + event.clientX - current.x, y: current.view.y + event.clientY - current.y });
  };

  const endPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    touches.current.delete(event.pointerId);
    if (pan.current?.id !== event.pointerId) return;
    pan.current = null;
    setGrabbing(false);
  };

  return (
    <div className="scp-root">
      <header className="scp-header">
        <div className="scp-heading">
          <h1 className="scp-title" title={canvas?.title}>{canvas?.title || t('分享的画布')}</h1>
          <span className="scp-badge"><Eye aria-hidden="true" />{t('只读')}</span>
        </div>
        <div className="scp-meta">
          {canvas && <span>{shareExpiryText(canvas.expires_at)}</span>}
          <span>{t('由 Novara 分享')}</span>
        </div>
      </header>

      <main className="scp-stage">
        {state.phase === 'loading' && <p className="scp-state" role="status">{t('正在加载画布…')}</p>}
        {state.phase === 'error' && (
          <div className="scp-state" role="alert">
            <p>{errorText(state.kind)}</p>
            {state.kind !== 'gone' && <button type="button" className="scp-retry" onClick={() => { setState({ phase: 'loading' }); setAttempt(value => value + 1); }}>{t('重试')}</button>}
          </div>
        )}
        {canvas && (
          <div
            className={`cn-viewport scp-viewport${grabbing ? ' is-grabbing' : ''}`}
            onPointerDownCapture={onPointerDownCapture}
            onPointerMove={onPointerMove}
            onPointerUp={endPan}
            onPointerCancel={endPan}
          >
            <CanvasSurface
              ref={surface}
              nodes={nodes}
              edges={edges}
              selection={NO_IDS}
              edgeSelection={NO_IDS}
              initialView={null}
              background="dots"
              renderNode={renderNode}
              onSelect={noop}
              onMove={noop}
              onResize={noop}
              onConnect={noop}
              canConnect={never}
            />
            {!nodes.length && <p className="scp-empty">{t('这张画布还是空的')}</p>}
            <CanvasZoomControls
              zoom={zoom}
              hasSelection={false}
              onZoomTo={value => surface.current?.zoomTo(value)}
              onStep={dir => surface.current?.zoomStep(dir)}
              onFitAll={() => surface.current?.fit()}
            />
          </div>
        )}
      </main>
    </div>
  );
}

export default SharedCanvasPage;
