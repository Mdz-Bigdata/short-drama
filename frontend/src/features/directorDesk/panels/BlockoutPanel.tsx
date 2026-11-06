import { useEffect, useMemo, useRef, useState } from 'react';
import { Boxes, Eye, ImagePlus, Trash2 } from 'lucide-react';

import type { StagePlan, StageShot } from '../../spatial/spatialTypes';
import { analyzeBlockout, uploadCapture, type BlockoutPiece, type BlockoutProposal } from '../directorDeskApi';
import type { EditRequest } from '../deskTypes';

interface Props {
  taskId: string;
  sceneId: string;
  plan: StagePlan;
  shot?: StageShot;
  editable: boolean;
  onCommit: (request: EditRequest) => void;
  /** Look through a camera, in a layout that shows its view. */
  onLook: (cameraId: string) => void;
  /** A picture handed in from outside; nothing is analysed until asked, same as a chosen file. */
  initialReference?: { url: string };
}

const REFERENCE_CAMERA_LABEL = '参考机位';
const KIND_COLORS: Record<BlockoutPiece['kind'], string> = {
  architecture: 'var(--desk-dim)', furniture: 'var(--desk-amber)', prop: 'var(--desk-cyan)', light: 'var(--desk-red)',
};

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** The proposal seen from above, so a wrong reading is caught before it goes on the stage. */
export function BlockoutPlan({ pieces }: { pieces: BlockoutPiece[] }) {
  const box = useMemo(() => {
    const reach = pieces.flatMap(piece => {
      const radius = Math.hypot(piece.size[0], piece.size[1]) / 2;
      return [piece.center[0] - radius, piece.center[0] + radius, piece.center[1] - radius, piece.center[1] + radius];
    });
    const xs = reach.filter((_, index) => index % 4 < 2);
    const zs = reach.filter((_, index) => index % 4 >= 2);
    const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
    return { left, top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) };
  }, [pieces]);
  return (
    <svg className="desk-blockout__plan" viewBox={`${box.left} ${box.top} ${box.width} ${box.height}`} role="img" aria-label={`白模俯视图，共 ${pieces.length} 块`}>
      {pieces.map(piece => (
        <g key={piece.name} transform={`translate(${piece.center[0]} ${piece.center[1]}) rotate(${-piece.yaw_deg})`}>
          {piece.shape === 'cylinder' || piece.shape === 'sphere' || piece.shape === 'cone'
            ? <ellipse rx={piece.size[0] / 2} ry={piece.size[1] / 2} fill={KIND_COLORS[piece.kind]} fillOpacity={piece.size[2] < 0.2 ? 0.15 : 0.55} />
            : <rect x={-piece.size[0] / 2} y={-piece.size[1] / 2} width={piece.size[0]} height={piece.size[1]} fill={KIND_COLORS[piece.kind]} fillOpacity={piece.size[2] < 0.2 ? 0.15 : 0.55} />}
        </g>
      ))}
    </svg>
  );
}

