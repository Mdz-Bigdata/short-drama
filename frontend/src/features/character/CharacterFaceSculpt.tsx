import { AlertTriangle, History, RotateCcw, Save, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { FaceSculptInstruct } from './FaceSculptInstruct';
import './CharacterFaceSculpt.css';

/**
 * 捏脸与捏表情：用固定控件捏出一个角色的长相和表情习惯，存进这个角色的统一资产。
 *
 * 控件表来自服务端(app/data/prompt/face_sculpt.json)。改动先在服务端预览：右栏显示保存后角色描述
 * 会变成什么、近景镜头里实际写进提示词的脸、人物资产卡的警告，以及每个表情在镜头里的写法。
 * 保存只改文字资产、不花钱；已画好的设定集要重出才会换上新脸。
 */

interface Option { value: string; label: string }
interface FaceControl {
  key: string;
  layer: string;
  label: string;
  type: 'choice' | 'scale';
  options?: Option[];
  steps?: string[];
}
interface Catalog {
  layers: { key: string; label: string }[];
  controls: FaceControl[];
  presets: { key: string; label: string; values: Record<string, string | number> }[];
  expression_controls: { key: string; label: string; options: Option[] }[];
  expressions: { key: string; label: string; words: string[] }[];
  limits: { note_chars: number; tell_chars: number; habit_chars: number };
}
interface ExpressionValue { choices: Record<string, string>; tell: string; habit: string }
export interface FaceSculptValue {
  face: Record<string, string | number>;
  notes: Record<string, string>;
  expressions: Record<string, ExpressionValue>;
  preset: string;
}
interface Preview {
  description: string;
  face_text: string;
  layers: Record<string, string>;
  issues: { code: string; message: string }[];
  expressions: Record<string, string>;
  sheet_stale: boolean;
  stale_note: string;
}
interface HistoryEntry { id: string; label: string; at: number; revision: number }
interface Current {
  name: string;
  sculpt: FaceSculptValue;
  revision: number;
  preview: Preview;
  label?: string;
  updated_at?: number;
  /** 改动之前的几步，新的在前；每一步都能回去。 */
  history?: HistoryEntry[];
  /** 保存之后下游被标记的东西：要重跑的视频段数、设定集是否过期。 */
  downstream?: { clips_marked: number; sheet_stale: boolean };
  /** 元素库里这位演员的描述有没有跟着改。 */
  library?: { updated: boolean; element_id?: string; error?: string };
}

const EMPTY: FaceSculptValue = { face: {}, notes: {}, expressions: {}, preset: '' };
const EMPTY_EXPRESSION: ExpressionValue = { choices: {}, tell: '', habit: '' };
const SCALE_VALUES = [-2, -1, 0, 1, 2];
const HISTORY_SHOWN = 6;

function historyOf(current: Current): HistoryEntry[] {
  if (!Array.isArray(current.history)) return [];
  return current.history.filter(item => item && item.id && Number.isFinite(item.at)).slice(0, HISTORY_SHOWN);
}

/** 「3 分钟前」：at 是服务端的 unix 秒。 */
function relativeTime(at: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.floor(now / 1000 - at));
  if (seconds < 60) return t('刚刚');
  if (seconds < 3600) return t('{n} 分钟前', { n: Math.floor(seconds / 60) });
  if (seconds < 86400) return t('{n} 小时前', { n: Math.floor(seconds / 3600) });
  return t('{n} 天前', { n: Math.floor(seconds / 86400) });
}

/** 落盘之后下游的结果：要重跑几段视频、元素库有没有同步。 */
function downstreamNotes(current: Current): string[] {
  const notes: string[] = [];
  const clips = Number(current.downstream?.clips_marked || 0);
  if (clips > 0) notes.push(t('{n} 段视频需重跑第 5 阶段才会换上新脸', { n: clips }));
  if (current.library?.updated) notes.push(t('元素库里的演员描述已同步'));
  return notes;
}

function base(taskId: string, name: string) {
  return `/api/drama/${encodeURIComponent(taskId)}/characters/${encodeURIComponent(name)}/face-sculpt`;
}

function normalize(value: Partial<FaceSculptValue> | undefined): FaceSculptValue {
  const expressions: Record<string, ExpressionValue> = {};
  for (const [key, item] of Object.entries(value?.expressions || {})) {
    expressions[key] = { choices: { ...(item?.choices || {}) }, tell: item?.tell || '', habit: item?.habit || '' };
  }
  return { face: { ...(value?.face || {}) }, notes: { ...(value?.notes || {}) }, expressions, preset: value?.preset || '' };
}

