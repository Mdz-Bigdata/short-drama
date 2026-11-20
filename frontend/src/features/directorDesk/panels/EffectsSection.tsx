import { useState } from 'react';
import { Crosshair, Plus, Trash2 } from 'lucide-react';

import type { GroundPoint, StageEffect, StageOperation, StagePlan, StageShot } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import {
  EFFECT_KINDS, EFFECT_RADIUS, MAX_EFFECTS, effectName, effectNumber, effectsOf, effectsOn, kindOf, nextEffectId, placeFor,
} from '../lib/effects';
import { DraftInput } from './fields';

// 「特效占位」：这一场地面上手动放的特效标记。每次改动是一条 set_effect / remove_effect，撤销跟别的编辑一样。
// 标记只进白模站位图和三维视图（红圈），不进机位截图，也不写进视频提示词。

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  selection: SelectionRef[];
  editable: boolean;
  onCommit: (request: EditRequest) => void;
}

type Scope = 'shot' | 'scene' | 'listed';

const round = (value: number) => Math.round(value * 100) / 100;

function scopeOf(effect: StageEffect, shot: StageShot | undefined): Scope {
  if (!effect.shot_ids.length) return 'scene';
  return effect.shot_ids.length === 1 && effect.shot_ids[0] === shot?.shot_id ? 'shot' : 'listed';
}

/** The ground point of whatever is selected, for 「移到选中处」. */
function selectedPoint(plan: StagePlan, selection: SelectionRef[]): GroundPoint | null {
  const picked = selection[0];
  if (picked?.kind === 'actor') return plan.actors.find(item => item.name === picked.name)?.position ?? null;
  if (picked?.kind === 'landmark') return plan.landmarks.find(item => item.name === picked.name)?.position ?? null;
  return null;
}