/** A reference image turned into grey-box set pieces: read it, look at the reading, then put it on the stage. */
export function BlockoutPanel({ taskId, sceneId, plan, shot, editable, onCommit, onLook, initialReference }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [hint, setHint] = useState('');
  const [widthText, setWidthText] = useState('');
  const [proposal, setProposal] = useState<BlockoutProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [addCamera, setAddCamera] = useState(true);
  const [asBackdrop, setAsBackdrop] = useState(true);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!initialReference) return undefined;
    const controller = new AbortController();
    fetch(initialReference.url, { credentials: 'include', signal: controller.signal })
      .then(response => (response.ok ? response.blob() : Promise.reject(new Error(String(response.status)))))
      .then(blob => setFile(new File([blob], 'reference', { type: blob.type })))
      .catch(() => { if (!controller.signal.aborted) setMessage('连接的参考图没能读取，请手动选择。'); });
    return () => controller.abort();
  }, [initialReference]);

  const picture = useMemo(() => (file ? URL.createObjectURL(file) : ''), [file]);
  useEffect(() => () => { if (picture) URL.revokeObjectURL(picture); }, [picture]);

  const held = plan.landmarks.filter(item => item.origin === 'blockout');
  const reference = plan.cameras.find(camera => camera.label === REFERENCE_CAMERA_LABEL && (shot?.alt_camera_ids ?? []).includes(camera.id));
  const width = Number(widthText);
  const widthRefused = widthText.trim() !== '' && !(width > 0 && width <= 500);

  const analyze = async () => {
    if (!file || busy || widthRefused) return;
    setBusy(true);
    setMessage('');
    setProposal(null);
    try {
      setProposal(await analyzeBlockout(taskId, sceneId, file, { hint, widthM: widthText.trim() ? width : undefined }));
    } catch (error) {
      setMessage(messageOf(error, '参考图解析失败，请稍后重试。'));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!proposal || busy) return;
    const camera = addCamera && shot && proposal.reference_camera ? { shot_id: shot.shot_id, reference_camera: proposal.reference_camera } : {};
    onCommit({ label: `参考图白模（${proposal.pieces.length} 块）`, barrier: true, operations: [{ op: 'apply_blockout', replace: true, pieces: proposal.pieces, ...camera }] });
    setProposal(null);
    setMessage(`已铺上 ${proposal.pieces.length} 块白模，每一块都能单独移动、缩放或删除。`);
    if (!asBackdrop || !file) return;
    setBusy(true);
    try {
      const stored = await uploadCapture(taskId, sceneId, {
        blob: file, kind: 'backdrop', shotId: 0, cameraId: '', width: 0, height: 0, planRevision: 0, showsLimbs: false, monochrome: false, labelled: false,
      });
      onCommit({ label: '背景：参考图', operations: [{ op: 'set_backdrop', kind: 'image', url: stored.url, opacity: 0.6 }] });
    } catch (error) {
      setMessage(messageOf(error, '白模已铺上，但参考图没能设为背景。'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="desk-blockout" aria-label="参考图生成白模">
      <h2><Boxes aria-hidden="true" /> 参考图生成白模</h2>
      <p className="desk-captures__note">上传一张场景图，由多模态模型拆成体块铺到舞台上，再在上面走位、架机位。每解析一次调用一次模型。</p>

      <input
        ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label="选择参考图"
        onChange={event => { setFile(event.target.files?.[0] ?? null); setProposal(null); setMessage(''); event.target.value = ''; }}
      />
      <button type="button" className="desk-blockout__drop" disabled={!editable || busy} onClick={() => input.current?.click()}>
        {picture ? <img src={picture} alt="所选参考图" /> : <><ImagePlus aria-hidden="true" /><span>选择参考图</span></>}
      </button>

      <label className="desk-field is-wide">
        <span>场地宽度（米，可选）</span>
        <input aria-label="场地宽度（米）" inputMode="decimal" value={widthText} placeholder="不填由模型估算" onChange={event => setWidthText(event.target.value)} />
        {widthRefused && <small className="desk-field__problem">填 0 到 500 之间的数字</small>}
      </label>
      <label className="desk-field is-wide">
        <span>补充说明（可选）</span>
        <textarea aria-label="补充说明" rows={2} maxLength={300} value={hint} placeholder="例如：俯拍的中世纪庭院迷宫" onChange={event => setHint(event.target.value)} />
      </label>
      <button type="button" className="desk-button is-primary" disabled={!editable || !file || busy || widthRefused} onClick={() => { void analyze(); }}>
        {busy ? '解析中…（可能要一两分钟）' : proposal ? '重新解析' : '解析参考图'}
      </button>

      {proposal && (
        <div className="desk-blockout__proposal">
          <h3>解析结果 <small>{proposal.pieces.length} 块 · {proposal.model}</small></h3>
          {proposal.summary && <p>{proposal.summary}</p>}
          <BlockoutPlan pieces={proposal.pieces} />
          {proposal.dropped > 0 && <p className="desk-field__problem" role="status">有 {proposal.dropped} 块字段不完整或超出上限，已略去。</p>}
          <div className="desk-toggles">
            <label><input type="checkbox" checked={addCamera} disabled={!proposal.reference_camera || !shot} onChange={event => setAddCamera(event.target.checked)} /> 添加参考机位</label>
            <label><input type="checkbox" checked={asBackdrop} onChange={event => setAsBackdrop(event.target.checked)} /> 把参考图设为机位背景</label>
          </div>
          <button type="button" className="desk-button is-primary" disabled={!editable || busy} onClick={() => { void apply(); }}>
            {held.length ? `替换舞台上的 ${held.length} 块白模` : '铺到舞台上'}
          </button>
        </div>
      )}

      {message && <p className="desk-captures__note" role="status">{message}</p>}

      {held.length > 0 && (
        <div className="desk-blockout__held">
          <h3>舞台上的白模 <small>{held.length} 块</small></h3>
          {reference && (
            <button type="button" className="desk-button" onClick={() => onLook(reference.id)}><Eye aria-hidden="true" /> 从参考机位看</button>
          )}
          <button type="button" className="desk-button is-danger" disabled={!editable} onClick={() => onCommit({ label: '清除白模', barrier: true, operations: [{ op: 'clear_blockout' }] })}>
            <Trash2 aria-hidden="true" /> 清除白模
          </button>
        </div>
      )}
    </section>
  );
}
