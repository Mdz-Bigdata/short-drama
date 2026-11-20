import { useEffect, useMemo, useState } from 'react';
import { History, LoaderCircle, X } from 'lucide-react';

import { t } from '../../i18n';
import { fetchCanvasVersion } from './canvasBeefApi';
import { boundsOf, diffVersions } from './canvasBeefVersionDiff';
import type { CanvasDoc, CanvasRecord } from './canvasTypes';
import './CanvasBeef.css';

export interface CanvasBeefVersionPreviewProps {
  projectId: string;
  canvasId: string;
  version: number;
  current: CanvasDoc;
  onRestore: (version: number) => void;
  onClose: () => void;
}

/** An older version drawn small, read only, with what restoring it would change; restoring stays a separate click. */
export function CanvasBeefVersionPreview({ projectId, canvasId, version, current, onRestore, onClose }: CanvasBeefVersionPreviewProps) {
  // What was read is kept with the version it belongs to, so a switch to another version never shows the old one.
  const [loaded, setLoaded] = useState<{ version: number; record?: CanvasRecord; error?: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchCanvasVersion(projectId, canvasId, version, controller.signal)
      .then(record => setLoaded({ version, record }))
      .catch(err => { if (!controller.signal.aborted) setLoaded({ version, error: err instanceof Error ? err.message : t('这一版读不出来') }); });
    return () => controller.abort();
  }, [projectId, canvasId, version]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const older = loaded?.version === version ? loaded.record ?? null : null;
  const error = loaded?.version === version ? loaded.error ?? '' : '';

  const diff = useMemo(() => (older ? diffVersions(current, older) : null), [current, older]);
  const status = useMemo(() => {
    const map = new Map<string, 'added' | 'changed'>();
    diff?.added.forEach(node => map.set(node.id, 'added'));
    diff?.changed.forEach(node => map.set(node.id, 'changed'));
    return map;
  }, [diff]);
  const box = older ? boundsOf(older.nodes) : null;

  return (
    <div className="canvas-beef-backdrop" role="presentation" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="canvas-beef-version" role="dialog" aria-modal="true" aria-label={t('预览第 {0} 版', [version])}>
        <header>
          <strong><History size={14} aria-hidden="true" /> {t('预览第 {0} 版（只读）', [version])}</strong>
          <button type="button" onClick={onClose} aria-label={t('关闭')}><X size={15} /></button>
        </header>
        {error && <div className="inline-error" role="alert">{error}</div>}
        {!older && !error && <div className="canvas-beef-muted"><LoaderCircle className="spin" size={14} /> {t('正在读取这一版…')}</div>}
        {older && box && diff && (
          <>
            <svg className="canvas-beef-version__map" viewBox={`${box.x - 40} ${box.y - 40} ${box.width + 80} ${box.height + 80}`} role="img"
              aria-label={t('第 {0} 版共 {1} 个节点', [version, older.nodes.length])}>
              {older.nodes.map(node => (
                <rect key={node.id} x={node.x} y={node.y} width={node.width} height={node.height} rx={12}
                  className={`canvas-beef-version__node is-${status.get(node.id) ?? 'same'}`} />
              ))}
            </svg>
            <ul className="canvas-beef-version__diff">
              <li>{t('恢复后会多出 {0} 个现在没有的节点', [diff.added.length])}</li>
              <li>{t('会去掉 {0} 个现在才有的节点', [diff.removed.length])}</li>
              <li>{t('会改回 {0} 个节点的位置或内容', [diff.changed.length])}</li>
              <li>{t('连线：多出 {0} 条，去掉 {1} 条', [diff.edgesAdded, diff.edgesRemoved])}</li>
            </ul>
            <p className="canvas-beef-muted">{t('恢复会存成新的一版，现在这一版仍留在历史里。')}</p>
          </>
        )}
        <footer>
          <span className="canvas-beef-spacer" />
          <button type="button" onClick={onClose}>{t('关闭')}</button>
          <button type="button" className="is-primary" disabled={!older} onClick={() => onRestore(version)}>{t('恢复这一版')}</button>
        </footer>
      </div>
    </div>
  );
}