export function CharacterFaceSculpt({ taskId, characterName, onSaved, onDirtyChange }: {
  taskId: string;
  characterName: string;
  /** 保存或重置成功后调用：外层据此刷新角色看板(描述与各状态的长相层已经变了)。 */
  onSaved?: () => void;
  /** 有没有未保存的改动：外层关窗前据此先问一句。 */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [value, setValue] = useState<FaceSculptValue>(EMPTY);
  const [saved, setSaved] = useState<FaceSculptValue>(EMPTY);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [tab, setTab] = useState<'face' | 'expression'>('face');
  const [expressionKey, setExpressionKey] = useState('smile');
  const [status, setStatus] = useState<'loading' | 'ready' | 'saving' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const previewVersion = useRef(0);

  useEffect(() => {
    // 换人时外层按名字重建本组件，初始状态就是 loading，这里不用再设。
    let alive = true;
    Promise.all([
      apiRequest<Catalog>('/api/face-sculpt/catalog'),
      apiRequest<Current>(base(taskId, characterName)),
    ]).then(([loadedCatalog, current]) => {
      if (!alive) return;
      setCatalog(loadedCatalog);
      const sculpt = normalize(current.sculpt);
      setValue(sculpt);
      setSaved(sculpt);
      setPreview(current.preview);
      setHistory(historyOf(current));
      setStatus('ready');
    }).catch(error => {
      if (!alive) return;
      setStatus('error');
      setMessage(error instanceof Error ? error.message : t('捏脸数据读取失败'));
    });
    return () => { alive = false; };
  }, [characterName, taskId]);

  const dirty = useMemo(() => JSON.stringify(value) !== JSON.stringify(saved), [saved, value]);

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);

  // 改动后稍等再预览：连续点几个选项只发一次请求，旧请求的结果不覆盖新的。
  useEffect(() => {
    if (status === 'loading' || !dirty) return;
    const version = ++previewVersion.current;
    const timer = window.setTimeout(() => {
      apiRequest<Preview>(`${base(taskId, characterName)}/preview`, { method: 'POST', body: JSON.stringify(value) })
        .then(result => { if (version === previewVersion.current) { setPreview(result); setMessage(''); } })
        .catch(error => { if (version === previewVersion.current) setMessage(error instanceof Error ? error.message : t('预览失败')); });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [characterName, dirty, status, taskId, value]);

  if (status === 'loading') return <p className="face-sculpt__status" role="status">{t('正在读取捏脸控件…')}</p>;
  if (status === 'error' && !catalog) return <p className="face-sculpt__status is-error" role="alert">{message}</p>;
  if (!catalog) return null;

  const setFace = (key: string, next: string | number) => setValue(current => {
    const face = { ...current.face };
    if (next === '' || next === 0) delete face[key];
    else face[key] = next;
    return { ...current, face, preset: '' };
  });
  const setNote = (layer: string, text: string) => setValue(current => ({ ...current, notes: { ...current.notes, [layer]: text } }));
  const applyPreset = (key: string) => {
    const preset = catalog.presets.find(item => item.key === key);
    if (!preset) return;
    setValue(current => ({ ...current, face: { ...preset.values }, preset: key }));
  };
  const expression = value.expressions[expressionKey] || EMPTY_EXPRESSION;
  const setExpression = (patch: Partial<ExpressionValue>) => setValue(current => {
    const next = { ...(current.expressions[expressionKey] || EMPTY_EXPRESSION), ...patch };
    const expressions = { ...current.expressions };
    const empty = !Object.values(next.choices).some(Boolean) && !next.tell.trim() && !next.habit.trim();
    if (empty) delete expressions[expressionKey];
    else expressions[expressionKey] = next;
    return { ...current, expressions };
  });

  const save = async () => {
    setStatus('saving');
    try {
      const current = await apiRequest<Current>(base(taskId, characterName), { method: 'PUT', body: JSON.stringify(value) });
      const sculpt = normalize(current.sculpt);
      setValue(sculpt);
      setSaved(sculpt);
      setPreview(current.preview);
      setHistory(historyOf(current));
      const clips = Number(current.downstream?.clips_marked || 0);
      setMessage([
        clips > 0 ? t('已保存。{n} 段视频需重跑第 5 阶段才会换上新脸', { n: clips }) : t('已保存：设定集、分镜和视频提示词都会用这张脸。'),
        current.library?.updated ? t('元素库里的演员描述已同步') : '',
      ].filter(Boolean).join(' '));
      onSaved?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('保存失败'));
    } finally {
      setStatus('ready');
    }
  };
  const reset = async () => {
    if (!window.confirm(t('放回第一次捏脸之前的角色描述，并清掉所有表情习惯？'))) return;
    setStatus('saving');
    try {
      const current = await apiRequest<Current>(base(taskId, characterName), { method: 'DELETE' });
      setValue(EMPTY);
      setSaved(EMPTY);
      setPreview(current.preview);
      setHistory(historyOf(current));
      setMessage(t('已恢复原来的角色描述。'));
      onSaved?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('重置失败'));
    } finally {
      setStatus('ready');
    }
  };

  const revert = async (entry: HistoryEntry) => {
    if (dirty || status === 'saving') return;
    setStatus('saving');
    try {
      const current = await apiRequest<Current>(`${base(taskId, characterName)}/revert`, {
        method: 'POST',
        body: JSON.stringify({ snapshot_id: entry.id }),
      });
      const sculpt = normalize(current.sculpt);
      setValue(sculpt);
      setSaved(sculpt);
      setPreview(current.preview);
      setHistory(historyOf(current));
      setMessage([t('已回到这一步。'), ...downstreamNotes(current)].join(' '));
      onSaved?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('没能回到这一步'));
    } finally {
      setStatus('ready');
    }
  };

  const sculptedExpressions = new Set(Object.keys(value.expressions));
  const busy = status === 'saving';

  return (
    <div className="face-sculpt">
      <div className="face-sculpt__editor">
        <div className="face-sculpt__tabs" role="tablist" aria-label={t('捏脸或捏表情')}>
          <button type="button" role="tab" aria-selected={tab === 'face'} className={tab === 'face' ? 'is-active' : ''} onClick={() => setTab('face')}>
            {t('捏脸')}
          </button>
          <button type="button" role="tab" aria-selected={tab === 'expression'} className={tab === 'expression' ? 'is-active' : ''} onClick={() => setTab('expression')}>
            {t('捏表情')}
          </button>
        </div>

        {tab === 'face' ? (
          <div role="tabpanel" aria-label={t('捏脸')}>
            <FaceSculptInstruct
              taskId={taskId}
              characterName={characterName}
              busy={busy}
              onProposed={next => setValue(normalize(next))}
            />
            <label className="face-sculpt__preset">
              <span><Sparkles size={14} aria-hidden="true" /> {t('从预设开始')}</span>
              <select value={value.preset} onChange={event => applyPreset(event.target.value)}>
                <option value="">{t('不用预设')}</option>
                {catalog.presets.map(preset => <option key={preset.key} value={preset.key}>{preset.label}</option>)}
              </select>
            </label>
            {catalog.layers.map(layer => {
              const controls = catalog.controls.filter(control => control.layer === layer.key);
              return (
                <fieldset key={layer.key} className="face-sculpt__layer">
                  <legend>{layer.label}</legend>
                  {controls.map(control => control.type === 'choice' ? (
                    <label key={control.key} className="face-sculpt__control">
                      <span>{control.label}</span>
                      <select value={String(value.face[control.key] ?? '')} onChange={event => setFace(control.key, event.target.value)}>
                        <option value="">{t('沿用原描述')}</option>
                        {control.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>
                  ) : (
                    <div key={control.key} className="face-sculpt__control" role="group" aria-label={control.label}>
                      <span>{control.label}</span>
                      <div className="face-sculpt__scale">
                        {SCALE_VALUES.map((step, index) => {
                          const selected = Number(value.face[control.key] ?? 0) === step;
                          const label = control.steps?.[index] || t('适中');
                          return (
                            <button
                              key={step}
                              type="button"
                              aria-pressed={selected}
                              title={label}
                              aria-label={`${control.label}：${label}`}
                              className={selected ? 'is-active' : ''}
                              onClick={() => setFace(control.key, step)}
                            >
                              {step > 0 ? `+${step}` : step}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  <label className="face-sculpt__note">
                    <span>{t('补充')}</span>
                    <input
                      value={value.notes[layer.key] || ''}
                      maxLength={catalog.limits.note_chars}
                      placeholder={t('这一层还要锁定的细节，如：右眉尾一道浅疤')}
                      onChange={event => setNote(layer.key, event.target.value)}
                    />
                  </label>
                </fieldset>
              );
            })}
          </div>
        ) : (
          <div role="tabpanel" aria-label={t('捏表情')}>
            <p className="face-sculpt__hint">{t('给这个人的每种情绪写一套自己的样子。镜头读到这个人这一镜的情绪时，用的是这一条，而不是通用写法。')}</p>
            <div className="face-sculpt__chips" role="listbox" aria-label={t('情绪')}>
              {catalog.expressions.map(item => (
                <button
                  key={item.key}
                  type="button"
                  role="option"
                  aria-selected={expressionKey === item.key}
                  className={`${expressionKey === item.key ? 'is-active' : ''} ${sculptedExpressions.has(item.key) ? 'is-sculpted' : ''}`}
                  title={item.words.join('、')}
                  onClick={() => setExpressionKey(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <fieldset className="face-sculpt__layer">
              <legend>{catalog.expressions.find(item => item.key === expressionKey)?.label}</legend>
              {catalog.expression_controls.map(control => (
                <label key={control.key} className="face-sculpt__control">
                  <span>{control.label}</span>
                  <select
                    value={expression.choices[control.key] || ''}
                    onChange={event => setExpression({ choices: { ...expression.choices, [control.key]: event.target.value } })}
                  >
                    <option value="">{t('不指定')}</option>
                    {control.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
              ))}
              <label className="face-sculpt__note">
                <span>{t('面部特征')}</span>
                <input
                  value={expression.tell}
                  maxLength={catalog.limits.tell_chars}
                  placeholder={t('只有这个人才有的，如：左颊梨涡、哭时鼻尖先红')}
                  onChange={event => setExpression({ tell: event.target.value })}
                />
              </label>
              <label className="face-sculpt__note">
                <span>{t('小动作')}</span>
                <input
                  value={expression.habit}
                  maxLength={catalog.limits.habit_chars}
                  placeholder={t('如：笑前先低头、生气时拇指摩挲剑柄')}
                  onChange={event => setExpression({ habit: event.target.value })}
                />
              </label>
            </fieldset>
          </div>
        )}
      </div>

      <aside className="face-sculpt__preview" aria-label={t('捏脸效果')} aria-live="polite">
        <h3>{t('近景镜头里的脸')}</h3>
        <p className="face-sculpt__face-text">{preview?.face_text || t('还没有可写进提示词的长相')}</p>
        {preview?.issues.map(issue => (
          <p key={issue.code} className="face-sculpt__issue" role="alert"><AlertTriangle size={14} aria-hidden="true" /> {issue.message}</p>
        ))}
        {tab === 'expression' && (
          <>
            <h3>{t('这个表情在镜头里')}</h3>
            <p className="face-sculpt__face-text">{preview?.expressions[expressionKey] || t('这个情绪还用通用写法')}</p>
          </>
        )}
        <details className="face-sculpt__description">
          <summary>{t('保存后的角色描述')}</summary>
          <p>{preview?.description}</p>
        </details>
        {preview?.sheet_stale && <p className="face-sculpt__stale"><AlertTriangle size={14} aria-hidden="true" /> {preview.stale_note}</p>}
        {message && <p className="face-sculpt__message" role="status">{message}</p>}
        <div className="face-sculpt__actions">
          <button type="button" className="is-primary" disabled={!dirty || status === 'saving'} onClick={() => { void save(); }}>
            <Save size={14} aria-hidden="true" /> {status === 'saving' ? t('保存中…') : t('保存到角色资产')}
          </button>
          <button type="button" disabled={status === 'saving'} onClick={() => { void reset(); }}>
            <RotateCcw size={14} aria-hidden="true" /> {t('恢复原描述')}
          </button>
        </div>
        {history.length > 0 && (
          <section className="face-sculpt__history" aria-label={t('修改记录')}>
            <h3><History size={14} aria-hidden="true" /> {t('修改记录')}</h3>
            <ol>
              {history.map(entry => (
                <li key={entry.id}>
                  <span className="face-sculpt__history-label">{entry.label || t('一次修改')}</span>
                  <time className="face-sculpt__history-time" dateTime={new Date(entry.at * 1000).toISOString()}>{relativeTime(entry.at)}</time>
                  <button
                    type="button"
                    disabled={dirty || busy}
                    title={dirty ? t('先保存或放弃未保存的改动') : undefined}
                    aria-label={`${t('回到这一步')}：${entry.label || t('一次修改')}`}
                    onClick={() => { void revert(entry); }}
                  >
                    {t('回到这一步')}
                  </button>
                </li>
              ))}
            </ol>
          </section>
        )}
      </aside>
    </div>
  );
}
