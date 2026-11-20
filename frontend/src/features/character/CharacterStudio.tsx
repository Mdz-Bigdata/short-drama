import {
  AlertTriangle, Columns2, History, PersonStanding, Redo2, RotateCcw, Sparkles, Undo2, UserRound, Wand2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { FaceSculptInstruct } from './FaceSculptInstruct';
import {
  EMPTY_EXPRESSION, EMPTY_SCULPT, controlValue, downstreamNotes, historyOf, normalizeSculpt, relativeTime, sculptBase,
  withControl, withPreset,
  type ExpressionValue, type FaceSculptValue, type SculptCatalog, type SculptCurrent, type SculptHistoryEntry, type SculptPreview,
  type StudioPanel, type StudioSection,
} from './faceSculptModel';
import { StudioControl } from './StudioControls';
import { StudioMarks } from './StudioMarks';
import { StudioVoice } from './StudioVoice';
import './CharacterStudio.css';

/**
 * 角色造型编辑器：脸部精修、脸部与身体特征、身材塑形、服装造型、音色音调、表情习惯。
 *
 * 每一处改动都落在这个角色的统一资产上(捏脸写进角色描述的各层，见 backend app/core/face_sculpt.py)：
 * 设定集、分镜和视频提示词都读这段描述。保存只改文字、不花钱；画面要「确认生成」(或勾上「保存时生成
 * 角色资产」)重画设定集才会换成新的样子，那一步调用图像模型，先问一句。
 * 版面(左栏几块、每块几页、每页放哪些控件)来自服务端的控件表。
 */

const FALLBACK_PANELS: StudioPanel[] = [{ key: 'all', label: '捏脸', sections: [] }];

function sectionLayer(catalog: SculptCatalog, section: StudioSection): string {
  const counts = new Map<string, number>();
  for (const key of section.controls) {
    const layer = catalog.controls.find(control => control.key === key)?.layer;
    if (layer) counts.set(layer, (counts.get(layer) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || '';
}

function panelsOf(catalog: SculptCatalog): StudioPanel[] {
  const panels = catalog.studio?.panels?.length ? catalog.studio.panels : FALLBACK_PANELS;
  // 没有版面的旧服务端：所有控件按层各一页。
  return panels.map(panel => (panel.key === 'all'
    ? { ...panel, sections: catalog.layers.map(layer => ({ key: layer.key, label: layer.label, controls: catalog.controls.filter(control => control.layer === layer.key).map(control => control.key), presets: layer.key === 'bone' })) }
    : panel));
}

export function CharacterStudio({
  taskId, characterName, role = '', faceImage, bodyImage, onSaved, onDirtyChange, onGenerate,
}: {
  taskId: string;
  characterName: string;
  /** 名字下面的一行：角色定位。 */
  role?: string;
  /** 中间大图：脸部近景与全身。 */
  faceImage?: string | null;
  bodyImage?: string | null;
  /** 保存、重置、回退成功后：外层刷新角色看板。 */
  onSaved?: () => void;
  /** 有没有未保存的改动：外层关窗前据此先问一句。 */
  onDirtyChange?: (dirty: boolean) => void;
  /** 按保存后的描述重画这个角色的设定集(付费，后台进行)；没有就不提供生成。 */
  onGenerate?: (name: string) => void | Promise<void>;
}) {
  const [catalog, setCatalog] = useState<SculptCatalog | null>(null);
  const [value, setValue] = useState<FaceSculptValue>(EMPTY_SCULPT);
  const [saved, setSaved] = useState<FaceSculptValue>(EMPTY_SCULPT);
  const [undo, setUndo] = useState<FaceSculptValue[]>([]);
  const [redo, setRedo] = useState<FaceSculptValue[]>([]);
  const [preview, setPreview] = useState<SculptPreview | null>(null);
  const [savedPreview, setSavedPreview] = useState<SculptPreview | null>(null);
  const [history, setHistory] = useState<SculptHistoryEntry[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'saving' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [panelKey, setPanelKey] = useState('');
  const [sectionKey, setSectionKey] = useState('');
  const [view, setView] = useState<'face' | 'body'>('face');
  const [compare, setCompare] = useState(false);
  const [instructOpen, setInstructOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [generateOnSave, setGenerateOnSave] = useState(false);
  const [expressionKey, setExpressionKey] = useState('smile');
  const previewVersion = useRef(0);

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiRequest<SculptCatalog>('/api/face-sculpt/catalog'),
      apiRequest<SculptCurrent>(sculptBase(taskId, characterName)),
    ]).then(([loaded, current]) => {
      if (!alive) return;
      setCatalog(loaded);
      const sculpt = normalizeSculpt(current.sculpt);
      setValue(sculpt);
      setSaved(sculpt);
      setPreview(current.preview);
      setSavedPreview(current.preview);
      setHistory(historyOf(current));
      setExpressionKey(loaded.expressions[0]?.key || 'smile');
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

  // 改动后稍等再预览：连续拖几下只发一次请求，旧请求的结果不覆盖新的。
  useEffect(() => {
    if (status === 'loading' || !dirty) return;
    const version = ++previewVersion.current;
    const timer = window.setTimeout(() => {
      apiRequest<SculptPreview>(`${sculptBase(taskId, characterName)}/preview`, { method: 'POST', body: JSON.stringify(value) })
        .then(result => { if (version === previewVersion.current) { setPreview(result); setMessage(''); } })
        .catch(error => { if (version === previewVersion.current) setMessage(error instanceof Error ? error.message : t('预览失败')); });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [characterName, dirty, status, taskId, value]);

  if (status === 'loading') return <p className="character-studio__status" role="status">{t('正在读取捏脸控件…')}</p>;
  if (status === 'error' && !catalog) return <p className="character-studio__status is-error" role="alert">{message}</p>;
  if (!catalog) return null;

  const panels = panelsOf(catalog);
  const panel = panels.find(item => item.key === panelKey) || panels[0];
  const sections = panel.sections || [];
  const section = sections.find(item => item.key === sectionKey) || sections[0];
  const busy = status === 'saving';

  /** 每一次改动都进撤销栈；重做栈在新改动时清空。 */
  const change = (next: FaceSculptValue | ((current: FaceSculptValue) => FaceSculptValue)) => {
    const updated = typeof next === 'function' ? next(value) : next;
    if (JSON.stringify(updated) === JSON.stringify(value)) return;
    setUndo(stack => [...stack.slice(-49), value]);
    setRedo([]);
    setValue(updated);
  };
  const stepBack = () => {
    const previous = undo[undo.length - 1];
    if (!previous) return;
    setUndo(stack => stack.slice(0, -1));
    setRedo(stack => [...stack, value]);
    setValue(previous);
  };
  const stepForward = () => {
    const next = redo[redo.length - 1];
    if (!next) return;
    setRedo(stack => stack.slice(0, -1));
    setUndo(stack => [...stack, value]);
    setValue(next);
  };

  const applyCurrent = (current: SculptCurrent) => {
    const sculpt = normalizeSculpt(current.sculpt);
    setValue(sculpt);
    setSaved(sculpt);
    setPreview(current.preview);
    setSavedPreview(current.preview);
    setHistory(historyOf(current));
  };

  const persist = async (): Promise<SculptCurrent | null> => {
    if (!dirty) return null;
    const current = await apiRequest<SculptCurrent>(sculptBase(taskId, characterName), { method: 'PUT', body: JSON.stringify(value) });
    applyCurrent(current);
    return current;
  };

  const addToCanvas = async (): Promise<string> => {
    try {
      const result = await apiRequest<{ added: boolean }>(`/api/studio/tasks/${encodeURIComponent(taskId)}/canvas/character`, {
        method: 'POST', body: JSON.stringify({ name: characterName }),
      });
      return result.added ? t('已把「{0}」的定妆设定集放到画布上。', [characterName]) : t('画布上已经有「{0}」的这张设定集。', [characterName]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) return error.message;
      throw error;
    }
  };

  /** 保存；generate 时接着重画设定集(付费，先问)，canvas 时把设定集放到画布上。 */
  const save = async ({ generate = false, canvas = false }: { generate?: boolean; canvas?: boolean } = {}) => {
    const drawing = generate && Boolean(onGenerate);
    if (drawing && !window.confirm(t('按现在的样子重画「{0}」的设定集？会调用图像模型，按次计费，在后台进行。', [characterName]))) return;
    setStatus('saving');
    try {
      const current = await persist();
      const notes: string[] = [];
      if (current) {
        const clips = Number(current.downstream?.clips_marked || 0);
        notes.push(clips > 0 ? t('已保存。{n} 段视频需重跑第 5 阶段才会换上新脸', { n: clips }) : t('已保存：设定集、分镜和视频提示词都会用这张脸。'));
        if (current.library?.updated) notes.push(t('元素库里的演员描述已同步'));
        onSaved?.();
      }
      if (drawing) {
        await onGenerate?.(characterName);
        notes.push(t('设定集正在后台重画，画好后这里自动换成新的样子。'));
      }
      if (canvas) {
        notes.push(await addToCanvas());
        if (drawing) notes.push(t('新设定集画好后，在画布上同步一次就会换上。'));
      }
      setMessage(notes.join(' ') || t('没有要保存的改动。'));
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
      applyCurrent(await apiRequest<SculptCurrent>(sculptBase(taskId, characterName), { method: 'DELETE' }));
      setUndo([]);
      setRedo([]);
      setMessage(t('已恢复原来的角色描述。'));
      onSaved?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('重置失败'));
    } finally {
      setStatus('ready');
    }
  };

  const revert = async (entry: SculptHistoryEntry) => {
    if (dirty || busy) return;
    setStatus('saving');
    try {
      const current = await apiRequest<SculptCurrent>(`${sculptBase(taskId, characterName)}/revert`, {
        method: 'POST', body: JSON.stringify({ snapshot_id: entry.id }),
      });
      applyCurrent(current);
      setHistoryOpen(false);
      setMessage([t('已回到这一步。'), ...downstreamNotes(current)].join(' '));
      onSaved?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('没能回到这一步'));
    } finally {
      setStatus('ready');
    }
  };

  const expression = value.expressions[expressionKey] || EMPTY_EXPRESSION;
  const setExpression = (patch: Partial<ExpressionValue>) => change(current => {
    const next = { ...(current.expressions[expressionKey] || EMPTY_EXPRESSION), ...patch };
    const expressions = { ...current.expressions };
    const empty = !Object.values(next.choices).some(Boolean) && !next.tell.trim() && !next.habit.trim();
    if (empty) delete expressions[expressionKey];
    else expressions[expressionKey] = next;
    return { ...current, expressions };
  });
  const focusControls = catalog.controls.filter(control => (catalog.focus_layers || []).includes(control.layer));
  const picture = view === 'face' ? faceImage || bodyImage : bodyImage || faceImage;
  const changedLayers = catalog.layers.filter(layer => (preview?.layers[layer.key] || '') !== (savedPreview?.layers[layer.key] || ''));

  const renderSection = (current: StudioSection) => {
    const layer = sectionLayer(catalog, current);
    return (
      <div className="studio-section" role="tabpanel" aria-label={current.label}>
        {current.presets && catalog.presets.length > 0 && (
          <div className="studio-control" role="group" aria-label={t('从预设开始')}>
            <span className="studio-control__label"><Sparkles size={13} aria-hidden="true" /> {t('从预设开始')}</span>
            <div className="studio-chips">
              {catalog.presets.map(preset => (
                <button
                  key={preset.key}
                  type="button"
                  aria-pressed={value.preset === preset.key}
                  className={value.preset === preset.key ? 'is-active' : ''}
                  onClick={() => change(currentValue => withPreset(catalog, currentValue, preset.key))}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {current.presets && focusControls.length > 0 && (
          <label className="studio-control" title={t('一张脸留一个突出点，其余五官收一收做配合；对话改脸时不会换掉它。')}>
            <span className="studio-control__label">{t('突出点')}</span>
            <select className="studio-select" value={value.focus} onChange={event => change(currentValue => ({ ...currentValue, focus: event.target.value }))}>
              <option value="">{t('不定突出点')}</option>
              {focusControls.map(control => <option key={control.key} value={control.key}>{control.label}</option>)}
            </select>
          </label>
        )}
        {current.controls.map(key => {
          const control = catalog.controls.find(item => item.key === key);
          if (!control) return null;
          return (
            <StudioControl
              key={control.key}
              control={control}
              value={controlValue(value, control.key)}
              onChange={next => change(currentValue => withControl(currentValue, control.key, next))}
            />
          );
        })}
        {layer && (
          <label className="studio-control">
            <span className="studio-control__label">{t('补充')}</span>
            <input
              className="studio-text"
              value={value.notes[layer] || ''}
              maxLength={catalog.limits.note_chars}
              placeholder={t('这一层还要锁定的细节，如：右眉尾一道浅疤')}
              onChange={event => change(currentValue => ({ ...currentValue, notes: { ...currentValue.notes, [layer]: event.target.value } }))}
            />
          </label>
        )}
      </div>
    );
  };

  const renderExpressions = () => (
    <div className="studio-section">
      <p className="studio-hint">{t('给这个人的每种情绪写一套自己的样子。镜头读到这个人这一镜的情绪时，用的是这一条，而不是通用写法。')}</p>
      <div className="studio-chips" role="listbox" aria-label={t('情绪')}>
        {catalog.expressions.map(item => (
          <button
            key={item.key}
            type="button"
            role="option"
            aria-selected={expressionKey === item.key}
            className={`${expressionKey === item.key ? 'is-active' : ''}${value.expressions[item.key] ? ' is-sculpted' : ''}`}
            title={item.words.join('、')}
            onClick={() => setExpressionKey(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {catalog.expression_controls.map(control => (
        <div key={control.key} className="studio-control" role="group" aria-label={control.label}>
          <span className="studio-control__label">{control.label}</span>
          <div className="studio-chips">
            {control.options.map(option => {
              const chosen = expression.choices[control.key] === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={chosen}
                  className={chosen ? 'is-active' : ''}
                  onClick={() => setExpression({ choices: { ...expression.choices, [control.key]: chosen ? '' : option.value } })}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <label className="studio-control">
        <span className="studio-control__label">{t('面部特征')}</span>
        <input className="studio-text" value={expression.tell} maxLength={catalog.limits.tell_chars} placeholder={t('只有这个人才有的，如：左颊梨涡、哭时鼻尖先红')} onChange={event => setExpression({ tell: event.target.value })} />
      </label>
      <label className="studio-control">
        <span className="studio-control__label">{t('小动作')}</span>
        <input className="studio-text" value={expression.habit} maxLength={catalog.limits.habit_chars} placeholder={t('如：笑前先低头、生气时拇指摩挲剑柄')} onChange={event => setExpression({ habit: event.target.value })} />
      </label>
      <p className="studio-face-text">{preview?.expressions[expressionKey] || t('这个情绪还用通用写法')}</p>
    </div>
  );

  return (
    <div className="character-studio">
      <nav className="character-studio__nav" aria-label={t('造型分类')}>
        <div className="character-studio__identity">
          <strong>{characterName}</strong>
          {role && <span>{role}</span>}
        </div>
        {panels.map(item => (
          <button
            key={item.key}
            type="button"
            aria-current={item.key === panel.key ? 'page' : undefined}
            className={item.key === panel.key ? 'is-active' : ''}
            onClick={() => { setPanelKey(item.key); setSectionKey(''); if (item.key === 'body') setView('body'); }}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <section className="character-studio__stage" aria-label={t('角色画面')}>
        <div className="character-studio__picture">
          {picture
            ? <img src={apiUrl(picture)} alt={view === 'face' ? t('{0}的脸部', [characterName]) : t('{0}的全身', [characterName])} />
            : <p className="studio-hint">{t('还没有画面：保存后点「确认生成」画出设定集。')}</p>}
          {(dirty || preview?.sheet_stale) && (
            <p className="character-studio__stale">
              <AlertTriangle size={13} aria-hidden="true" /> {dirty ? t('画面还是改动前的样子：保存并确认生成后换成新的') : preview?.stale_note}
            </p>
          )}
          {compare && (
            <div className="character-studio__compare" aria-label={t('改动对比')}>
              {changedLayers.length === 0 && <p>{t('和上次保存时一样。')}</p>}
              {changedLayers.map(layer => (
                <dl key={layer.key}>
                  <dt>{layer.label}</dt>
                  <dd><span>{t('之前')}</span>{savedPreview?.layers[layer.key] || t('沿用原描述')}</dd>
                  <dd><span>{t('现在')}</span>{preview?.layers[layer.key] || t('沿用原描述')}</dd>
                </dl>
              ))}
            </div>
          )}
        </div>
        <div className="character-studio__toolbar">
          <div className="character-studio__tools">
            <button type="button" className="studio-icon-button" aria-label={t('撤销')} disabled={!undo.length} onClick={stepBack}><Undo2 size={16} /></button>
            <button type="button" className="studio-icon-button" aria-label={t('重做')} disabled={!redo.length} onClick={stepForward}><Redo2 size={16} /></button>
            <button type="button" className={`studio-icon-button${compare ? ' is-active' : ''}`} aria-pressed={compare} aria-label={t('对比改动')} onClick={() => setCompare(open => !open)}><Columns2 size={16} /></button>
          </div>
          <div className="character-studio__views" role="group" aria-label={t('画面')}>
            <button type="button" className={`studio-icon-button${view === 'face' ? ' is-active' : ''}`} aria-pressed={view === 'face'} aria-label={t('脸部')} onClick={() => setView('face')}><UserRound size={16} /></button>
            <button type="button" className={`studio-icon-button${view === 'body' ? ' is-active' : ''}`} aria-pressed={view === 'body'} aria-label={t('全身')} onClick={() => setView('body')}><PersonStanding size={16} /></button>
          </div>
        </div>
        <details className="character-studio__description">
          <summary>{t('保存后的角色描述')}</summary>
          <p>{preview?.description}</p>
        </details>
      </section>

      <aside className="character-studio__controls" aria-label={panel.label}>
        {sections.length > 1 && (
          <div className="studio-tabs" role="tablist" aria-label={panel.label}>
            {sections.map(item => (
              <button key={item.key} type="button" role="tab" aria-selected={item.key === section?.key} className={item.key === section?.key ? 'is-active' : ''} onClick={() => setSectionKey(item.key)}>
                {item.label}
              </button>
            ))}
          </div>
        )}
        <div className="character-studio__scroll">
          {panel.marks && catalog.marks && (
            <StudioMarks
              catalog={catalog.marks}
              marks={value.marks}
              area={view}
              onAreaChange={setView}
              onChange={marks => change(current => ({ ...current, marks }))}
            />
          )}
          {panel.voice && <StudioVoice taskId={taskId} characterName={characterName} onChanged={onSaved} />}
          {panel.expression && renderExpressions()}
          {section && renderSection(section)}
          {preview?.issues.map(issue => (
            <p key={issue.code} className="studio-issue" role="alert"><AlertTriangle size={13} aria-hidden="true" /> {issue.message}</p>
          ))}
        </div>
        {!panel.voice && (
          <div className="character-studio__generate">
            {instructOpen && (
              <div className="character-studio__instruct">
                <FaceSculptInstruct taskId={taskId} characterName={characterName} busy={busy} onProposed={next => change(normalizeSculpt(next))} />
              </div>
            )}
            {onGenerate && (
              <button type="button" className="studio-primary" disabled={busy} onClick={() => { void save({ generate: true }); }}>
                <Sparkles size={15} aria-hidden="true" /> {t('确认生成')}
              </button>
            )}
            <button
              type="button"
              className={`studio-icon-button studio-icon-button--large${instructOpen ? ' is-active' : ''}`}
              aria-pressed={instructOpen}
              aria-label={t('用一句话捏脸')}
              title={t('用一句话捏脸')}
              onClick={() => setInstructOpen(open => !open)}
            >
              <Wand2 size={16} />
            </button>
          </div>
        )}
      </aside>

      <footer className="character-studio__footer">
        {onGenerate ? (
          <label className="character-studio__check">
            <input type="checkbox" checked={generateOnSave} onChange={event => setGenerateOnSave(event.target.checked)} />
            {t('保存时生成角色资产')}
            <small>{t('（重画设定集，按次计费）')}</small>
          </label>
        ) : <span />}
        {message && <p className="character-studio__message" role="status">{message}</p>}
        <div className="character-studio__actions">
          <div className="character-studio__history">
            <button type="button" className="studio-icon-button" aria-expanded={historyOpen} aria-label={t('修改记录')} disabled={!history.length} onClick={() => setHistoryOpen(open => !open)}>
              <History size={16} />
            </button>
            {historyOpen && (
              <section className="character-studio__history-list" aria-label={t('修改记录')}>
                <ol>
                  {history.map(entry => (
                    <li key={entry.id}>
                      <span>{entry.label || t('一次修改')}</span>
                      <time dateTime={new Date(entry.at * 1000).toISOString()}>{relativeTime(entry.at)}</time>
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
          </div>
          <button type="button" className="studio-icon-button" aria-label={t('恢复原描述')} title={t('恢复原描述')} disabled={busy} onClick={() => { void reset(); }}>
            <RotateCcw size={16} />
          </button>
          <button type="button" className="studio-secondary" disabled={busy || (!dirty && !generateOnSave)} onClick={() => { void save({ generate: generateOnSave }); }}>
            {busy ? t('保存中…') : t('保存')}
          </button>
          <button type="button" className="studio-primary" disabled={busy} onClick={() => { void save({ generate: generateOnSave, canvas: true }); }}>
            {t('保存并添加到画布')}
          </button>
        </div>
      </footer>
    </div>
  );
}
