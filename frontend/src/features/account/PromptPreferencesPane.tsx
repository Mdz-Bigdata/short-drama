import { useEffect, useState } from 'react';
import { LoaderCircle, PenLine } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { isChanged, type Draft, type Mode } from './promptPreferenceDraft';
import './PromptPreferencesPane.css';

interface ModeInfo {
  id: Mode;
  label: string;
  hint: string;
}

interface Operation {
  id: string;
  stage: number;
  label: string;
  description: string;
  modes: Mode[];
  why_no_rewrite: string;
  platform_text: string;
  protected: string;
  mode: Mode;
  text: string;
}

export interface PromptPreferenceCatalogue {
  text_limit: number;
  modes: ModeInfo[];
  operations: Operation[];
}

function draftsOf(catalogue: PromptPreferenceCatalogue): Record<string, Draft> {
  return Object.fromEntries(catalogue.operations.map(item => [item.id, { mode: item.mode, text: item.text }]));
}

/** Per stage agent: follow the platform's creative method, add to it, or (where offered) write one's own. */
export function PromptPreferencesPane() {
  const [catalogue, setCatalogue] = useState<PromptPreferenceCatalogue | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [savedId, setSavedId] = useState('');

  const accept = (data: PromptPreferenceCatalogue, only?: string) => {
    if (!Array.isArray(data?.operations) || !Array.isArray(data?.modes)) return;
    setCatalogue(data);
    setDrafts(current => (only ? { ...current, [only]: draftsOf(data)[only] } : draftsOf(data)));
  };

  useEffect(() => {
    let active = true;
    apiRequest<PromptPreferenceCatalogue>('/api/users/me/prompt-preferences')
      .then(data => { if (active) accept(data); })
      .catch(() => { /* The pane stays out of the page; the rest of the account centre does not depend on it. */ });
    return () => { active = false; };
  }, []);

  if (!catalogue) return null;

  const save = async (operation: Operation) => {
    const draft = drafts[operation.id];
    setBusy(operation.id);
    setError('');
    setSavedId('');
    try {
      accept(await apiRequest<PromptPreferenceCatalogue>(
        `/api/users/me/prompt-preferences/${encodeURIComponent(operation.id)}`,
        { method: 'PUT', body: JSON.stringify({ mode: draft.mode, text: draft.mode === 'follow' ? '' : draft.text }) },
      ), operation.id);
      setSavedId(operation.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('偏好没有保存'));
    } finally {
      setBusy('');
    }
  };

  const edit = (id: string, change: Partial<Draft>) => {
    setSavedId('');
    setDrafts(current => ({ ...current, [id]: { ...current[id], ...change } }));
  };

  return (
    <section className="prompt-preferences" aria-labelledby="prompt-preferences-title">
      <div className="section-title">
        <PenLine size={20} />
        <div>
          <h2 id="prompt-preferences-title">{t('提示词偏好')}</h2>
          <p>{t('每个环节开头的创作方法可以跟随平台、追加你的几条，或换成你自己的；资料、本片事实和输出格式始终由平台给出，不受这里影响。只对你自己的项目生效。')}</p>
        </div>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <div className="prompt-preferences__list">
        {catalogue.operations.map(operation => {
          const draft = drafts[operation.id] ?? { mode: operation.mode, text: operation.text };
          const length = draft.text.trim().length;
          const writes = draft.mode !== 'follow';
          // Text left in the box after switching back to follow is not sent, so it cannot be over the limit.
          const over = writes && length > catalogue.text_limit;
          const changed = isChanged({ mode: operation.mode, text: operation.text }, draft);
          return (
            <article className="prompt-preferences__item" key={operation.id} aria-label={operation.label}>
              <header>
                <strong>{operation.label}</strong>
                <span>{operation.description}</span>
              </header>
              <div className="prompt-preferences__modes" role="radiogroup" aria-label={t('{0} 的方式', [operation.label])}>
                {catalogue.modes.filter(mode => operation.modes.includes(mode.id)).map(mode => (
                  <label key={mode.id} title={mode.hint} className={draft.mode === mode.id ? 'is-chosen' : ''}>
                    <input
                      type="radio" name={`prompt-preference-${operation.id}`} value={mode.id}
                      checked={draft.mode === mode.id} onChange={() => edit(operation.id, { mode: mode.id })}
                    />
                    {mode.label}
                  </label>
                ))}
              </div>
              <p className="account-help">
                {catalogue.modes.find(mode => mode.id === draft.mode)?.hint}
                {operation.why_no_rewrite && ` ${operation.why_no_rewrite}`}
              </p>
              {writes && (
                <>
                  <textarea
                    aria-label={t('{0} 的偏好内容', [operation.label])} rows={4} value={draft.text}
                    onChange={event => edit(operation.id, { text: event.target.value })}
                    placeholder={draft.mode === 'append' ? t('例如：少用旁白，多用动作交代；反派不要脸谱化') : t('写下你自己的创作方法')}
                  />
                  <small className={over ? 'is-over' : ''}>{t('{0} / {1} 字', [length, catalogue.text_limit])}</small>
                </>
              )}
              {draft.mode === 'rewrite' && operation.platform_text && (
                <details>
                  <summary>{t('平台默认的方法（会被你的内容代替）')}</summary>
                  <pre>{operation.platform_text}</pre>
                  {operation.protected && <p className="account-help">{t('这一句仍会保留：{0}', [operation.protected])}</p>}
                </details>
              )}
              <div className="prompt-preferences__actions">
                {savedId === operation.id && <span role="status">{t('已保存')}</span>}
                <button
                  type="button" className="primary-action" onClick={() => void save(operation)}
                  disabled={!changed || busy === operation.id || over || (writes && length === 0)}
                >
                  {busy === operation.id && <LoaderCircle className="spin" size={14} />}
                  {t('保存')}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
