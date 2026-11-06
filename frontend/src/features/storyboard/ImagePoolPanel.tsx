import { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import './ImagePoolPanel.css';

export interface PoolImage {
  id: string;
  url: string;
  kind: 'shot' | 'board' | 'cell';
  label: string;
  scene_id?: string;
  shot_id?: number;
  row?: number;
  column?: number;
}

interface PoolView {
  revision: number;
  images: PoolImage[];
}

export interface PoolShot {
  shot_id: number;
  scene_id: string;
  shot_uid?: number;
  desc?: string;
}

interface Props {
  taskId: string;
  /** The shot to assign to; without one the panel lets the person choose. */
  shot?: PoolShot | null;
  /** The shot workspace the assignment answers with, for a caller already showing it. */
  onAssigned?: (workspace: unknown) => void;
  onClose: () => void;
}

const FILTERS: ReadonlyArray<{ id: 'all' | PoolImage['kind']; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'cell', label: '切图' },
  { id: 'shot', label: '分镜图' },
  { id: 'board', label: '宫格图' },
];

function shotKey(shot: PoolShot): string {
  return `${shot.scene_id}#${shot.shot_id}`;
}

/** Every image the project has, plus grid cuts: pick one for a shot, or cut a grid image into the pool. */
export function ImagePoolPanel({ taskId, shot, onAssigned, onClose }: Props) {
  const [pool, setPool] = useState<PoolView | null>(null);
  const [shots, setShots] = useState<PoolShot[]>([]);
  const [targetKey, setTargetKey] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all');
  const [rows, setRows] = useState(3);
  const [columns, setColumns] = useState(3);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const base = `/api/drama/${encodeURIComponent(taskId)}`;

  useEffect(() => {
    let live = true;
    const first = async () => {
      try {
        const data = await apiRequest<PoolView>(`${base}/image-pool`);
        if (live) setPool(data);
      } catch (err) {
        if (live) setError(err instanceof Error ? err.message : t('图片池加载失败'));
      }
    };
    void first();
    if (!shot) {
      apiRequest<{ shots?: PoolShot[] }>(`${base}/shots/visual`)
        .then(data => { if (live) setShots(Array.isArray(data.shots) ? data.shots : []); })
        .catch(() => undefined);
    }
    return () => { live = false; };
  }, [base, shot]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const target = shot ?? shots.find(item => shotKey(item) === targetKey) ?? null;
  const selected = pool?.images.find(image => image.id === selectedId) ?? null;
  const visible = (pool?.images ?? []).filter(image => filter === 'all' || image.kind === filter);

  const run = useCallback(async (key: string, work: () => Promise<void>) => {
    setBusy(key);
    setError('');
    setStatus('');
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setBusy('');
    }
  }, []);

  const split = () => {
    if (!selected || !pool) return;
    void run('split', async () => {
      const data = await apiRequest<PoolView & { added: string[] }>(`${base}/image-pool/split`, {
        method: 'POST',
        body: JSON.stringify({ image_id: selected.id, rows, columns, revision: pool.revision }),
      });
      setPool(data);
      setFilter('cell');
      setSelectedId(data.added[0] ?? '');
      setStatus(t('切出 {count} 张，已放进图片池。', { count: data.added.length }));
    });
  };

  const rebuild = () => {
    void run('rebuild', async () => {
      const data = await apiRequest<PoolView>(`${base}/image-pool/rebuild`, { method: 'POST', body: JSON.stringify({}) });
      setPool(data);
      setStatus(t('已按项目记录和磁盘文件重建图片池。'));
    });
  };

  const assign = () => {
    if (!selected || !target) return;
    void run('assign', async () => {
      const workspace = await apiRequest<unknown>(`${base}/image-pool/assign`, {
        method: 'POST',
        body: JSON.stringify({ image_id: selected.id, shot_id: target.shot_id, scene_id: target.scene_id, shot_uid: target.shot_uid ?? null }),
      });
      setStatus(t('已设为这一镜的分镜图；重跑第 5 阶段后视频才会用上。'));
      onAssigned?.(workspace);
    });
  };

  const disabled = Boolean(busy);
  return (
    <div className="image-pool" role="dialog" aria-modal="true" aria-label={t('图片池')}>
      <div className="image-pool__panel">
        <header className="image-pool__head">
          <h2>{t('图片池')}</h2>
          <button type="button" className="image-pool__icon" onClick={onClose} aria-label={t('关闭')}><X size={16} /></button>
        </header>

        <div className="image-pool__controls">
          <label>{t('类型')}
            <select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}>
              {FILTERS.map(option => <option key={option.id} value={option.id}>{t(option.label)}</option>)}
            </select>
          </label>
          <label>{t('行')}
            <input type="number" min={1} max={8} value={rows} onChange={event => setRows(Number(event.target.value) || 1)} />
          </label>
          <label>{t('列')}
            <input type="number" min={1} max={8} value={columns} onChange={event => setColumns(Number(event.target.value) || 1)} />
          </label>
          <button type="button" className="image-pool__action" disabled={disabled || !selected || rows * columns < 2} onClick={split}>
            {busy === 'split' ? t('切分中…') : t('切分选中的图')}
          </button>
          <button type="button" className="image-pool__action" disabled={disabled} onClick={rebuild}>{t('重建索引')}</button>
          <span className="image-pool__spacer" />
          {!shot && (
            <label>{t('给哪一镜')}
              <select value={targetKey} onChange={event => setTargetKey(event.target.value)}>
                <option value="">{t('选择镜头')}</option>
                {shots.map(item => (
                  <option key={shotKey(item)} value={shotKey(item)}>{item.scene_id} · {item.shot_id}{item.desc ? ` ${item.desc.slice(0, 16)}` : ''}</option>
                ))}
              </select>
            </label>
          )}
          <button type="button" className="image-pool__action image-pool__action--primary" disabled={disabled || !selected || !target} onClick={assign}>
            {shot ? t('用于 {scene} 第 {shot} 镜', { scene: shot.scene_id, shot: shot.shot_id }) : t('用于这一镜')}
          </button>
        </div>

        {error && <p className="image-pool__error" role="alert">{error}</p>}
        {status && <p className="image-pool__status" role="status">{status}</p>}

        <ul className="image-pool__grid">
          {pool && visible.length === 0 && <li className="image-pool__empty">{t('这里还没有图片；第 4 阶段出分镜图后会出现在这里。')}</li>}
          {visible.map(image => (
            <li key={image.id}>
              <button type="button" className="image-pool__item" aria-pressed={selectedId === image.id} onClick={() => setSelectedId(image.id)}>
                <img src={apiUrl(image.url)} alt={image.label} loading="lazy" decoding="async" />
                <span title={image.label}>{image.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
