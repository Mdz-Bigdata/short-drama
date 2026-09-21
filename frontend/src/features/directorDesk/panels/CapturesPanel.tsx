import { useCallback, useEffect, useRef, useState } from 'react';
import { Aperture, Check, Clapperboard, Download, Eye, Trash2, Undo2, X } from 'lucide-react';

import type { StageCamera } from '../../spatial/spatialTypes';
import type { LensHandle } from '../deskTypes';
import type { ClipStage } from '../lib/clipExport';
import { useReducedMotion } from '../lib/useReducedMotion';
import {
  applyCapture, deleteCapture, downloadCapture, isApplied, listCaptures, unapplyCapture, uploadCapture,
  type DeskCapture, type DeskCaptureList,
} from '../directorDeskApi';

interface Props {
  taskId: string;
  sceneId: string;
  shotId: number | null;
  /** The lens the camera view looks through: what a new still is a picture of. */
  camera?: StageCamera;
  cameras: StageCamera[];
  planRevision: number;
  /** Unconfirmed edits are on screen: a still now would carry a revision it does not match. */
  saving: boolean;
  getLens: () => LensHandle | null;
  /** Delivery aspect (width / height) and the shot's timeline: what a blockout clip is made to. */
  aspect: number;
  durationS: number;
  fps: number;
  /** The lens canvas, ready to be driven frame by frame; `null` while the camera view is not on screen. */
  getClipStage: () => ClipStage | null;
}

