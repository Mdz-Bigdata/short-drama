import { useState } from 'react';

import type { StageContact, StageLandmark, StageOperation, StagePlan, StageShot } from '../../spatial/spatialTypes';
import { contactOn, contactOperation, handOf, HAND_LABELS, isSeat, seatOf, topOf, type Hand } from '../lib/contacts';

// The 「接触」 part of the inspector: what a prop is held by or rests on, and what an actor sits on.
// Every change is one set_contact / remove_contact edit; the desk derives its undo like any other.

type Scope = 'shot' | 'scene' | 'listed';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  editable: boolean;
  send: (label: string, operations: StageOperation[]) => void;
}

const HANDS = Object.keys(HAND_LABELS) as Hand[];

function scopeOfContact(contact: StageContact, shot: StageShot | undefined): Scope {
  if (!contact.shot_ids.length) return 'scene';
  return contact.shot_ids.length === 1 && contact.shot_ids[0] === shot?.shot_id ? 'shot' : 'listed';
}

/** Taking a contact off where it is in force: this shot only for one tied to shots, everywhere for a whole-scene one. */
function removal(contact: StageContact, shot: StageShot | undefined): StageOperation {
  return contact.shot_ids.length && shot ? { op: 'remove_contact', target: contact.target, shot_id: shot.shot_id } : { op: 'remove_contact', target: contact.target };
}

/** 本镜 / 整场, and the shots a planner-made contact names when it is neither. */
function ScopeField({ value, contact, shot, disabled, onChange }: {
  value: Scope; contact?: StageContact; shot?: StageShot; disabled: boolean; onChange: (scope: Scope) => void;
}) {
  return (
    <label className="desk-field">
      <span>生效范围</span>
      <select aria-label="接触生效范围" value={value} disabled={disabled} onChange={event => onChange(event.target.value as Scope)}>
        {shot && <option value="shot">本镜生效</option>}
        <option value="scene">整场</option>
        {value === 'listed' && contact && <option value="listed">第 {contact.shot_ids.join('、')} 镜</option>}
      </select>
    </label>
  );
}

/**
 * The contact made again for `ids`. A new contact only takes its own shots out of the others on the
 * target, so narrowing one to this shot takes it off everywhere first.
 */
function rescoped(contact: StageContact, ids: number[]): StageOperation[] {
  const narrower = ids.length > 0 && (!contact.shot_ids.length || contact.shot_ids.some(id => !ids.includes(id)));
  return [...(narrower ? [{ op: 'remove_contact', target: contact.target }] : []), { ...contactOperation(contact), shot_ids: ids }];
}

function useScope(contact: StageContact | undefined, shot: StageShot | undefined) {
  // Before there is a contact, the scope is only a choice for the one about to be made.
  const [sceneWide, setSceneWide] = useState(false);
  const scope: Scope = contact ? scopeOfContact(contact, shot) : sceneWide || !shot ? 'scene' : 'shot';
  const shotIds = (wanted: Scope): number[] => (wanted === 'scene' || !shot ? [] : wanted === 'shot' ? [shot.shot_id] : contact?.shot_ids ?? [shot.shot_id]);
  return { scope, shotIds, setSceneWide };
}

