import { Component, lazy, memo, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  AudioLines, Box, Boxes, Clapperboard, Clock, Film, Globe2, ImageIcon, Loader2, Palette, Play, StickyNote, Upload, X, type LucideIcon, Wrench } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { isApplied, listCaptures, type DeskCapture, type DeskCaptureList } from '../directorDesk/directorDeskApi';
import { fetchSpatialPlan } from '../spatial/spatialApi';
import type { StagePlan } from '../spatial/spatialTypes';
import { acceptsInput, outputType, RUNNABLE_KINDS } from './canvasGraph';
import { useCanvasActions } from './canvasContext';
import { kindLabel, nodeTitle, outputLabel, statusLabel } from './canvasLabels';
import type { CanvasNode, LatestRun, NodeKind, NodeOutput } from './canvasTypes';
import type { DropState } from './CanvasSurface';
import { ToolBody } from './ToolBody';

const PanoramaViewer = lazy(() => import('./PanoramaViewer'));

const KIND_ICONS: Record<NodeKind, LucideIcon> = {
  artifact: Box, candidate: Boxes, media: Upload, note: StickyNote, group: Boxes, image_gen: ImageIcon, video_gen: Film,
  audio_gen: AudioLines, video_compose: Clapperboard, style_ref: Palette, panorama: Globe2, previz: Clapperboard, tool: Wrench,
};

export const ACCEPTED_UPLOADS = 'image/png,image/jpeg,image/webp,video/mp4,video/webm,audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/aac,audio/ogg';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function MediaPreview({ output }: { output: NodeOutput }) {
  const url = apiUrl(output.url);
  if (output.medium === 'image') return <img className="cn-media" src={url} alt="" loading="lazy" draggable={false} />;
  if (output.medium === 'video') return <video className="cn-media" src={url} controls preload="metadata" playsInline />;
  return <audio className="cn-audio" src={url} controls preload="none" />;
}

function UploadButton({ nodeId, label }: { nodeId: string; label: string }) {
  const { upload } = useCanvasActions();
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input} type="file" hidden accept={ACCEPTED_UPLOADS} aria-label={t('选择文件')}
        onChange={event => {
          const file = event.target.files?.[0];
          if (file) upload(nodeId, file);
          event.target.value = '';
        }}
      />
      <button type="button" className="cn-button" onClick={() => input.current?.click()}><Upload aria-hidden="true" /> {label}</button>
    </>
  );
}

function RunBar({ node, latest }: { node: CanvasNode; latest?: LatestRun }) {
  const { run, cancel, options } = useCanvasActions();
  const busy = latest?.status === 'queued' || latest?.status === 'running';
  const kind = options?.kinds[node.kind];
  return (
    <div className="cn-runbar">
      <button type="button" className="cn-button is-primary" disabled={busy || kind?.runnable === false} onClick={() => run([node.id])}>
        {busy ? <Loader2 className="cn-spin" aria-hidden="true" /> : <Play aria-hidden="true" />} {t('运行')}
      </button>
      {latest && <span className={`cn-status is-${latest.status}`} title={latest.error ?? undefined}>{statusLabel(latest.status)}</span>}
      {latest?.status === 'queued' && (
        <button type="button" className="cn-button is-quiet" onClick={() => cancel(latest)} aria-label={t('取消排队')}><X aria-hidden="true" /></button>
      )}
      {latest?.status === 'failed' && latest.error && <p className="cn-error" role="status">{latest.error}</p>}
    </div>
  );
}

function PromptField({ node, label, field, placeholder }: { node: CanvasNode; label: string; field: 'prompt' | 'text' | 'styleText'; placeholder?: string }) {
  const { patch } = useCanvasActions();
  return (
    <textarea
      className="cn-textarea" aria-label={label} placeholder={placeholder ?? label} value={String(node.payload[field] ?? '')} maxLength={8000}
      onChange={event => patch(node.id, { [field]: event.target.value }, `${field}:${node.id}`)}
    />
  );
}

