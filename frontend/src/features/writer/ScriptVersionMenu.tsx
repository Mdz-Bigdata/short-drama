import { ChevronDown, History, Save } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import type { WriterScriptVersion } from './types';
import { t } from '../../i18n';

function when(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

/** Saved versions of the screenplay: save the current one under a name, or bring an earlier one back. */
export function ScriptVersionMenu({
  versions,
  onSave,
  onRestore,
}: {
  versions: WriterScriptVersion[];
  onSave?: (label: string) => Promise<void>;
  onRestore?: (versionId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError('');
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('版本操作失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!onSave) return;
    void run('save', () => onSave(label.trim())).then(() => setLabel(''));
  };

  return (
    <div className={`writer-version-menu ${open ? 'is-open' : ''}`}>
      <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(current => !current)}>
        <History aria-hidden="true" /> {t('版本')}{versions.length ? ` (${versions.length})` : ''} <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <div className="writer-version-menu__panel" role="dialog" aria-label={t('剧本版本')}>
          {onSave && (
            <form className="writer-version-menu__save" onSubmit={save}>
              <input aria-label={t('版本名称')} value={label} maxLength={120} placeholder={t('给当前版本起个名字（可留空）')} disabled={busy === 'save'} onChange={event => setLabel(event.target.value)} />
              <button type="submit" disabled={busy === 'save'}><Save aria-hidden="true" /> {t('保存当前版本')}</button>
            </form>
          )}
          {error && <p className="writer-version-menu__error" role="alert">{error}</p>}
          {versions.length === 0 ? (
            <p className="writer-version-menu__empty">{t('还没有保存过版本。')}</p>
          ) : (
            <ul>
              {versions.map(version => (
                <li key={version.versionId}>
                  <div>
                    <strong>{version.label || version.versionId}</strong>
                    <small>{when(version.createdAt)} · {version.episodeCount} 集 · {version.sceneCount} 镜</small>
                  </div>
                  {onRestore && (
                    <button type="button" disabled={Boolean(busy)} onClick={() => void run(`restore:${version.versionId}`, () => onRestore(version.versionId))}>
                      {busy === `restore:${version.versionId}` ? t('恢复中…') : t('恢复')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
