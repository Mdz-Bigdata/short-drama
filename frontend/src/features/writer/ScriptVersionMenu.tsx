import { ChevronDown, History, Save } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import type { WriterScriptVersion } from './types';
import { apiRequest } from '../../api/client';
import { t } from '../../i18n';

/** What changed from a saved version to the screenplay as it is now, by episode. */
export interface ScriptVersionCompare {
  version_id: string;
  label: string;
  identical: boolean;
  summary: { same: number; changed: number; added: number; removed: number; lines_added: number; lines_removed: number };
  episodes: Array<{
    episode: number; status: string; label: string; title: string; lines_added: number; lines_removed: number;
    changes: Array<{ old: string[]; new: string[] }>; more_changes: number;
  }>;
}

function when(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

/** Saved versions of the screenplay: save the current one under a name, or bring an earlier one back. */
export function ScriptVersionMenu({
  versions,
  onSave,
  onRestore,
  taskId,
}: {
  versions: WriterScriptVersion[];
  onSave?: (label: string) => Promise<void>;
  onRestore?: (versionId: string) => Promise<void>;
  /** With a project id, each version can be compared with the current screenplay before it is brought back. */
  taskId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [compared, setCompared] = useState<ScriptVersionCompare | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // The panel floats over the board: a click elsewhere or Esc puts it away.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      toggleRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError('');
    try {
      await action();
      return true;
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('版本操作失败，请稍后重试。'));
      return false;
    } finally {
      setBusy('');
    }
  };

  const compare = (versionId: string) => run(`compare:${versionId}`, async () => {
    setCompared(await apiRequest<ScriptVersionCompare>(
      `/api/drama/${encodeURIComponent(taskId ?? '')}/script/versions/${encodeURIComponent(versionId)}/compare`,
    ));
  });

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!onSave) return;
    // A failed save keeps the name the writer typed, ready to try again.
    void run('save', () => onSave(label.trim())).then(saved => { if (saved) setLabel(''); });
  };

  return (
    <div ref={menuRef} className={`writer-version-menu ${open ? 'is-open' : ''}`}>
      <button ref={toggleRef} type="button" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(current => !current)}>
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
                  {taskId && (
                    <button type="button" disabled={Boolean(busy)} aria-pressed={compared?.version_id === version.versionId} onClick={() => void compare(version.versionId)}>
                      {busy === `compare:${version.versionId}` ? t('对比中…') : t('对比')}
                    </button>
                  )}
                  {onRestore && (
                    <button type="button" disabled={Boolean(busy)} onClick={() => void run(`restore:${version.versionId}`, () => onRestore(version.versionId))}>
                      {busy === `restore:${version.versionId}` ? t('恢复中…') : t('恢复')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {compared && (
            <section className="writer-version-menu__compare" aria-label={t('版本对比')}>
              <strong>{t('「{0}」和现在的剧本相比', [compared.label || compared.version_id])}</strong>
              {compared.identical ? (
                <p className="writer-version-menu__empty">{t('内容一样，没有改动。')}</p>
              ) : (
                <>
                  <small>
                    {t('改了 {0} 集 · 新增 {1} 集 · 删掉 {2} 集 · 多了 {3} 行 · 少了 {4} 行', [
                      compared.summary.changed, compared.summary.added, compared.summary.removed, compared.summary.lines_added, compared.summary.lines_removed,
                    ])}
                  </small>
                  <ol>
                    {compared.episodes.map(row => (
                      <li key={row.episode} className={`is-${row.status}`}>
                        <span>{row.title} · {row.label}{row.status === 'changed' ? ` (+${row.lines_added} / -${row.lines_removed})` : ''}</span>
                        {row.changes.map((change, index) => (
                          <div key={index} className="writer-version-menu__change">
                            {change.old.map((line, at) => <del key={`o${at}`}>{line}</del>)}
                            {change.new.map((line, at) => <ins key={`n${at}`}>{line}</ins>)}
                          </div>
                        ))}
                        {row.more_changes > 0 && <small>{t('还有 {0} 处改动没有列出', [row.more_changes])}</small>}
                      </li>
                    ))}
                  </ol>
                </>
              )}
              <button type="button" onClick={() => setCompared(null)}>{t('收起对比')}</button>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
