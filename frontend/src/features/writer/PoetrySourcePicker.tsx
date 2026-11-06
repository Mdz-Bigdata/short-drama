import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';


export interface PoetryAuthor {
  collection: string;
  author: string;
  dynasty: string;
  count: number;
}

const WHOLE_SHELF = '全部';

/**
 * Which of the poetry library's authors the Writer may quote and rework. The list is saved with the project;
 * choosing nothing leaves the library out of the prompt entirely, which keeps every other project's prompt as it was.
 */
export function PoetrySourcePicker({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
  const [authors, setAuthors] = useState<PoetryAuthor[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    apiRequest<{ items: PoetryAuthor[] }>('/api/poetry/authors')
      .then(data => { if (alive) setAuthors(data.items); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : t('诗词库加载失败')); });
    return () => { alive = false; };
  }, []);

  const whole = value.includes(WHOLE_SHELF);
  const toggle = (name: string) => {
    if (name === WHOLE_SHELF) {
      onChange(whole ? [] : [WHOLE_SHELF]);
      return;
    }
    const rest = value.filter(item => item !== WHOLE_SHELF);
    onChange(rest.includes(name) ? rest.filter(item => item !== name) : [...rest, name]);
  };

  return (
    <div className="poetry-picker" role="group" aria-label={t('诗词取材')}>
      <header>
        <BookOpen size={15} />
        <div><strong>{t('诗词取材')}</strong><small>{t('编剧可引用或化用这些作者的作品。不选则不使用诗词库。')}</small></div>
      </header>
      {error && <p className="poetry-picker__error" role="alert">{error}</p>}
      {!authors && !error && <p className="poetry-picker__hint">{t('正在加载…')}</p>}
      {authors && (
        <div className="poetry-picker__list">
          <label className={whole ? 'is-on' : ''}>
            <input type="checkbox" checked={whole} onChange={() => toggle(WHOLE_SHELF)} /> {t('整个诗词库')}
          </label>
          {authors.map(item => (
            <label key={item.collection} className={!whole && value.includes(item.author) ? 'is-on' : ''}>
              <input type="checkbox" disabled={whole} checked={whole || value.includes(item.author)} onChange={() => toggle(item.author)} />
              {item.author}<small>{item.dynasty} · {item.count}</small>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