function GenerateBody({ node, output, latest, inputs }: { node: CanvasNode; output: NodeOutput | null; latest?: LatestRun; inputs: number }) {
  const { options, patch } = useCanvasActions();
  const reason = options?.kinds[node.kind]?.reason;
  const mode = node.payload.params?.mode ?? 'speech';
  return (
    <>
      {output && <div className="cn-preview"><MediaPreview output={output} /></div>}
      {output?.seam && <p className={`cn-hint cn-seam is-${output.seam.verdict}`} role={output.seam.verdict === 'good' ? undefined : 'status'} title={output.seam.detail}>{t('接缝：{0}', [output.seam.label])}{output.seam.verdict !== 'good' ? ` · ${output.seam.detail}` : ''}</p>}
      <PromptField node={node} label={node.kind === 'audio_gen' ? t('要合成的文本') : t('提示词')} field="prompt" />
      {node.kind === 'audio_gen' && (
        <select
          className="cn-select" aria-label={t('音频类型')} value={mode}
          onChange={event => patch(node.id, { params: { ...node.payload.params, mode: event.target.value as 'speech' | 'music' | 'sfx' } })}
        >
          <option value="speech">{t('配音')}</option>
          <option value="music" disabled={options?.kinds.audio_gen?.modes?.music === false}>{t('配乐')}</option>
          <option value="sfx" disabled={options?.kinds.audio_gen?.modes?.sfx === false}>{t('音效')}</option>
        </select>
      )}
      {node.kind === 'video_gen' && inputs === 0 && reason && <p className="cn-hint">{reason}</p>}
      {node.kind === 'audio_gen' && reason && <p className="cn-hint">{reason}</p>}
      {node.kind !== 'audio_gen' && inputs > 0 && <p className="cn-hint">{t('已连接 {0} 个输入', [inputs])}</p>}
      <RunBar node={node} latest={latest} />
    </>
  );
}

function ComposeBody({ node, output, latest, inputs }: { node: CanvasNode; output: NodeOutput | null; latest?: LatestRun; inputs: number }) {
  const { options } = useCanvasActions();
  return (
    <>
      {output && <div className="cn-preview"><MediaPreview output={output} /></div>}
      <p className="cn-hint">{t('按连入顺序拼接 {0} 个输入', [inputs])}</p>
      {options?.kinds.video_compose?.reason && <p className="cn-hint">{options.kinds.video_compose.reason}</p>}
      <RunBar node={node} latest={latest} />
    </>
  );
}

function webglAvailable() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

/** A failed 3D view stays inside its node: the rest of the canvas, with whatever is unsaved, must not go with it. */
class ViewerBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function PanoramaBody({ node, output, selected }: { node: CanvasNode; output: NodeOutput | null; selected: boolean }) {
  const [inside, setInside] = useState(false);
  const [noWebgl, setNoWebgl] = useState(false);
  const url = output?.medium === 'image' ? output.url : '';
  if (!url) {
    return (
      <>
        <p className="cn-hint">{t('连一张等距柱状投影全景图，或上传一张。')}</p>
        <UploadButton nodeId={node.id} label={t('上传全景图')} />
      </>
    );
  }
  return inside && selected ? (
    <>
      <ViewerBoundary fallback={<p className="cn-error" role="status">{t('全景视图打开失败，这个浏览器可能不支持 WebGL。')}</p>}>
        <Suspense fallback={<p className="cn-hint">{t('加载全景…')}</p>}><PanoramaViewer url={url} /></Suspense>
      </ViewerBoundary>
      <button type="button" className="cn-button" onClick={() => setInside(false)}>{t('退出全景')}</button>
    </>
  ) : (
    <>
      <div className="cn-preview"><img className="cn-media" src={apiUrl(url)} alt="" loading="lazy" draggable={false} /></div>
      {noWebgl && <p className="cn-error" role="status">{t('全景视图打开失败，这个浏览器可能不支持 WebGL。')}</p>}
      <button
        type="button" className="cn-button" disabled={!selected} title={selected ? undefined : t('先选中这个节点')}
        onClick={() => {
          const supported = webglAvailable();
          setNoWebgl(!supported);
          setInside(supported);
        }}
      >
        <Globe2 aria-hidden="true" /> {t('进入全景')}
      </button>
    </>
  );
}

function usableCapture(capture: DeskCapture) {
  // A backdrop is the desk's own framing underlay, and a depth still would be copied as a grey frame.
  return capture.kind !== 'backdrop' && !capture.stale && !(capture.depth && capture.kind === 'still');
}