// Shown for records saved before the server started writing the sentence itself.
const LIMBS_WARNING = '白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function when(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function CapturesPanel({ taskId, sceneId, shotId, camera, cameras, planRevision, saving, getLens, aspect, durationS, fps, getClipStage }: Props) {
  const [list, setList] = useState<DeskCaptureList>({ captures: [], applied: {} });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [monochrome, setMonochrome] = useState(false);
  const [labels, setLabels] = useState(false);
  const [viewing, setViewing] = useState<DeskCapture | null>(null);
  // 0…1 while a clip is being rendered; the controller is how 取消 reaches the frame loop.
  const [progress, setProgress] = useState<number | null>(null);
  const exporting = useRef<AbortController | null>(null);
  const reducedMotion = useReducedMotion();
  // Closing the desk mid-export stops the loop, which puts the renderer back the way it was.
  useEffect(() => () => exporting.current?.abort(), []);

  const refresh = useCallback((signal?: AbortSignal) => (
    listCaptures(taskId, sceneId, signal)
      .then(data => { setList(data); setLoaded(true); })
      .catch(error => { if (!signal?.aborted) { setLoaded(true); setNotice(messageOf(error, '截图库读取失败。')); } })
  ), [sceneId, taskId]);

  // A plan edit is what turns captures stale, so every new revision is a reason to look again.
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [planRevision, refresh]);

  const run = async (work: () => Promise<DeskCaptureList | void>, done: string) => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      const next = await work();
      if (next) setList(next);
      setNotice(done);
    } catch (error) {
      setNotice(messageOf(error, '操作失败，请稍后重试。'));
    } finally {
      setBusy(false);
    }
  };

  const take = () => run(async () => {
    const lens = getLens();
    if (!lens || !camera || shotId === null) throw new Error('机位视角还没有准备好，请切到「并排」或「机位」布局后再截图。');
    const still = await lens.capture({ monochrome, labels });
    await uploadCapture(taskId, sceneId, {
      blob: still.blob, width: still.width, height: still.height, shotId, cameraId: camera.id, planRevision, showsLimbs: still.showsLimbs, monochrome, labelled: labels,
    });
    return listCaptures(taskId, sceneId);
  }, '已截图并保存到截图库。');

  const film = () => run(async () => {
    if (!camera || shotId === null) throw new Error('本镜还没有机位。');
    const stage = getClipStage();
    if (!stage) throw new Error('机位视角还没有准备好，请切到「并排」或「机位」布局后再导出。');
    const controller = new AbortController();
    exporting.current = controller;
    setProgress(0);
    try {
      // three.js and the encoder stay out of the desk's first load.
      const { exportClip } = await import('../lib/clipExport');
      const clip = await exportClip({ stage, aspect, durationS, fps, monochrome, labels, signal: controller.signal, onProgress: setProgress });
      await uploadCapture(taskId, sceneId, {
        kind: 'clip', blob: clip.blob, width: clip.width, height: clip.height, durationS: clip.durationS, fps: clip.fps,
        shotId, cameraId: camera.id, planRevision, showsLimbs: clip.showsLimbs, monochrome, labelled: labels,
      });
      return await listCaptures(taskId, sceneId);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw new Error('已取消导出，没有保存任何文件。', { cause: error });
      throw error;
    } finally {
      exporting.current = null;
      setProgress(null);
    }
  }, '白模视频已导出并保存到截图库。');

  const cameraLabel = (id: string) => cameras.find(item => item.id === id)?.label || id || '—';
  // The scene's backdrops share this store but are not pictures of the stage; they live in「机位」.
  const shown = list.captures.filter(capture => capture.kind !== 'backdrop');

  return (
    <section className="desk-captures" aria-label="截图库">
      <h2><Aperture aria-hidden="true" /> 截图库 <small>{shown.length}</small></h2>
      <div className="desk-toggles">
        <label><input type="checkbox" checked={monochrome} onChange={event => setMonochrome(event.target.checked)} /> 统一白模色</label>
        <label><input type="checkbox" checked={labels} onChange={event => setLabels(event.target.checked)} /> 烧入角色名</label>
      </div>
      <button type="button" className="desk-button is-primary" disabled={busy || saving || !camera || shotId === null} onClick={() => { void take(); }}>
        <Aperture aria-hidden="true" /> {busy ? '处理中…' : `截取第 ${shotId ?? '—'} 镜画面`}
      </button>
      <p className="desk-captures__note">{saving ? '正在保存站位，保存完成后可截图。' : '按成片画幅输出，长边 1920 像素；网格、机位架和辅助线不会进入画面。'}</p>
      <button type="button" className="desk-button" disabled={busy || saving || !camera || shotId === null} onClick={() => { void film(); }}>
        <Clapperboard aria-hidden="true" /> 导出第 {shotId ?? '—'} 镜白模视频（{durationS} 秒 · {fps} fps）
      </button>
      {progress !== null && (
        <div className="desk-captures__progress" role="group" aria-label="导出进度">
          <progress aria-label="白模视频导出进度" value={progress} max={1} />
          <span>{Math.round(progress * 100)}%</span>
          <button type="button" className="desk-button" onClick={() => exporting.current?.abort()}>取消</button>
        </div>
      )}
      <details className="desk-captures__handoff">
        <summary>白模视频应用到分镜后会发生什么</summary>
          <p>视频排到本镜 <code>reference_videos</code> 的第一位；每镜只保留一条导演台视频，新的替换旧的。</p>
          <p>第 5 阶段把本镜标为「必须使用动作参考」：自动选模式时按多模态（multimodal）生成，优先于首尾帧；所选视频模型不支持多模态时本镜会报错，而不是悄悄丢掉视频。</p>
          <p>实测机位句（「机位距…米、机高…米」）从本镜的站位描述和运动提示词里撤下，机位只听白模视频，避免两套机位指令打架。</p>
          <p>带四肢的白模会在运动提示词后追加一句要求：按时间顺序分段写清肢体动作。</p>
          <p>站位或时间线再改一次，视频即标为过期；第 5 阶段不再使用过期视频，机位句恢复。请重新导出后再应用。</p>
      </details>
      {notice && <p className="desk-captures__notice" role="status">{notice}</p>}

      {loaded && shown.length === 0 && <p className="desk-inspector__empty">还没有截图。截图可以应用到分镜，作为第 5 阶段的首帧参考。</p>}
      <ul className="desk-captures__list">
        {shown.map(capture => {
          const applied = isApplied(list, capture);
          const title = `第 ${capture.shotId} 镜 · ${cameraLabel(capture.cameraId)}`;
          return (
            <li key={capture.id} className={capture.stale ? 'is-stale' : ''}>
              <button type="button" className="desk-captures__thumb" aria-label={`查看 ${title}`} onClick={() => setViewing(capture)}>
                {capture.kind === 'still' ? <img src={capture.url} alt="" loading="lazy" /> : <video src={capture.url} muted loop playsInline preload="metadata" aria-label={`${title} 白模视频`} onMouseEnter={event => { if (!reducedMotion) void event.currentTarget.play().catch(() => {}); }} onMouseLeave={event => event.currentTarget.pause()} />}
              </button>
              <div className="desk-captures__meta">
                <strong>{title}</strong>
                <small>{capture.kind === 'clip' ? `白模视频 · ${capture.durationS} 秒 · ${capture.fps} fps · ` : ''}第 {capture.planRevision} 版 · {capture.width}×{capture.height}{when(capture.createdAt) ? ` · ${when(capture.createdAt)}` : ''}</small>
                <span className="desk-captures__badges">
                  {capture.stale && <em className="desk-badge is-stale" title="截取之后站位已修改">过期</em>}
                  {applied && <em className="desk-badge is-applied">已应用</em>}
                  {capture.monochrome && <em className="desk-badge">白模色</em>}
                  {capture.labelled && <em className="desk-badge">带角色名</em>}
                  {capture.showsLimbs && <em className="desk-badge is-limbs">带四肢</em>}
                </span>
                {capture.showsLimbs && <small className="desk-captures__warning" role="note">{capture.warning || LIMBS_WARNING}</small>}
              </div>
              <div className="desk-captures__actions">
                <button type="button" className="desk-icon" aria-label={`查看 ${title}`} onClick={() => setViewing(capture)}><Eye aria-hidden="true" /></button>
                {applied ? (
                  <button type="button" className="desk-icon" aria-label={`取消应用 ${title}`} disabled={busy} onClick={() => { void run(() => unapplyCapture(taskId, sceneId, capture.id), '已从分镜中取消应用。'); }}><Undo2 aria-hidden="true" /></button>
                ) : (
                  <button
                    type="button" className="desk-icon" aria-label={`应用至分镜 ${title}`} disabled={busy || capture.stale}
                    title={capture.stale ? '这条是按旧站位拍的，请重新截取后再应用' : capture.kind === 'clip' ? '应用后本镜按多模态生成，实测机位句让位给白模视频' : undefined}
                    onClick={() => { void run(() => applyCapture(taskId, sceneId, capture.id), capture.kind === 'clip' ? `已应用到第 ${capture.shotId} 镜：第 5 阶段将按多模态使用这条白模视频，实测机位句不再写入本镜提示词。` : `已应用到第 ${capture.shotId} 镜。`); }}
                  ><Check aria-hidden="true" /></button>
                )}
                <button
                  type="button" className="desk-icon" aria-label={`下载 ${title}`} disabled={busy}
                  onClick={() => { void run(async () => { if (!await downloadCapture(capture)) throw new Error('下载失败，请稍后重试。'); }, ''); }}
                ><Download aria-hidden="true" /></button>
                <button
                  type="button" className="desk-icon" aria-label={`删除 ${title}`} disabled={busy}
                  onClick={() => { if (window.confirm(applied ? '这张截图正在被分镜使用，删除后会同时从分镜中移除。继续吗？' : '删除这张截图？')) void run(() => deleteCapture(taskId, sceneId, capture.id), '已删除。'); }}
                ><Trash2 aria-hidden="true" /></button>
              </div>
            </li>
          );
        })}
      </ul>

      {viewing && (
        <div className="desk-modal__backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setViewing(null); }}>
          <figure className="desk-captures__viewer" role="dialog" aria-modal="true" aria-label="查看截图">
            <button type="button" className="desk-icon" aria-label="关闭查看" onClick={() => setViewing(null)}><X aria-hidden="true" /></button>
            {viewing.kind === 'still' ? <img src={viewing.url} alt={`第 ${viewing.shotId} 镜截图`} /> : <video src={viewing.url} controls autoPlay loop muted playsInline aria-label={`第 ${viewing.shotId} 镜白模视频`} />}
            <figcaption>第 {viewing.shotId} 镜 · {cameraLabel(viewing.cameraId)} · 第 {viewing.planRevision} 版{viewing.stale ? ' · 已过期' : ''}</figcaption>
          </figure>
        </div>
      )}
    </section>
  );
}
