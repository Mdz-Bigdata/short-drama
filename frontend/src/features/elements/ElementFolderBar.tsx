import { useState, type FormEvent } from 'react';
import { FolderPlus, Pencil, Trash2 } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { findPoster, type ElementItem } from './elementTypes';
import { UNFILED, type ElementFolderListing } from './elementFolders';
import './ElementFolderBar.css';

/** "Which folder is this element in", for one element. */
export function ElementFolderSelect({ item, folders, disabled, onMove }: {
  item: ElementItem;
  folders: ElementFolderListing['folders'];
  disabled?: boolean;
  onMove: (item: ElementItem, folderId: string | null) => void;
}) {
  return (
    <select
      className="element-folder-select"
      aria-label={t('“{0}”所在文件夹', [item.name])}
      value={item.folder_id ?? ''}
      disabled={disabled}
      onChange={event => onMove(item, event.target.value || null)}
    >
      <option value="">{t('未归档')}</option>
      {folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
    </select>
  );
}

interface Props {
  listing: ElementFolderListing;
  active: string;
  /** Elements on screen, to choose a cover from. */
  items: ElementItem[];
  /** The element the 3D workspace has selected: its cards have no room for a folder picker. */
  selected?: ElementItem;
  disabled?: boolean;
  onSelect: (folder: string) => void;
  onMove: (item: ElementItem, folderId: string | null) => void;
  onChanged: () => void;
  onError: (message: string) => void;
}

/** All / unfiled / the person's folders. Folders are optional: nothing here is needed to use the library. */
export function ElementFolderBar({ listing, active, items, selected, disabled, onSelect, onMove, onChanged, onError }: Props) {
  const [mode, setMode] = useState<'' | 'create' | 'rename'>('');
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const current = listing.folders.find(folder => folder.id === active);
  const covers = items.filter(item => findPoster(item));

  const run = async (work: () => Promise<unknown>, after?: () => void) => {
    setSaving(true);
    try {
      await work();
      after?.();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const name = draft.trim();
    if (!name) return;
    const close = () => { setMode(''); setDraft(''); };
    if (mode === 'create') {
      void run(() => apiRequest('/api/elements/folders', { method: 'POST', body: JSON.stringify({ name }) }), close);
    } else if (current) {
      void run(() => apiRequest(`/api/elements/folders/${current.id}`, { method: 'PATCH', body: JSON.stringify({ name }) }), close);
    }
  };

  const remove = () => {
    if (!current || !window.confirm(t('删除文件夹“{0}”？里面的元素不会被删除，会回到未归档。', [current.name]))) return;
    void run(() => apiRequest(`/api/elements/folders/${current.id}`, { method: 'DELETE' }), () => onSelect(''));
  };

  const setCover = (elementId: string) => {
    if (!current) return;
    void run(() => apiRequest(`/api/elements/folders/${current.id}`, { method: 'PATCH', body: JSON.stringify({ cover_element_id: elementId || null }) }));
  };

  const busy = saving || Boolean(disabled);
  return (
    <section className="element-folder-bar" aria-label={t('文件夹')}>
      <div className="element-folder-bar__chips">
        <button type="button" className="element-folder-chip" aria-pressed={active === ''} onClick={() => onSelect('')}>
          {t('全部')} <small>{listing.total}</small>
        </button>
        <button type="button" className="element-folder-chip" aria-pressed={active === UNFILED} onClick={() => onSelect(UNFILED)}>
          {t('未归档')} <small>{listing.unfiled}</small>
        </button>
        {listing.folders.map(folder => (
          <button key={folder.id} type="button" className="element-folder-chip" aria-pressed={active === folder.id} onClick={() => onSelect(folder.id)}>
            {folder.cover_url && <img src={apiUrl(folder.cover_url)} alt="" loading="lazy" decoding="async" />}
            {folder.name} <small>{folder.count}</small>
          </button>
        ))}
      </div>

      {mode ? (
        <form className="element-folder-bar__form" onSubmit={submit}>
          <input autoFocus value={draft} maxLength={80} aria-label={t('文件夹名称')} placeholder={t('文件夹名称')} onChange={event => setDraft(event.target.value)} />
          <button type="submit" className="element-folder-bar__action" disabled={busy || !draft.trim()}>{t('保存')}</button>
          <button type="button" className="element-folder-bar__action" onClick={() => { setMode(''); setDraft(''); }}>{t('取消')}</button>
        </form>
      ) : (
        <button type="button" className="element-folder-bar__action" disabled={busy} onClick={() => setMode('create')}>
          <FolderPlus size={14} /> {t('新建文件夹')}
        </button>
      )}

      {current && !mode && (
        <>
          <label className="element-folder-bar__label">{t('封面')}
            <select value={current.cover_element_id ?? ''} disabled={busy} onChange={event => setCover(event.target.value)}>
              <option value="">{t('无封面')}</option>
              {current.cover_element_id && !covers.some(item => item.id === current.cover_element_id) && (
                <option value={current.cover_element_id}>{t('当前封面')}</option>
              )}
              {covers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <button type="button" className="element-folder-bar__action" disabled={busy} onClick={() => { setMode('rename'); setDraft(current.name); }}>
            <Pencil size={14} /> {t('重命名')}
          </button>
          <button type="button" className="element-folder-bar__action" disabled={busy} onClick={remove}>
            <Trash2 size={14} /> {t('删除文件夹')}
          </button>
        </>
      )}

      {selected && (
        <label className="element-folder-bar__label">{t('移动“{0}”到', [selected.name])}
          <ElementFolderSelect item={selected} folders={listing.folders} disabled={busy} onMove={onMove} />
        </label>
      )}
    </section>
  );
}