function PrevizBody({ node, reference }: { node: CanvasNode; reference: string | null }) {
  const { taskId, shots, deskToken, patch, openDesk } = useCanvasActions();
  const sceneId = node.payload.sceneId ?? '';
  const shotId = node.payload.shotId ?? null;
  const [plan, setPlan] = useState<{ scene: string; plan: StagePlan | null }>({ scene: '', plan: null });
  const [list, setList] = useState<DeskCaptureList>({ captures: [], applied: {} });
  const [problem, setProblem] = useState('');

  useEffect(() => {
    if (!sceneId) return undefined;
    const controller = new AbortController();
    fetchSpatialPlan(taskId, sceneId, controller.signal)
      .then(response => { setPlan({ scene: sceneId, plan: response.plan }); setProblem(''); })
      .catch(error => { if (!controller.signal.aborted) { setPlan({ scene: sceneId, plan: null }); setProblem(messageOf(error, t('空间方案读取失败'))); } });
    listCaptures(taskId, sceneId, controller.signal)
      .then(setList)
      // A scene the desk has not touched has no capture record; that is the normal case.
      .catch(() => { if (!controller.signal.aborted) setList({ captures: [], applied: {} }); });
    return () => controller.abort();
  }, [deskToken, sceneId, taskId]);

  const scenes = [...new Set(shots.map(item => item.scene_id))];
  const sceneShots = shots.filter(item => item.scene_id === sceneId);
  const current = plan.scene === sceneId ? plan.plan : null;
  const objects = current ? current.actors.length + current.landmarks.length + (current.crowds?.length ?? 0) : null;
  const timelines = Object.entries(current?.timelines ?? {}).filter(([id]) => shotId === null || id === String(shotId));
  const frames = current ? timelines.reduce((total, [, item]) => total + Math.max(1, Math.ceil(item.duration_s * item.fps)), 0) : null;
  const selected = new Set(node.payload.selectedCaptureIds ?? []);
  const captures = list.captures.filter(item => item.kind !== 'backdrop' && (shotId === null || item.shotId === shotId));

  return (
    <>
      <div className="cn-row">
        <select
          className="cn-select" aria-label={t('场景')} value={sceneId}
          onChange={event => patch(node.id, { sceneId: event.target.value, shotId: null, selectedCaptureIds: [] })}
        >
          <option value="">{t('选择场景')}</option>
          {scenes.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
        <select
          className="cn-select" aria-label={t('镜头')} value={shotId ?? ''} disabled={!sceneId}
          onChange={event => patch(node.id, { shotId: event.target.value ? Number(event.target.value) : null, selectedCaptureIds: [] })}
        >
          <option value="">{t('全部镜头')}</option>
          {sceneShots.map(item => <option key={item.shot_id} value={item.shot_id}>{t('第 {0} 镜', [item.shot_id])}</option>)}
        </select>
      </div>
      {!scenes.length && <p className="cn-hint">{t('项目还没有分镜，完成第 4 阶段后才有场景可选。')}</p>}
      {sceneId && (
        <p className="cn-hint">
          {objects === null ? (problem || t('读取中…')) : t('{0} 个对象 · {1} 帧', [objects, frames ?? 0])}
        </p>
      )}
      <button type="button" className="cn-button is-primary" disabled={!sceneId} onClick={() => openDesk(node.id)} aria-haspopup="dialog">
        <Clapperboard aria-hidden="true" /> {t('打开预演台')}
      </button>
      {reference && <p className="cn-hint">{t('已连接参考图，会带入预演台的白模页')}</p>}
      {captures.length > 0 && (
        <div className="cn-captures" data-no-wheel data-no-drag role="group" aria-label={t('预演台的输出')}>
          {captures.map(capture => {
            const usable = usableCapture(capture);
            return (
              <label key={capture.id} className={`cn-capture${capture.stale ? ' is-stale' : ''}`} title={capture.stale ? t('按旧站位拍的，不能用；回预演台重新截取') : capture.warning || undefined}>
                <input
                  type="checkbox" checked={selected.has(capture.id)} disabled={!usable}
                  aria-label={capture.kind === 'clip' ? t('白模视频 {0}', [capture.id.slice(0, 6)]) : t('静帧 {0}', [capture.id.slice(0, 6)])}
                  onChange={event => {
                    const next = new Set(selected);
                    if (event.target.checked) next.add(capture.id);
                    else next.delete(capture.id);
                    patch(node.id, { selectedCaptureIds: [...next] });
                  }}
                />
                {capture.kind === 'clip'
                  ? <video src={apiUrl(capture.url)} muted preload="metadata" />
                  : <img src={apiUrl(capture.url)} alt="" loading="lazy" draggable={false} />}
                <small>
                  {capture.kind === 'clip' ? `${capture.durationS}s` : t('静帧')}
                  {capture.stale ? ` · ${t('过期')}` : ''}
                  {isApplied(list, capture) ? ` · ${t('已应用')}` : ''}
                </small>
              </label>
            );
          })}
        </div>
      )}
    </>
  );
}

function Body({ node, output, latest, selected, inputs, reference }: { node: CanvasNode; output: NodeOutput | null; latest?: LatestRun; selected: boolean; inputs: number; reference: string | null }) {
  switch (node.kind) {
    case 'media':
      return (
        <>
          {output ? <div className="cn-preview"><MediaPreview output={output} /></div> : <p className="cn-hint">{t('图片、视频或音频')}</p>}
          {output?.filename && <small className="cn-filename">{output.filename}</small>}
          <UploadButton nodeId={node.id} label={output ? t('替换文件') : t('上传文件')} />
        </>
      );
    case 'note':
      return <PromptField node={node} label={t('文本')} field="text" />;
    case 'image_gen': case 'video_gen': case 'audio_gen':
      return <GenerateBody node={node} output={output} latest={latest} inputs={inputs} />;
    case 'video_compose':
      return <ComposeBody node={node} output={output} latest={latest} inputs={inputs} />;
    case 'tool':
      return (
        <ToolBody
          node={node} output={output} runBar={<RunBar node={node} latest={latest} />}
          media={output ? <div className="cn-preview"><MediaPreview output={output} /></div> : null}
          prompt={label => <PromptField node={node} label={label} field="prompt" />}
        />
      );
    case 'style_ref':
      return (
        <>
          {output ? <div className="cn-preview"><MediaPreview output={output} /></div> : <UploadButton nodeId={node.id} label={t('上传风格图')} />}
          <PromptField node={node} label={t('风格描述')} field="styleText" />
        </>
      );
    case 'panorama':
      return <PanoramaBody node={node} output={output} selected={selected} />;
    case 'previz':
      return <PrevizBody node={node} reference={reference} />;
    default:
      return (
        <>
          {output && <div className="cn-preview"><MediaPreview output={output} /></div>}
          {node.artifact_id && <small className="cn-filename">{node.artifact_id}</small>}
          {node.payload.text && <p className="cn-hint">{node.payload.text}</p>}
        </>
      );
  }
}

/** A node from far away: where it is and what kind, nothing else. */
export const NodeShell = memo(function NodeShell({ node, selected }: { node: CanvasNode; selected: boolean }) {
  return (
    <div className={`cn-shell cn-kind--${node.kind}${selected ? ' is-selected' : ''}${node.track === 'mainline' ? ' is-mainline' : ''}`}>
      {node.kind === 'group' && <span>{nodeTitle(node)}</span>}
    </div>
  );
});

interface CardProps {
  node: CanvasNode;
  selected: boolean;
  dropState: DropState;
  output: NodeOutput | null;
  latest?: LatestRun;
  historyCount: number;
  inputs: number;
  /** Previz only: the connected picture that goes along to the desk's 白模 tab. */
  reference: string | null;
}

export const CanvasNodeCard = memo(function CanvasNodeCard({ node, selected, dropState, output, latest, historyCount, inputs, reference }: CardProps) {
  const Icon = KIND_ICONS[node.kind];
  const produced = outputType(node);
  if (node.kind === 'group') {
    return (
      <div className={`cn-group${selected ? ' is-selected' : ''}`}>
        <header className="cn-group__head"><Boxes aria-hidden="true" /> {nodeTitle(node)}</header>
        <span className="cn-resize" data-resize aria-hidden="true" />
      </div>
    );
  }
  return (
    <article
      className={`cn-node cn-kind--${node.kind}${selected ? ' is-selected' : ''}${dropState ? ` is-drop-${dropState}` : ''}${node.track === 'mainline' ? ' is-mainline' : ''}`}
      aria-label={`${kindLabel(node.kind)}：${nodeTitle(node)}`}
    >
      <header className="cn-node__head">
        <Icon aria-hidden="true" />
        <strong>{nodeTitle(node)}</strong>
        {node.track === 'mainline' && <em className="cn-tag" title={t('已提交到项目')}>{t('已提交')}</em>}
        {RUNNABLE_KINDS.has(node.kind) && historyCount > 0 && (
          <span className="cn-count" title={t('生成记录')}><Clock aria-hidden="true" /> {historyCount}</span>
        )}
      </header>
      <div className="cn-node__body"><Body node={node} output={output} latest={latest} selected={selected} inputs={inputs} reference={reference} /></div>
      {acceptsInput(node) && <span className="cn-port cn-port--in" aria-hidden="true" />}
      {produced && <span className="cn-port cn-port--out" data-port="out" title={t('拖出连线（输出：{0}）', [outputLabel(produced)])} />}
      <span className="cn-resize" data-resize aria-hidden="true" />
    </article>
  );
});
