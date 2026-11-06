import { useCallback, useEffect, useState } from 'react';
import { Pin, PinOff, Trash2, X } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import './ProjectMemory.css';

export type MemoryKind = 'preference' | 'decision' | 'fact';

export interface MemoryEntry {
  id: string;
  text: string;
  kind: MemoryKind;
  source: 'user' | 'model';
  pinned: boolean;
  updated_at?: string;
}

export interface TokenTotals {
  input: number;
  output: number;
  reasoning: number;
  cached_input: number;
  reused_calls: number;
  reused_saved: number;
  system_chars_saved: number;
}

export interface MemoryView {
  entries: MemoryEntry[];
  prompt_profile: 'standard' | 'lean';
  tokens: TokenTotals;
}

const KIND_LABELS: Record<MemoryKind, string> = { preference: '偏好', decision: '决定', fact: '设定' };

function count(value: number) {
  return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : String(value);
}

interface Props {
  taskId: string;
  onClose: () => void;
}

/** What the project remembers across conversations, and what its text calls have cost and saved. */
export function ProjectMemory({ taskId, onClose }: Props) {
  const base = `/api/drama/${encodeURIComponent(taskId)}/memory`;
  const [view, setView] = useState<MemoryView | null>(null);
  const [text, setText] = useState('');
  const [kind, setKind] = useState<MemoryKind>('decision');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (work: () => Promise<MemoryView>) => {
    setBusy(true);
    setProblem('');
    try {
      setView(await work());
      return true;
    } catch (error) {
      setProblem(error instanceof Error && error.message ? error.message : t('操作失败，请稍后重试。'));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<MemoryView>(base, { signal: controller.signal }).then(setView).catch(error => {
      if (!controller.signal.aborted) setProblem(error instanceof Error && error.message ? error.message : t('操作失败，请稍后重试。'));
    });
    return () => controller.abort();
  }, [base]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const add = async () => {
    const clean = text.trim();
    if (!clean) return;
    const done = await run(() => apiRequest<MemoryView>(base, { method: 'POST', body: JSON.stringify({ text: clean, kind, pinned: true }) }));
    if (done) setText('');
  };
  const entries = [...(view?.entries ?? [])].sort((a, b) => Number(b.pinned) - Number(a.pinned));
  const tokens = view?.tokens;
  const cachedShare = tokens && tokens.input > 0 ? Math.round((tokens.cached_input / tokens.input) * 100) : 0;

  return (
    <div className="project-memory" role="dialog" aria-modal="true" aria-label={t('项目记忆')}>
      <div className="project-memory__panel">
        <header>
          <h2>{t('项目记忆')}</h2>
          <button type="button" aria-label={t('关闭')} onClick={onClose}><X size={16} aria-hidden="true" /></button>
        </header>
        <p className="project-memory__note">{t('这里记的是以后都要遵守的事。只有和当前任务相关的才会发给模型，所以不用反复交代，也不用每次带上整段聊天。在聊天里发「/记住 ……」或「/忘记 ……」也可以，不花 token。')}</p>
        {problem && <p className="project-memory__problem" role="alert">{problem}</p>}

        <form className="project-memory__add" onSubmit={event => { event.preventDefault(); void add(); }}>
          <select aria-label={t('类型')} value={kind} onChange={event => setKind(event.target.value as MemoryKind)}>
            {(Object.keys(KIND_LABELS) as MemoryKind[]).map(item => <option key={item} value={item}>{t(KIND_LABELS[item])}</option>)}
          </select>
          <input aria-label={t('要记住的事')} maxLength={200} value={text} placeholder={t('例如：女主从不穿红色；全片不要旁白')} onChange={event => setText(event.target.value)} />
          <button type="submit" disabled={busy || !text.trim()}>{t('记住')}</button>
        </form>

        <ul className="project-memory__list" aria-label={t('记忆列表')}>
          {entries.map(entry => (
            <li key={entry.id} className={entry.pinned ? 'is-pinned' : ''}>
              <span className="project-memory__kind">{t(KIND_LABELS[entry.kind] ?? KIND_LABELS.decision)}</span>
              <p>{entry.text}{entry.source === 'model' && <small>{t('模型记的')}</small>}</p>
              <button
                type="button" aria-label={t(entry.pinned ? '取消固定：{text}' : '固定：{text}', { text: entry.text })} aria-pressed={entry.pinned} disabled={busy}
                title={t('固定的记忆每次都发给模型')}
                onClick={() => { void run(() => apiRequest<MemoryView>(`${base}/${entry.id}`, { method: 'PATCH', body: JSON.stringify({ pinned: !entry.pinned }) })); }}
              >
                {entry.pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
              </button>
              <button
                type="button" aria-label={t('删除：{text}', { text: entry.text })} disabled={busy}
                onClick={() => { void run(() => apiRequest<MemoryView>(`${base}/${entry.id}`, { method: 'DELETE' })); }}
              >
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
          {view && !entries.length && <li className="project-memory__empty">{t('还没有记忆。')}</li>}
        </ul>

        <section className="project-memory__tokens" aria-label={t('Token 用量')}>
          <h3>{t('Token 用量')}</h3>
          {tokens && (
            <dl>
              <div><dt>{t('输入')}</dt><dd>{count(tokens.input)}</dd></div>
              <div><dt>{t('输出')}</dt><dd>{count(tokens.output)}</dd></div>
              <div><dt>{t('供应商缓存命中')}</dt><dd>{count(tokens.cached_input)}{cachedShare > 0 && `（${cachedShare}%）`}</dd></div>
              <div><dt>{t('复用答案省下')}</dt><dd>{count(tokens.reused_saved)} · {tokens.reused_calls} {t('次')}</dd></div>
            </dl>
          )}
          <label className="project-memory__lean">
            <input
              type="checkbox" checked={view?.prompt_profile === 'lean'} disabled={!view || busy}
              onChange={event => { void run(() => apiRequest<MemoryView>(`${base}/prompt-profile`, { method: 'PUT', body: JSON.stringify({ profile: event.target.checked ? 'lean' : 'standard' }) })); }}
            />
            <span>{t('省 token 模式：分镜阶段的指南减半，每次少约三成输入 token；但这部分大多已享受缓存折扣，实际省钱不多，多格场次的影响尚未验证')}</span>
          </label>
        </section>
      </div>
    </div>
  );
}
