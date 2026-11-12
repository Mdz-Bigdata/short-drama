import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { STORY_PHASES, type WriterTimelineEvent } from './types';
import { t } from '../../i18n';

interface EventForm {
  index: number | null;
  phase: string;
  title: string;
  desc: string;
  points: string;
}

function cleanEvent(event: WriterTimelineEvent) {
  return {
    phase: String(event.phase || '剧情节点'),
    title: String(event.title || ''),
    desc: String(event.desc || ''),
    points: Array.isArray(event.points) ? event.points.map(point => String(point)) : [],
  };
}

/** The story as a vertical line of event nodes: a phase tag, a title, a summary and its beats; each node can be added, edited or removed. */
export function StoryEventTimeline({
  events,
  authored = false,
  onSave,
}: {
  events: WriterTimelineEvent[];
  authored?: boolean;
  onSave?: (events: Array<{ phase: string; title: string; desc: string; points: string[] }>) => Promise<void>;
}) {
  const [form, setForm] = useState<EventForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [formOpened, setFormOpened] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!formOpened) return;
    formRef.current?.scrollIntoView?.({ block: 'nearest' });
    titleRef.current?.focus({ preventScroll: true });
  }, [formOpened]);

  const commit = async (next: WriterTimelineEvent[]) => {
    if (!onSave) return;
    setSaving(true);
    setError('');
    try {
      await onSave(next.map(cleanEvent));
      setForm(null);
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('剧情节点保存失败，请稍后重试。'));
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form || saving) return;
    const title = form.title.trim();
    if (!title) {
      setError(t('请填写节点标题。'));
      return;
    }
    const entry: WriterTimelineEvent = {
      phase: form.phase,
      title,
      desc: form.desc.trim(),
      points: form.points.split('\n').map(line => line.trim()).filter(Boolean).slice(0, 30),
    };
    const next = [...events];
    if (form.index !== null && form.index >= 0 && form.index < next.length) next[form.index] = entry;
    else next.push(entry);
    void commit(next);
  };

  const startCreate = () => {
    setError('');
    setForm({ index: null, phase: STORY_PHASES[Math.min(events.length, STORY_PHASES.length - 1)], title: '', desc: '', points: '' });
    setFormOpened(count => count + 1);
  };

  const startEdit = (index: number) => {
    const event = events[index];
    setError('');
    setForm({
      index,
      phase: String(event.phase || STORY_PHASES[0]),
      title: String(event.title || ''),
      desc: String(event.desc || ''),
      points: (event.points || []).join('\n'),
    });
    setFormOpened(count => count + 1);
  };

  const remove = (index: number) => {
    if (saving) return;
    // The removal is saved at once and the timeline keeps no history to bring a node back from.
    if (!window.confirm(t('确定删除剧情节点“{0}”吗？删除后无法恢复。', [String(events[index]?.title || '')]))) return;
    if (form?.index === index) setForm(null);
    void commit(events.filter((_, position) => position !== index));
  };

  const phaseOptions = Array.from(new Set<string>([...STORY_PHASES, ...events.map(event => String(event.phase || '')).filter(Boolean)]));

  // An edit opens inside its own node so the writer keeps their place in a long timeline.
  const formNode = form && (
    <form ref={formRef} className="writer-events__form" aria-label={form.index === null ? t('添加剧情节点') : t('编辑剧情节点')} onSubmit={submit}>
      <label>
        <span>{t('阶段')}</span>
        <select value={form.phase} onChange={event => setForm(current => current && { ...current, phase: event.target.value })}>
          {phaseOptions.map(phase => <option key={phase} value={phase}>{t(phase)}</option>)}
        </select>
      </label>
      <label>
        <span>{t('标题')}</span>
        <input ref={titleRef} value={form.title} maxLength={500} onChange={event => setForm(current => current && { ...current, title: event.target.value })} />
      </label>
      <label>
        <span>{t('概述')}</span>
        <textarea rows={2} value={form.desc} maxLength={4000} onChange={event => setForm(current => current && { ...current, desc: event.target.value })} />
      </label>
      <label>
        <span>{t('要点（每行一条）')}</span>
        <textarea rows={3} value={form.points} onChange={event => setForm(current => current && { ...current, points: event.target.value })} />
      </label>
      {error && <p className="writer-events__error" role="alert">{error}</p>}
      <div className="writer-events__form-actions">
        <button type="submit" disabled={saving}>{form.index === null ? t('添加') : t('保存修改')}</button>
        <button type="button" disabled={saving} onClick={() => { setForm(null); setError(''); }}>{t('取消')}</button>
      </div>
    </form>
  );

  return (
    <div className="writer-events" aria-label={t('剧情事件时间轴')}>
      <div className="writer-events__toolbar">
        <span>{authored ? t('已手动编排，不再随分集账本重新生成') : t('由分集账本生成；编辑后以你的编排为准')}</span>
        {onSave && (
          <button type="button" className="writer-outline-button is-primary" disabled={saving} onClick={startCreate}>
            <Plus aria-hidden="true" /> {t('添加节点')}
          </button>
        )}
      </div>
      {!form && error && <p className="writer-events__error" role="alert">{error}</p>}
      {form?.index === null && formNode}
      {events.length === 0 ? (
        <div className="writer-empty">{t('还没有剧情节点：生成剧本后由分集账本生成，也可以手动添加。')}</div>
      ) : (
        <ol className="writer-events__list">
          {events.map((event, index) => {
            const points = Array.isArray(event.points) ? event.points : [];
            return (
              <li key={`${event.eventId || index}-${event.title}`}>
                <span className="writer-events__dot" aria-hidden="true" />
                <article>
                  <header>
                    <em>{t(String(event.phase || '剧情节点'))}</em>
                    <h3>{event.title}</h3>
                    {onSave && (
                      <span className="writer-events__tools">
                        <button type="button" aria-label={t('编辑节点 {0}', [String(event.title || '')])} disabled={saving} onClick={() => startEdit(index)}><Pencil aria-hidden="true" /></button>
                        <button type="button" aria-label={t('删除节点 {0}', [String(event.title || '')])} disabled={saving} onClick={() => remove(index)}><Trash2 aria-hidden="true" /></button>
                      </span>
                    )}
                  </header>
                  {event.desc && <p>{event.desc}</p>}
                  {points.length > 0 && <ul>{points.map((point, pointIndex) => <li key={`${point}-${pointIndex}`}>{point}</li>)}</ul>}
                </article>
                {form?.index === index && formNode}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
