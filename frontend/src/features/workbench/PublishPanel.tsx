import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { AlertTriangle, Check, CheckCircle2, Copy, ExternalLink, Info, ListTodo, Send, Tv } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import './PublishPanel.css';

export interface PublishPlatform {
  id: string;
  name: string;
  color: string;
  region: 'cn' | 'global';
  language: 'zh' | 'en';
  uploadUrl: string | null;
}

interface PublishCheck { level: 'error' | 'warning' | 'info' | 'todo'; text: string }

export interface PublishPackage {
  platform: string;
  name: string;
  title: string;
  description: string;
  tags: string[];
  covers: string[];
  uploadUrl: string | null;
  episodes: Array<{ episode: number; title: string; url: string; seconds: number | null }>;
  checks: PublishCheck[];
  ready: boolean;
}

export interface PublishState {
  platforms: PublishPlatform[];
  prepared: { platforms: string[]; prepared_at: string; packages: PublishPackage[] } | null;
}

const CHECK_ICON = { error: AlertTriangle, warning: AlertTriangle, info: Info, todo: ListTodo } as const;

function seconds(value: number | null): string {
  if (!value) return '';
  const total = Math.round(value);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function packageText(item: PublishPackage): string {
  const tags = item.tags.map(tag => `#${tag}`).join(' ');
  return [item.title, item.description, tags].filter(Boolean).join('\n\n');
}

/** 宣发：选平台 → 完成发布准备。只备好各平台的上架物料，发布由人在平台自己的上传页完成。 */
export function PublishPanel({ taskId }: { taskId: string }) {
  const [state, setState] = useState<PublishState | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');

  useEffect(() => {
    let active = true;
    void apiRequest<PublishState>(`/api/drama/${encodeURIComponent(taskId)}/publish`)
      .then(data => {
        if (!active) return;
        setState(data);
        setSelected(data.prepared?.platforms ?? []);
      })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : t('平台列表加载失败')); });
    return () => { active = false; };
  }, [taskId]);

  const toggle = (id: string) => setSelected(current => (
    current.includes(id) ? current.filter(item => item !== id) : [...current, id]
  ));

  const prepare = async () => {
    if (!selected.length || busy) return;
    setBusy(true);
    setError('');
    try {
      const data = await apiRequest<PublishState>(`/api/drama/${encodeURIComponent(taskId)}/publish/prepare`, {
        method: 'POST',
        body: JSON.stringify({ platforms: selected }),
      });
      setState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('发布准备失败'));
    } finally {
      setBusy(false);
    }
  };

  const copy = useCallback(async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied(current => (current === key ? '' : current)), 1600);
    } catch {
      setError(t('复制失败，请手动选中文字复制'));
    }
  }, []);

  const platforms = state?.platforms ?? [];
  const packages = state?.prepared?.packages ?? [];

  return (
    <section className="publish-panel" aria-labelledby="publish-panel-title">
      <h3 id="publish-panel-title">{t('分享至社媒')}</h3>
      <div className="publish-panel__platforms" role="group" aria-label={t('选择发布平台')}>
        {platforms.map(item => {
          const on = selected.includes(item.id);
          return (
            <button
              key={item.id}
              type="button"
              className={`publish-panel__platform${on ? ' is-selected' : ''}`}
              style={{ '--platform-color': item.color } as CSSProperties}
              aria-pressed={on}
              onClick={() => toggle(item.id)}
            >
              <Tv size={20} aria-hidden="true" />
              <span>{item.name}</span>
              {on && <Check className="publish-panel__tick" size={14} aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <button type="button" className="publish-panel__prepare" disabled={!selected.length || busy} onClick={() => { void prepare(); }}>
        <Send size={18} aria-hidden="true" />
        {busy ? t('正在准备各平台物料…') : t('完成发布准备')}
      </button>
      <p className="publish-panel__note">{t('只准备上架物料，不会自动发布；在各平台的上传页由你确认发布。')}</p>
      {error && <p className="publish-panel__error" role="alert">{error}</p>}

      {packages.length > 0 && (
        <div className="publish-panel__packages" aria-label={t('各平台发布物料')}>
          {packages.map(item => {
            const color = platforms.find(entry => entry.id === item.platform)?.color;
            return (
              <article key={item.platform} className="publish-package" style={{ '--platform-color': color } as CSSProperties}>
                <header>
                  <span className="publish-package__dot" aria-hidden="true" />
                  <strong>{item.name}</strong>
                  <em className={item.ready ? 'is-ready' : 'is-blocked'}>{item.ready ? t('可上传') : t('有阻断项')}</em>
                  <button type="button" className="publish-package__copy-all" onClick={() => { void copy(`${item.platform}:all`, packageText(item)); }}>
                    {copied === `${item.platform}:all` ? <CheckCircle2 size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                    {copied === `${item.platform}:all` ? t('已复制') : t('复制全部文案')}
                  </button>
                </header>
                <dl>
                  <div>
                    <dt>{t('标题')}</dt>
                    <dd>
                      <span>{item.title}</span>
                      <button type="button" aria-label={`${t('复制')} ${item.name} ${t('标题')}`} onClick={() => { void copy(`${item.platform}:title`, item.title); }}>
                        {copied === `${item.platform}:title` ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                      </button>
                    </dd>
                  </div>
                  <div>
                    <dt>{t('简介')}</dt>
                    <dd>
                      <span className="publish-package__description">{item.description}</span>
                      <button type="button" aria-label={`${t('复制')} ${item.name} ${t('简介')}`} onClick={() => { void copy(`${item.platform}:description`, item.description); }}>
                        {copied === `${item.platform}:description` ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                      </button>
                    </dd>
                  </div>
                  {item.tags.length > 0 && (
                    <div>
                      <dt>{t('标签')}</dt>
                      <dd className="publish-package__tags">{item.tags.map(tag => <span key={tag}>#{tag}</span>)}</dd>
                    </div>
                  )}
                  <div>
                    <dt>{t('封面')}</dt>
                    <dd>{item.covers.join(' · ')}</dd>
                  </div>
                  <div>
                    <dt>{t('成片')}</dt>
                    <dd className="publish-package__films">
                      {item.episodes.map(film => (
                        <a key={film.episode} href={film.url} target="_blank" rel="noreferrer">
                          {`第${film.episode}集 ${film.title}`}{film.seconds ? ` · ${seconds(film.seconds)}` : ''}
                        </a>
                      ))}
                    </dd>
                  </div>
                </dl>
                <ul className="publish-package__checks">
                  {item.checks.map(check => {
                    const Icon = CHECK_ICON[check.level];
                    return <li key={check.text} className={`is-${check.level}`}><Icon size={13} aria-hidden="true" />{check.text}</li>;
                  })}
                </ul>
                <footer>
                  {item.uploadUrl ? (
                    <a className="publish-package__upload" href={item.uploadUrl} target="_blank" rel="noreferrer">
                      <ExternalLink size={14} aria-hidden="true" /> {`${t('打开')} ${item.name} ${t('上传页')}`}
                    </a>
                  ) : (
                    <span className="publish-package__offline">{t('该平台没有公开上传入口，按清单走合作提交')}</span>
                  )}
                </footer>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
