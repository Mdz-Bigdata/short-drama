import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { LoaderCircle, Pencil, X } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import type { ElementItem } from './elementTypes';
import { affectedShots, fetchUsages, syncCounts, type WithSync } from './elementVersions';
import './ElementVersionHistory.css';

export interface RenameResult {
  updated: ElementItem | null;
  name: string;
  counts: { shotsMarked: number; clipsMarked: number };
}

/**
 * 改资产名字的小窗：先说有几个镜头引用了它(改名会让这些镜头标成需重画)，
 * 改完再说后端实际标了几个。
 */
export function RenameAssetDialog({ item, kindLabel, onClose, onRenamed }: {
  item: ElementItem;
  kindLabel: string;
  onClose: () => void;
  /** 改名成功(对话框还开着，显示结果)。 */
  onRenamed: (result: RenameResult) => void;
}) {
  const [draft, setDraft] = useState(item.name);
  const [usageCount, setUsageCount] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<RenameResult | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    void fetchUsages(item.id)
      .then(items => { if (live) setUsageCount(items.length); })
      .catch(() => { if (live) setUsageCount(null); });
    input.current?.focus();
    input.current?.select();
    return () => { live = false; };
  }, [item.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, saving]);

  const trimmed = draft.trim();
  const submit = async () => {
    if (saving || !trimmed || trimmed === item.name) return;
    setSaving(true);
    setError('');
    try {
      const response = await apiRequest<WithSync<ElementItem> | null>(`/api/elements/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: trimmed }),
      });
      const updated = response && typeof response === 'object' && 'id' in response ? response : null;
      const result: RenameResult = { updated, name: trimmed, counts: syncCounts(response) };
      setDone(result);
      onRenamed(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('重命名{0}资产失败', [kindLabel]));
    } finally {
      setSaving(false);
    }
  };

  const title = t('重命名{0}资产', [kindLabel]);
  const marked = done ? affectedShots(done.counts) : 0;
  return createPortal(
    <div className="element-versions__backdrop" onClick={event => { if (event.target === event.currentTarget && !saving) onClose(); }}>
      <div className="element-versions element-rename-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <header className="element-versions__header">
          <h2><Pencil size={15} aria-hidden="true" /> {title}</h2>
          <button type="button" onClick={onClose} aria-label={t('关闭')} disabled={saving}><X size={16} /></button>
        </header>
        {done ? (
          <>
            <p className="element-rename-dialog__note" role="status">
              {marked > 0
                ? t('已重命名为“{0}”，{1} 个镜头已标记为需重画。', [done.name, marked])
                : t('已重命名为“{0}”。', [done.name])}
            </p>
            <div className="element-rename-dialog__actions">
              <button type="button" onClick={onClose}>{t('完成')}</button>
            </div>
          </>
        ) : (
          <form onSubmit={event => { event.preventDefault(); void submit(); }}>
            <label>{t('新名称')}
              <input ref={input} value={draft} onChange={event => setDraft(event.target.value)} disabled={saving} />
            </label>
            {usageCount !== null && usageCount > 0 && (
              <p className="element-rename-dialog__note">{t('若改名，{0} 个镜头引用了它，会标记为需重画', [usageCount])}</p>
            )}
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="element-rename-dialog__actions">
              <button type="button" onClick={onClose} disabled={saving}>{t('取消')}</button>
              <button type="submit" disabled={saving || !trimmed || trimmed === item.name} aria-busy={saving}>
                {saving && <LoaderCircle className="spin" size={13} />} {t('保存名称')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  );
}
