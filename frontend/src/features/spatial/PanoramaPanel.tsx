import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { fetchSpatialPlan, patchSpatialPlan } from './spatialApi';
import './PanoramaPanel.css';

// three.js is large and only this view needs it here, so it arrives when a panorama is on screen.
const PanoramaViewer = lazy(() => import('./three/PanoramaViewer'));

interface PanoramaItem {
  id: string;
  url: string;
  description: string;
  source: 'text' | 'image';
  width: number;
  height: number;
  warning?: string;
}

interface PanoramaList {
  panoramas: PanoramaItem[];
}

interface Props {
  taskId: string;
  sceneId: string;
  onClose: () => void;
}

/** Generate a scene's 360° panorama from text or a picture, look around it, and hand it to the director desk. */
export function PanoramaPanel({ taskId, sceneId, onClose }: Props) {
  const [items, setItems] = useState<PanoramaItem[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [description, setDescription] = useState('');
  const [reference, setReference] = useState<File | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const file = useRef<HTMLInputElement>(null);
  const path = `/api/drama/${encodeURIComponent(taskId)}/panoramas/scenes/${encodeURIComponent(sceneId)}`;

  useEffect(() => {
    let live = true;
    const first = async () => {
      try {
        const data = await apiRequest<PanoramaList>(path);
        if (!live) return;
        setItems(data.panoramas);
        setSelectedId(data.panoramas[data.panoramas.length - 1]?.id ?? '');
      } catch (err) {
        if (live) setError(err instanceof Error ? err.message : t('全景加载失败'));
      }
    };
    void first();
    return () => { live = false; };
  }, [path]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const selected = items.find(item => item.id === selectedId) ?? null;

  const generate = async () => {
    if (!window.confirm(t('生成全景会调用一次图像模型并产生费用，确定继续？'))) return;
    setBusy('generate');
    setError('');
    setStatus('');
    try {
      const form = new FormData();
      form.append('description', description.trim());
      if (reference) form.append('reference', reference);
      const data = await apiRequest<PanoramaList>(path, { method: 'POST', body: form });
      setItems(data.panoramas);
      setSelectedId(data.panoramas[data.panoramas.length - 1]?.id ?? '');
      setStatus(t('全景已生成。'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('全景生成失败'));
    } finally {
      setBusy('');
    }
  };

  const applyBackdrop = async () => {
    if (!selected) return;
    setBusy('backdrop');
    setError('');
    setStatus('');
    try {
      // The revision is read right here, so the person is not told about an edit they made a minute ago.
      const current = await fetchSpatialPlan(taskId, sceneId);
      await patchSpatialPlan(taskId, sceneId, current.plan.revision, [
        { op: 'set_backdrop', kind: 'panorama', url: selected.url, yaw_deg: 0 },
      ], { solve: false });
      setStatus(t('已设为这一场导演台的全景背景。'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('设置背景失败'));
    } finally {
      setBusy('');
    }
  };

  const disabled = Boolean(busy);
  return (
    <div className="panorama-panel" role="dialog" aria-modal="true" aria-label={t('360° 全景')}>
      <div className="panorama-panel__body">
        <header className="panorama-panel__head">
          <h2>{t('360° 全景')} · {sceneId}</h2>
          <button type="button" className="panorama-panel__icon" onClick={onClose} aria-label={t('关闭')}><X size={16} /></button>
        </header>

        <div className="panorama-panel__form">
          <label>{t('这个地点什么样')}
            <textarea
              value={description}
              maxLength={1500}
              placeholder={t('留空则按剧本里这一场的地点生成')}
              onChange={event => setDescription(event.target.value)}
            />
          </label>
          <div className="panorama-panel__row">
            <input
              ref={file} type="file" hidden accept="image/png,image/jpeg,image/webp" aria-label={t('选择参考图')}
              onChange={event => { setReference(event.target.files?.[0] ?? null); event.target.value = ''; }}
            />
            <button type="button" className="panorama-panel__button" disabled={disabled} onClick={() => file.current?.click()}>
              {reference ? t('换一张参考图') : t('从图片生成（可选）')}
            </button>
            {reference && (
              <>
                <span className="panorama-panel__empty">{reference.name}</span>
                <button type="button" className="panorama-panel__button" disabled={disabled} onClick={() => setReference(null)}>{t('移除')}</button>
              </>
            )}
            <button type="button" className="panorama-panel__button panorama-panel__button--primary" disabled={disabled} onClick={() => { void generate(); }}>
              {busy === 'generate' ? t('全景生成中…') : t('生成全景')}
            </button>
          </div>
        </div>

        {error && <p className="panorama-panel__error" role="alert">{error}</p>}
        {status && <p className="panorama-panel__status" role="status">{status}</p>}
        {selected?.warning && <p className="panorama-panel__warning">{selected.warning}</p>}

        {selected ? (
          <>
            <div className="panorama-panel__stage">
              <Suspense fallback={<div className="panorama-panel__loading">{t('正在加载全景查看器…')}</div>}>
                <PanoramaViewer key={selected.id} url={apiUrl(selected.url)} alt={selected.description || t('全景图')} />
              </Suspense>
            </div>
            <div className="panorama-panel__row">
              <button type="button" className="panorama-panel__button panorama-panel__button--primary" disabled={disabled} onClick={() => { void applyBackdrop(); }}>
                {busy === 'backdrop' ? t('设置中…') : t('用作导演台背景')}
              </button>
              <span className="panorama-panel__empty">{selected.width}×{selected.height}</span>
            </div>
          </>
        ) : (
          <p className="panorama-panel__empty">{t('这一场还没有全景。')}</p>
        )}

        {items.length > 1 && (
          <ul className="panorama-panel__list" aria-label={t('这一场的全景')}>
            {items.map((item, index) => (
              <li key={item.id}>
                <button type="button" className="panorama-panel__thumb" aria-pressed={item.id === selectedId} aria-label={t('全景 {0}', [index + 1])} onClick={() => setSelectedId(item.id)}>
                  <img src={apiUrl(item.url)} alt="" loading="lazy" decoding="async" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
