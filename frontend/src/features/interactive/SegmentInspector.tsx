import { Plus, Trash2 } from 'lucide-react';

import { t } from '../../i18n';
import {
  addChoice, addRoute, connectEdge, deleteChoice, deleteRoute, MAX_CHOICES, MAX_ROUTES, moveChoice, moveItem, moveRoute, setKind, updateChoice, updateRoute, updateSegment,
} from './graphOps';
import { CanvasHandoffButton } from './CanvasHandoffButton';
import { MediaPicker } from './MediaPicker';
import { ConditionEditor, EffectsEditor, Field, NumberField, RowTools } from './storyFields';
import type { Selection, StoryGraph, StorySegment } from './storyTypes';

type Edit = (change: (graph: StoryGraph) => StoryGraph) => void;

function TargetSelect({ graph, value, onChange, label }: { graph: StoryGraph; value: string | null; onChange: (target: string | null) => void; label: string }) {
  const known = graph.segments.some(item => item.id === value);
  return (
    <select aria-label={label} value={known ? value! : ''} onChange={event => onChange(event.target.value || null)}>
      <option value="">{t('（未连接）')}</option>
      {graph.segments.map(item => <option key={item.id} value={item.id}>{item.title || item.id}</option>)}
    </select>
  );
}

/** Everything about one segment; the selected choice or route is the one scrolled into its open state. */
export function SegmentInspector({ taskId, graph, segment, selection, edit, onDelete, onSelect, onOpenCanvas }: {
  taskId: string;
  /** Opens the project's node canvas; absent where there is none to open. */
  onOpenCanvas?: () => void;
  graph: StoryGraph;
  segment: StorySegment;
  selection: Selection;
  edit: Edit;
  onDelete: () => void;
  onSelect: (selection: Selection) => void;
}) {
  const patch = (change: Partial<StorySegment>) => edit(current => updateSegment(current, segment.id, change));
  const selectedEdge = selection?.kind === 'edge' ? selection.edge : null;
  return (
    <div className="istory-inspector" aria-label={t('片段编辑')}>
      <header className="istory-inspector__head">
        <h2>{t('片段')}</h2>
        <button type="button" className="istory-link is-danger" onClick={onDelete}><Trash2 aria-hidden="true" /> {t('删除片段')}</button>
      </header>
      <Field label={t('标题')}>
        <input value={segment.title} maxLength={120} onChange={event => patch({ title: event.target.value })} />
      </Field>
      <div className="istory-inline">
        <Field label={t('类型')}>
          <select value={segment.kind} onChange={event => edit(current => setKind(current, segment.id, event.target.value as StorySegment['kind']))}>
            <option value="scene">{t('剧情片段')}</option>
            <option value="ending">{t('结局')}</option>
          </select>
        </Field>
        <label className="istory-check">
          <input type="radio" name="istory-start" checked={graph.start === segment.id} onChange={() => edit(current => ({ ...current, start: segment.id }))} />
          {t('设为开场')}
        </label>
      </div>
      {segment.kind === 'ending' && (
        <Field label={t('结局名称')}>
          <input value={segment.ending_label} maxLength={60} onChange={event => patch({ ending_label: event.target.value })} />
        </Field>
      )}
      <Field label={t('旁白 / 场景')}>
        <textarea rows={4} value={segment.narration} maxLength={4000} onChange={event => patch({ narration: event.target.value })} />
      </Field>
      <section className="istory-section">
        <h3>{t('台词')}</h3>
        {segment.dialogue.map((line, index) => (
          <div className="istory-dialogue" key={index}>
            <input aria-label={t('说话人')} placeholder={t('说话人')} value={line.speaker} maxLength={60} onChange={event => patch({ dialogue: segment.dialogue.map((item, at) => (at === index ? { ...item, speaker: event.target.value } : item)) })} />
            <input aria-label={t('台词内容')} placeholder={t('台词内容')} value={line.text} maxLength={1000} onChange={event => patch({ dialogue: segment.dialogue.map((item, at) => (at === index ? { ...item, text: event.target.value } : item)) })} />
            <RowTools
              onUp={index ? () => patch({ dialogue: moveItem(segment.dialogue, index, -1) }) : undefined}
              onDown={index < segment.dialogue.length - 1 ? () => patch({ dialogue: moveItem(segment.dialogue, index, 1) }) : undefined}
              onDelete={() => patch({ dialogue: segment.dialogue.filter((_, at) => at !== index) })}
              deleteLabel={t('删除这句台词')}
            />
          </div>
        ))}
        <button type="button" className="istory-link" disabled={segment.dialogue.length >= 40} onClick={() => patch({ dialogue: [...segment.dialogue, { speaker: '', text: '' }] })}>
          <Plus aria-hidden="true" /> {t('添加台词')}
        </button>
      </section>
      <section className="istory-section">
        <h3>{t('媒体')}</h3>
        <CanvasHandoffButton taskId={taskId} segmentId={segment.id} onOpenCanvas={onOpenCanvas} />
        <MediaPicker taskId={taskId} value={segment.media} onChange={media => patch({ media })} />
        <Field label={t('预计时长（秒）')} hint={t('留空时按视频长度或文字量估算')}>
          <NumberField label={t('预计时长（秒）')} value={segment.est_seconds} allowEmpty min={0} max={7200} onChange={value => patch({ est_seconds: value === null ? null : Math.max(0, Math.min(7200, value)) })} />
        </Field>
      </section>
      {segment.kind !== 'ending' && (
        <>
          <section className="istory-section">
            <h3>{t('选项')}</h3>
            {segment.choices.map((choice, index) => (
              <article className={`istory-edge-card ${selectedEdge === choice.id ? 'is-selected' : ''}`} key={choice.id} data-choice={choice.id}>
                <div className="istory-inline">
                  <input
                    aria-label={t('选项文字')}
                    placeholder={t('选项文字')}
                    value={choice.text}
                    maxLength={200}
                    onFocus={() => onSelect({ kind: 'edge', segment: segment.id, edge: choice.id })}
                    onChange={event => edit(current => updateChoice(current, segment.id, choice.id, { text: event.target.value }))}
                  />
                  <RowTools
                    onUp={index ? () => edit(current => moveChoice(current, segment.id, choice.id, -1)) : undefined}
                    onDown={index < segment.choices.length - 1 ? () => edit(current => moveChoice(current, segment.id, choice.id, 1)) : undefined}
                    onDelete={() => edit(current => deleteChoice(current, segment.id, choice.id))}
                    deleteLabel={t('删除这个选项')}
                  />
                </div>
                <Field label={t('去往')}>
                  <TargetSelect graph={graph} label={t('去往')} value={choice.target} onChange={target => edit(current => connectEdge(current, segment.id, choice.id, target))} />
                </Field>
                <details open={Boolean(choice.condition) || selectedEdge === choice.id}>
                  <summary>{t('出现条件')}</summary>
                  <ConditionEditor value={choice.condition} variables={graph.variables} onChange={condition => edit(current => updateChoice(current, segment.id, choice.id, { condition }))} />
                  {choice.condition && (
                    <div className="istory-inline">
                      <Field label={t('不满足时')}>
                        <select value={choice.when_locked} onChange={event => edit(current => updateChoice(current, segment.id, choice.id, { when_locked: event.target.value as 'hide' | 'lock' }))}>
                          <option value="lock">{t('显示为锁定')}</option>
                          <option value="hide">{t('隐藏')}</option>
                        </select>
                      </Field>
                      {choice.when_locked === 'lock' && (
                        <Field label={t('锁定提示')}>
                          <input value={choice.locked_hint} maxLength={120} onChange={event => edit(current => updateChoice(current, segment.id, choice.id, { locked_hint: event.target.value }))} />
                        </Field>
                      )}
                    </div>
                  )}
                </details>
                <details open={choice.effects.length > 0}>
                  <summary>{t('选择后的效果')}</summary>
                  <EffectsEditor value={choice.effects} variables={graph.variables} onChange={effects => edit(current => updateChoice(current, segment.id, choice.id, { effects }))} />
                </details>
              </article>
            ))}
            <button type="button" className="istory-link" disabled={segment.choices.length >= MAX_CHOICES} onClick={() => edit(current => addChoice(current, segment.id, t('新选项')).graph)}>
              <Plus aria-hidden="true" /> {t('添加选项')}
            </button>
          </section>
          <section className="istory-section">
            <h3>{t('限时选择')}</h3>
            <label className="istory-check">
              <input
                type="checkbox"
                checked={Boolean(segment.timer)}
                disabled={!segment.choices.length}
                onChange={event => patch({ timer: event.target.checked ? { seconds: 10, default_choice: segment.choices.find(item => !item.condition)?.id ?? segment.choices[0]?.id ?? '' } : null })}
              />
              {t('到时间自动选择')}
            </label>
            {segment.timer && (
              <div className="istory-inline">
                <Field label={t('秒数')}>
                  <NumberField label={t('秒数')} min={1} max={120} value={segment.timer.seconds} onChange={value => patch({ timer: { ...segment.timer!, seconds: Math.round(Math.max(1, Math.min(120, value ?? 10))) } })} />
                </Field>
                <Field label={t('默认选项')}>
                  <select value={segment.timer.default_choice} onChange={event => patch({ timer: { ...segment.timer!, default_choice: event.target.value } })}>
                    <option value="">{t('（未选择）')}</option>
                    {segment.choices.map(choice => <option key={choice.id} value={choice.id}>{choice.text || choice.id}</option>)}
                  </select>
                </Field>
              </div>
            )}
          </section>
          <section className="istory-section">
            <h3>{t('自动路由')}</h3>
            <p className="istory-hint">{t('不用观众操作，按顺序走第一条成立的路由；都不成立时才显示选项。适合用变量决定结局。')}</p>
            {segment.routes.map((route, index) => (
              <article className={`istory-edge-card ${selectedEdge === route.id ? 'is-selected' : ''}`} key={route.id} data-route={route.id}>
                <div className="istory-inline">
                  <Field label={t('去往')}>
                    <TargetSelect graph={graph} label={t('去往')} value={route.target} onChange={target => edit(current => connectEdge(current, segment.id, route.id, target))} />
                  </Field>
                  <RowTools
                    onUp={index ? () => edit(current => moveRoute(current, segment.id, route.id, -1)) : undefined}
                    onDown={index < segment.routes.length - 1 ? () => edit(current => moveRoute(current, segment.id, route.id, 1)) : undefined}
                    onDelete={() => edit(current => deleteRoute(current, segment.id, route.id))}
                    deleteLabel={t('删除这条路由')}
                  />
                </div>
                <ConditionEditor value={route.condition} variables={graph.variables} onChange={condition => edit(current => updateRoute(current, segment.id, route.id, { condition }))} />
                {!route.condition && <p className="istory-hint">{t('没有条件：一定走这条，后面的出口都用不上。')}</p>}
              </article>
            ))}
            <button type="button" className="istory-link" disabled={segment.routes.length >= MAX_ROUTES} onClick={() => edit(current => addRoute(current, segment.id).graph)}>
              <Plus aria-hidden="true" /> {t('添加路由')}
            </button>
          </section>
        </>
      )}
    </div>
  );
}