export function EffectsSection({ plan, shot, selection, editable, onCommit }: Props) {
  const [kind, setKind] = useState(EFFECT_KINDS[1].id);
  const [problem, setProblem] = useState('');
  const effects = effectsOf(plan);
  const onNow = effectsOn(plan, shot?.shot_id);
  const cast = plan.actors.filter(actor => !actor.crowd_id);
  const here = selectedPoint(plan, selection);
  const send = (label: string, operations: StageOperation[]) => { setProblem(''); onCommit({ label, operations }); };
  const change = (effect: StageEffect, label: string, fields: Record<string, unknown>) => send(label, [{ op: 'set_effect', id: effect.id, ...fields }]);

  const add = () => {
    if (effects.length >= MAX_EFFECTS) { setProblem(`这一场最多放 ${MAX_EFFECTS} 个特效占位。`); return; }
    const { position, source } = placeFor(plan, selection);
    send(`放一个${kindOf(kind).label}占位`, [{
      op: 'set_effect', id: nextEffectId(effects), kind, position, radius_m: kindOf(kind).radius, source, note: '',
      shot_ids: shot ? [shot.shot_id] : [],
    }]);
  };

  const number = (text: string, input: HTMLInputElement, low: number, high: number, fallback: number, done: (value: number) => void) => {
    const value = Number(text);
    if (!text.trim() || !Number.isFinite(value) || value < low || value > high) {
      setProblem(`请填 ${low} 到 ${high} 之间的数。`);
      input.value = String(fallback);
      return;
    }
    if (round(value) !== fallback) done(round(value));
  };

  return (
    <section className="desk-effects" aria-label="特效占位">
      <h3>特效占位</h3>
      <p className="desk-inspector__empty">
        在地面上标出特效的中心和范围（爆炸、冲击波、火焰…），白模站位图会画成编号的圈（VFX-01…）。只是预演占位：不进机位截图，也不写进视频提示词。
      </p>
      {effects.map(effect => {
        const index = onNow.findIndex(item => item.id === effect.id);
        const scope = scopeOf(effect, shot);
        const title = index >= 0 ? `${effectNumber(index)} ${effectName(effect)}` : `${effectName(effect)}（第 ${effect.shot_ids.join('、')} 镜）`;
        return (
          <fieldset key={effect.id} className={`desk-effects__item ${index >= 0 ? '' : 'is-off'}`} disabled={!editable}>
            <legend>{title}</legend>
            <div className="desk-inspector__grid">
              <label className="desk-field">
                <span>种类</span>
                <select aria-label={`${title} 的种类`} value={effect.kind} onChange={event => change(effect, `改成${kindOf(event.target.value).label}占位`, { kind: event.target.value })}>
                  {EFFECT_KINDS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </label>
              <label className="desk-field">
                <span>范围半径（米）</span>
                <DraftInput
                  aria-label={`${title} 的范围半径`} inputMode="decimal" value={effect.radius_m}
                  onDone={(text, input) => number(text, input, EFFECT_RADIUS.low, EFFECT_RADIUS.high, effect.radius_m, value => change(effect, `调整${effectName(effect)}范围`, { radius_m: value }))}
                />
              </label>
              <label className="desk-field">
                <span>谁发出的</span>
                <select aria-label={`${title} 由谁发出`} value={effect.source} onChange={event => change(effect, `改${effectName(effect)}的发出者`, { source: event.target.value })}>
                  <option value="">没有发出者</option>
                  {cast.map(actor => <option key={actor.id} value={actor.name}>{actor.name}</option>)}
                </select>
              </label>
              <label className="desk-field">
                <span>生效范围</span>
                <select
                  aria-label={`${title} 的生效范围`} value={scope}
                  onChange={event => change(effect, `调整${effectName(effect)}生效范围`, { shot_ids: event.target.value === 'scene' || !shot ? [] : [shot.shot_id] })}
                >
                  {shot && <option value="shot">本镜生效</option>}
                  <option value="scene">整场</option>
                  {scope === 'listed' && <option value="listed">第 {effect.shot_ids.join('、')} 镜</option>}
                </select>
              </label>
              <label className="desk-field">
                <span>左右 X（米）</span>
                <DraftInput
                  aria-label={`${title} 的 X`} inputMode="decimal" value={effect.position[0]}
                  onDone={(text, input) => number(text, input, -500, 500, effect.position[0], value => change(effect, `移动${effectName(effect)}`, { position: [value, effect.position[1]] }))}
                />
              </label>
              <label className="desk-field">
                <span>前后 Z（米）</span>
                <DraftInput
                  aria-label={`${title} 的 Z`} inputMode="decimal" value={effect.position[1]}
                  onDone={(text, input) => number(text, input, -500, 500, effect.position[1], value => change(effect, `移动${effectName(effect)}`, { position: [effect.position[0], value] }))}
                />
              </label>
              <label className="desk-field is-wide">
                <span>叫法（可不填，最多 40 字）</span>
                <DraftInput
                  aria-label={`${title} 的叫法`} maxLength={40} placeholder={kindOf(effect.kind).label} value={effect.note}
                  onDone={text => { if (text.trim() !== effect.note) change(effect, `改${effectName(effect)}的叫法`, { note: text.trim() }); }}
                />
              </label>
            </div>
            <div className="desk-effects__actions">
              <button
                type="button" className="desk-button" disabled={!here} title={here ? '把中心移到选中的人物或物件脚下' : '先在场上选中一个人物或物件'}
                onClick={() => here && change(effect, `移动${effectName(effect)}`, { position: [round(here[0]), round(here[1])] })}
              ><Crosshair aria-hidden="true" /> 移到选中处</button>
              <button type="button" className="desk-button" onClick={() => send(`删除${effectName(effect)}占位`, [{ op: 'remove_effect', id: effect.id }])}>
                <Trash2 aria-hidden="true" /> 删除
              </button>
            </div>
          </fieldset>
        );
      })}
      {editable && (
        <div className="desk-effects__add">
          <label className="desk-field">
            <span>新占位的种类</span>
            <select aria-label="新占位的种类" value={kind} onChange={event => setKind(event.target.value)}>
              {EFFECT_KINDS.map(item => <option key={item.id} value={item.id}>{item.label}（默认 {item.radius} 米）</option>)}
            </select>
          </label>
          <button type="button" className="desk-button" onClick={add}><Plus aria-hidden="true" /> 放一个</button>
        </div>
      )}
      {editable && (
        <p className="desk-inspector__empty">
          新占位放在选中人物面前 1 米（并记他为发出者）、选中物件的位置，或没选中时放在人物中间；默认只在本镜生效。用「选择」或「移动」工具时，可以在三维视图里按住圈心的红色圆点直接拖。
        </p>
      )}
      {problem && <p className="desk-field__problem" role="alert">{problem}</p>}
    </section>
  );
}
