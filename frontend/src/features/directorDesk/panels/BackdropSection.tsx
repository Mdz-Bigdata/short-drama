import { useCallback, useEffect, useRef, useState } from 'react';
import { Image as ImageIcon, Trash2, Upload } from 'lucide-react';

import { NO_BACKDROP, type BackdropKind, type StageBackdrop } from '../../spatial/spatialTypes';
import type { EditRequest } from '../deskTypes';
import { deleteCapture, listCaptures, uploadCapture, uploadRefusal, type DeskCapture } from '../directorDeskApi';

interface Props {
  taskId: string;
  sceneId: string;
  backdrop: StageBackdrop;
  editable: boolean;
  /** Whether a delivered still or clip keeps the backdrop; lives in the desk, not in the plan. */
  inCapture: boolean;
  onInCapture: (value: boolean) => void;
  onCommit: (request: EditRequest) => void;
  onPreview: (operations: null) => void;
}

const KINDS: Array<{ id: BackdropKind; label: string }> = [
  { id: 'none', label: '无' }, { id: 'color', label: '纯色' }, { id: 'image', label: '参考图' }, { id: 'panorama', label: '全景图' },
];

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * The scene's backdrop: what the *lens* stands in front of.
 *
 * A picture is stored the way every other desk upload is — under the task, as a capture of kind
 * `backdrop` — and the plan keeps only its URL, so the backdrop travels with the scene and a
 * re-plan does not lose it.
 */
export function BackdropSection({ taskId, sceneId, backdrop, editable, inCapture, onInCapture, onCommit, onPreview }: Props) {
  const [pictures, setPictures] = useState<DeskCapture[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const file = useRef<HTMLInputElement>(null);

  const refresh = useCallback((signal?: AbortSignal) => (
    listCaptures(taskId, sceneId, signal)
      .then(data => setPictures(data.captures.filter(item => item.kind === 'backdrop')))
      .catch(error => { if (!signal?.aborted) setNotice(messageOf(error, '背景图读取失败。')); })
  ), [sceneId, taskId]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const change = (label: string, fields: Partial<StageBackdrop>) => {
    onPreview(null);
    onCommit({ label: `背景：${label}`, operations: [{ op: 'set_backdrop', ...fields }] });
  };

  const run = async (work: () => Promise<void>, done: string) => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      await work();
      setNotice(done);
    } catch (error) {
      setNotice(messageOf(error, '操作失败，请稍后重试。'));
    } finally {
      setBusy(false);
    }
  };

  const upload = (chosen: File | undefined) => {
    if (!chosen) return;
    const refusal = uploadRefusal({ blob: chosen, kind: 'backdrop', shotId: 0, cameraId: '', width: 0, height: 0, planRevision: 0, showsLimbs: false, monochrome: false, labelled: false });
    if (refusal) { setNotice(refusal); return; }
    void run(async () => {
      const stored = await uploadCapture(taskId, sceneId, {
        blob: chosen, kind: 'backdrop', shotId: 0, cameraId: '', width: 0, height: 0,
        planRevision: 0, showsLimbs: false, monochrome: false, labelled: false,
      });
      await refresh();
      // A freshly uploaded picture is what the person wanted to see, so it goes up straight away.
      change('使用新上传的图', { kind: backdrop.kind === 'panorama' ? 'panorama' : 'image', url: stored.url });
    }, '背景图已上传。');
  };

  const kind = backdrop.kind;
  const disabled = !editable || busy;
  return (
    <section className="desk-backdrop" aria-label="场景背景">
      <h3><ImageIcon aria-hidden="true" /> 场景背景</h3>
      <p className="desk-captures__note">只在机位画面里作构图参考：导演视角不画，也不会写进任何提示词。</p>
      <div className="desk-segment is-wide" role="radiogroup" aria-label="背景类型">
        {KINDS.map(item => (
          <button
            key={item.id} type="button" role="radio" aria-checked={kind === item.id} className={kind === item.id ? 'is-active' : ''}
            disabled={disabled || ((item.id === 'image' || item.id === 'panorama') && !backdrop.url && pictures.length === 0)}
            title={(item.id === 'image' || item.id === 'panorama') && !backdrop.url && pictures.length === 0 ? '先上传一张背景图' : undefined}
            onClick={() => { if (item.id !== kind) change(item.label, { kind: item.id, ...(item.id !== 'color' && !backdrop.url && pictures[0] ? { url: pictures[0].url } : {}) }); }}
          >{item.label}</button>
        ))}
      </div>

      {kind === 'color' && (
        <label className="desk-field is-wide">
          <span>背景色</span>
          <input
            key={backdrop.color} type="color" aria-label="背景色" defaultValue={backdrop.color || '#10141c'} disabled={disabled}
            onBlur={event => { if (event.target.value !== backdrop.color) change('颜色', { color: event.target.value }); }}
            onChange={event => { if (event.target.value !== backdrop.color) change('颜色', { color: event.target.value }); }}
          />
        </label>
      )}

      {kind !== 'none' && (
        <label className="desk-field is-wide">
          <span>不透明度 {Math.round(backdrop.opacity * 100)}%</span>
          <input
            type="range" aria-label="背景不透明度" min={0} max={1} step={0.05} value={backdrop.opacity} disabled={disabled}
            onChange={event => change('不透明度', { opacity: Number(event.target.value) })}
          />
        </label>
      )}
      {kind === 'panorama' && (
        <label className="desk-field is-wide">
          <span>接缝方向 {Math.round(backdrop.yaw_deg)}°</span>
          <input
            type="range" aria-label="全景接缝方向" min={-180} max={180} step={5} value={backdrop.yaw_deg} disabled={disabled}
            onChange={event => change('接缝方向', { yaw_deg: Number(event.target.value) })}
          />
        </label>
      )}

      <button type="button" className="desk-button" disabled={disabled} onClick={() => file.current?.click()}>
        <Upload aria-hidden="true" /> 上传背景图
      </button>
      <input
        ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label="上传背景图文件"
        onChange={event => { const chosen = event.target.files?.[0]; event.target.value = ''; upload(chosen); }}
      />
      {pictures.length > 0 && (
        <ul className="desk-backdrop__list" aria-label="本场背景图">
          {pictures.map(picture => {
            const active = backdrop.url === picture.url && kind !== 'none' && kind !== 'color';
            return (
              <li key={picture.id} className={active ? 'is-active' : ''}>
                <button
                  type="button" className="desk-backdrop__thumb" aria-pressed={active} aria-label={`使用背景图 ${picture.id.slice(0, 6)}`} disabled={disabled}
                  onClick={() => change('换一张图', { kind: kind === 'panorama' ? 'panorama' : 'image', url: picture.url })}
                ><img src={picture.url} alt="" loading="lazy" /></button>
                <button
                  type="button" className="desk-icon" aria-label={`删除背景图 ${picture.id.slice(0, 6)}`} disabled={disabled}
                  onClick={() => {
                    if (!window.confirm('删除这张背景图？正在使用它的场景会回到无背景。')) return;
                    void run(async () => {
                      await deleteCapture(taskId, sceneId, picture.id);
                      await refresh();
                      if (backdrop.url === picture.url) change('已删除所用的图', { ...NO_BACKDROP, color: backdrop.color });
                    }, '已删除。');
                  }}
                ><Trash2 aria-hidden="true" /></button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="desk-toggles">
        <label><input type="checkbox" checked={inCapture} disabled={kind === 'none'} onChange={event => onInCapture(event.target.checked)} /> 导出时包含背景</label>
      </div>
      {notice && <p className="desk-captures__notice" role="status">{notice}</p>}
    </section>
  );
}