export function PropContacts({ plan, shot, landmark, editable, send }: Props & { landmark: StageLandmark }) {
  const contact = contactOn(plan, shot?.shot_id, landmark.name);
  const { scope, shotIds, setSceneWide } = useScope(contact, shot);
  const holding = contact?.kind === 'hold' ? contact : undefined;
  const resting = contact?.kind === 'rest' ? contact : undefined;
  const people = plan.actors.filter(actor => !actor.crowd_id);
  // Something is put on the set or on a piece of furniture; the one it is on now stays listed whatever it is.
  const supports = plan.landmarks.filter(item => item.name !== landmark.name && (item.kind === 'furniture' || item.kind === 'architecture' || item.name === resting?.support));
  const hold = (actor: string, hand: Hand, ids: number[]) => send(`${landmark.name} 交到 ${actor} ${HAND_LABELS[hand]}`, [{
    op: 'set_contact', kind: 'hold', actor, target: landmark.name, hand, shot_ids: ids,
  }]);
  const rest = (support: string, ids: number[]) => send(`把 ${landmark.name} 放到 ${support} 上`, [{
    op: 'set_contact', kind: 'rest', target: landmark.name, support, shot_ids: ids,
  }]);
  const release = (label: string) => { if (contact) send(label, [removal(contact, shot)]); };
  return (
    <section className="desk-contacts" aria-label="接触">
      <h3>接触</h3>
      <div className="desk-inspector__grid">
        <label className="desk-field">
          <span>拿在谁手里</span>
          <select
            aria-label="拿在谁手里" value={holding?.actor ?? ''} disabled={!editable}
            onChange={event => (event.target.value ? hold(event.target.value, holding ? handOf(holding) : 'right', shotIds(scope)) : release(`${landmark.name} 离手`))}
          >
            <option value="">不拿在手里</option>
            {people.map(actor => <option key={actor.id} value={actor.name}>{actor.name}</option>)}
          </select>
        </label>
        <label className="desk-field">
          <span>哪只手</span>
          <select
            aria-label="哪只手" value={holding ? handOf(holding) : 'right'} disabled={!editable || !holding}
            onChange={event => { if (holding) hold(holding.actor, event.target.value as Hand, holding.shot_ids); }}
          >
            {HANDS.map(hand => <option key={hand} value={hand}>{HAND_LABELS[hand]}</option>)}
          </select>
        </label>
        <label className="desk-field">
          <span>放在哪件东西上</span>
          <select
            aria-label="放在哪件东西上" value={resting?.support ?? ''} disabled={!editable}
            onChange={event => (event.target.value ? rest(event.target.value, shotIds(scope)) : release(`${landmark.name} 不再放在 ${resting?.support ?? ''} 上`))}
          >
            <option value="">不放在别的东西上</option>
            {supports.map(item => <option key={item.id} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <ScopeField
          value={scope} contact={contact} shot={shot} disabled={!editable}
          onChange={wanted => {
            if (!contact) { setSceneWide(wanted === 'scene'); return; }
            send(`调整 ${landmark.name} 接触范围`, rescoped(contact, shotIds(wanted)));
          }}
        />
      </div>
      {holding && <p className="desk-inspector__empty">跟着{holding.actor}的{HAND_LABELS[handOf(holding)]}走；要单独移动，先选「不拿在手里」。</p>}
      {resting && <p className="desk-inspector__empty">贴在「{resting.support}」的台面上，只能在台面范围内挪动。</p>}
    </section>
  );
}

export function ActorContacts({ plan, shot, actor, editable, send }: Props & { actor: string }) {
  const seat = seatOf(plan, shot?.shot_id, actor);
  const { scope, shotIds, setSceneWide } = useScope(seat, shot);
  const seats = plan.landmarks.filter(item => isSeat(item) || item.name === seat?.target);
  const sit = (target: string) => send(`${actor} 坐到 ${target} 上`, [
    ...(seat && seat.target !== target ? [removal(seat, shot)] : []),
    { op: 'set_contact', kind: 'sit', actor, target, shot_ids: shotIds(scope) },
  ]);
  return (
    <section className="desk-contacts" aria-label="接触">
      <h3>接触</h3>
      <div className="desk-inspector__grid">
        <label className="desk-field">
          <span>坐在哪件家具上</span>
          <select
            aria-label="坐在哪件家具上" value={seat?.target ?? ''} disabled={!editable}
            onChange={event => (event.target.value ? sit(event.target.value) : seat && send(`${actor} 站起来`, [removal(seat, shot)]))}
          >
            <option value="">不坐</option>
            {seats.map(item => <option key={item.id} value={item.name}>{item.name}（{topOf(item).toFixed(2)} 米高）</option>)}
          </select>
        </label>
        <ScopeField
          value={scope} contact={seat} shot={shot} disabled={!editable}
          onChange={wanted => {
            if (!seat) { setSceneWide(wanted === 'scene'); return; }
            send(`调整 ${actor} 接触范围`, rescoped(seat, shotIds(wanted)));
          }}
        />
      </div>
      {!seats.length && <p className="desk-inspector__empty">场上没有台面 0.3–0.7 米高、能坐的家具。</p>}
      {seat && <p className="desk-inspector__empty">坐在「{seat.target}」正中；要单独移动，先选「不坐」。</p>}
    </section>
  );
}
