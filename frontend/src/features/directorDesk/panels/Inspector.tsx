import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { actorsInShot, POSTURE_LABELS, type LandmarkShape, type StageLandmark, type StageOperation, type StagePlan, type StagePosture, type StageShot } from '../../spatial/spatialTypes';
import { actorMoveOperation, addLandmarkOperation } from '../deskOperations';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { contactOn, contactOperation, detachOperations, seatOf } from '../lib/contacts';
import { crowdMembers, crowdOf, distance2 } from '../lib/stageMath';
import { KIND_LABELS, SHAPE_LABELS, landmarkColor } from '../three/stageLook';
import { ActorContacts, PropContacts } from './ContactSection';
import { ColorField, DraftInput, NumberField } from './fields';
import { ModelBinding } from './ModelBinding';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  selection: SelectionRef[];
  editable: boolean;
  error: string;
  /** The element library the desk borrows models from is scoped to this project. */
  taskId: string;
  onCommit: (request: EditRequest) => void;
  onSelect: (ref: SelectionRef, additive: boolean) => void;
}

function LandmarkName({ landmark, plan, disabled, onRename }: { landmark: StageLandmark; plan: StagePlan; disabled: boolean; onRename: (name: string) => void }) {
  const [problem, setProblem] = useState('');
  // The note is about the name that was typed for this piece; another piece picked is a fresh start.
  const [shownFor, setShownFor] = useState(landmark.name);
  if (shownFor !== landmark.name) {
    setShownFor(landmark.name);
    setProblem('');
  }
  const send = (text: string, input: HTMLInputElement) => {
    const name = text.trim();
    if (!name || name === landmark.name) { setProblem(''); input.value = landmark.name; return; }
    // A taken name stays in the field, so the director can change a character instead of typing it again.
    if (plan.landmarks.some(item => item.name === name) || plan.actors.some(actor => actor.name === name)) { setProblem(`场上已经有「${name}」`); return; }
    setProblem('');
    onRename(name);
  };
  return (
    <label className="desk-field is-wide">
      <span>名称</span>
      <DraftInput value={landmark.name} maxLength={120} disabled={disabled} onDone={send} />
      {problem && <small className="desk-field__problem">{problem}</small>}
    </label>
  );
}

export function Inspector({ plan, shot, selection, editable, error, taskId, onCommit, onSelect }: Props) {
  const primary = selection[selection.length - 1];
  const send = (label: string, operations: StageOperation[], extra: Partial<EditRequest> = {}) => onCommit({ label, operations, ...extra });
  const alert = error && <p className="desk-inspector__error" role="alert">{error}</p>;

  if (!primary) {
    return (
      <section className="desk-inspector" aria-label="属性">
        <h2>属性</h2>
        {alert}
        <p className="desk-inspector__empty">在舞台或左侧大纲里选择一个角色、道具、群演或机位。按住 Shift 可多选，多选后移动会一起走。</p>
      </section>
    );
  }

  if (primary.kind === 'actor') {
    const actor = actorsInShot(plan, shot).find(item => item.name === primary.name);
    if (!actor) return <section className="desk-inspector" aria-label="属性"><h2>{primary.name}</h2><p className="desk-inspector__empty">本镜中该角色不在场。</p></section>;
    const others = actorsInShot(plan, shot).filter(item => item.name !== actor.name && shot?.subjects.includes(item.name));
    const move = (change: { position?: [number, number]; yaw_deg?: number }) => send(`调整 ${actor.name}`, [actorMoveOperation(shot, actor.name, change)]);
    // Someone on a seat is where the seat is: the mark only comes back into play once they stand up.
    const seated = Boolean(seatOf(plan, shot?.shot_id, actor.name));
    return (
      <section className="desk-inspector" aria-label="属性">
        <h2>{actor.name} <small>{actor.role === 'principal' ? '主角' : '配角'}</small></h2>
        {alert}
        <div className="desk-inspector__grid">
          <NumberField label="X（米）" value={actor.position[0]} min={-500} max={500} disabled={!editable || seated} onCommit={value => move({ position: [value, actor.position[1]] })} />
          <NumberField label="Z（米）" value={actor.position[1]} min={-500} max={500} disabled={!editable || seated} onCommit={value => move({ position: [actor.position[0], value] })} />
          <NumberField label="朝向（°）" value={actor.yaw_deg} min={-180} max={180} step={5} disabled={!editable} onCommit={value => move({ yaw_deg: value })} />
          <NumberField label="身高（米）" value={actor.height_m} min={0.4} max={3} step={0.05} disabled={!editable} onCommit={value => send(`调整 ${actor.name} 身高`, [{ op: 'move_actor', name: actor.name, height_m: value }])} />
          <label className="desk-field is-wide">
            <span>姿态</span>
            <select value={actor.posture} disabled={!editable} onChange={event => send(`调整 ${actor.name} 姿态`, [{ op: 'move_actor', name: actor.name, posture: event.target.value as StagePosture }])}>
              {(Object.keys(POSTURE_LABELS) as StagePosture[]).map(key => <option key={key} value={key}>{POSTURE_LABELS[key]}</option>)}
            </select>
          </label>
        </div>
        <ActorContacts key={actor.name} plan={plan} shot={shot} actor={actor.name} editable={editable} send={send} />
        <h3>与本镜其他主体的距离</h3>
        {others.length === 0
          ? <p className="desk-inspector__empty">本镜没有其他主体。</p>
          : (
            <ul className="desk-inspector__distances">
              {others.map(other => <li key={other.id}><span>{other.name}</span><strong>{distance2(actor.position, other.position).toFixed(2)} m</strong></li>)}
            </ul>
          )}
      </section>
    );
  }

  if (primary.kind === 'landmark') {
    const landmark = plan.landmarks.find(item => item.name === primary.name);
    if (!landmark) return null;
    const change = (label: string, fields: Record<string, unknown>) => send(label, [{ op: 'transform_landmark', name: landmark.name, ...fields }]);
    const onAxis = plan.axis.from_name === landmark.name || plan.axis.to_name === landmark.name;
    // A prop in a hand goes where the hand goes: where it stands and which way it faces are not its own.
    const held = contactOn(plan, shot?.shot_id, landmark.name)?.kind === 'hold';
    const rename = (name: string) => {
      // There is no rename operation: the piece is rebuilt under its new name in one all-or-nothing batch,
      // and every contact that named it is made again under the new name.
      const renamed = (plan.contacts || []).filter(item => item.target === landmark.name || item.support === landmark.name).map(item => ({
        ...contactOperation(item),
        target: item.target === landmark.name ? name : item.target,
        support: item.support === landmark.name ? name : item.support,
      }));
      send(`重命名 ${landmark.name}`, [
        ...detachOperations(plan, landmark.name),
        { op: 'remove_landmark', name: landmark.name }, addLandmarkOperation(landmark, name),
        ...(landmark.element_id ? [{ op: 'bind_landmark_model', name, element_id: landmark.element_id }] : []),
        ...renamed,
      ]);
      onSelect({ kind: 'landmark', name }, false);
    };
    const size = (index: 0 | 1 | 2, value: number) => {
      const next = [...landmark.size];
      next[index] = value;
      change(`调整 ${landmark.name} 尺寸`, { size: next });
    };
    return (
      <section className="desk-inspector" aria-label="属性">
        <h2>{landmark.name} <small>{SHAPE_LABELS[landmark.shape ?? 'box']}</small></h2>
        {alert}
        <div className="desk-inspector__grid">
          {/* Removing a piece the axis hangs on would drop the axis, so that one keeps its name. */}
          <LandmarkName landmark={landmark} plan={plan} disabled={!editable || onAxis} onRename={rename} />
          <label className="desk-field">
            <span>类别</span>
            <select value={landmark.kind} disabled={!editable} onChange={event => change(`调整 ${landmark.name} 类别`, { kind: event.target.value })}>
              {(Object.keys(KIND_LABELS) as StageLandmark['kind'][]).map(key => <option key={key} value={key}>{KIND_LABELS[key]}</option>)}
            </select>
          </label>
          <label className="desk-field">
            <span>形状</span>
            <select value={landmark.shape ?? 'box'} disabled={!editable} onChange={event => change(`调整 ${landmark.name} 形状`, { shape: event.target.value })}>
              {(Object.keys(SHAPE_LABELS) as LandmarkShape[]).map(key => <option key={key} value={key}>{SHAPE_LABELS[key]}</option>)}
            </select>
          </label>
          <NumberField label="宽（米）" value={landmark.size[0]} min={0.05} max={50} disabled={!editable} onCommit={value => size(0, value)} />
          <NumberField label="深（米）" value={landmark.size[1]} min={0.05} max={50} disabled={!editable} onCommit={value => size(1, value)} />
          <NumberField label="高（米）" value={landmark.size[2]} min={0.05} max={50} disabled={!editable} onCommit={value => size(2, value)} />
          <NumberField label="朝向（°）" value={landmark.yaw_deg ?? 0} min={-180} max={180} step={5} disabled={!editable || held} onCommit={value => change(`旋转 ${landmark.name}`, { yaw_deg: value })} />
          <NumberField label="X（米）" value={landmark.position[0]} min={-500} max={500} disabled={!editable || held} onCommit={value => change(`移动 ${landmark.name}`, { position: [value, landmark.position[1]] })} />
          <NumberField label="Z（米）" value={landmark.position[1]} min={-500} max={500} disabled={!editable || held} onCommit={value => change(`移动 ${landmark.name}`, { position: [landmark.position[0], value] })} />
          <ColorField label="颜色" value={landmarkColor(landmark)} disabled={!editable} onCommit={color => change(`调整 ${landmark.name} 颜色`, { color })} />
          <button type="button" className="desk-button" disabled={!editable || !landmark.color} onClick={() => change(`恢复 ${landmark.name} 颜色`, { color: '' })}>用类别色</button>
        </div>
        <PropContacts key={landmark.name} plan={plan} shot={shot} landmark={landmark} editable={editable} send={send} />
        <ModelBinding taskId={taskId} landmark={landmark} editable={editable} onCommit={onCommit} />
        <button type="button" className="desk-button is-danger" disabled={!editable} onClick={() => send(`删除 ${landmark.name}`, [...detachOperations(plan, landmark.name), { op: 'remove_landmark', name: landmark.name }])}>
          <Trash2 aria-hidden="true" /> 删除道具
        </button>
      </section>
    );
  }

  if (primary.kind === 'crowd') {
    const members = crowdMembers(plan, primary.id);
    const crowd = crowdOf(plan, primary.id);
    if (!crowd) return null;
    const center = crowd.center;
    // The seed is what rebuilds the same crowd; an array with no record cannot be brought back.
    const recorded = Boolean(plan.crowds?.some(item => item.id === crowd.id));
    const change = (label: string, fields: Record<string, unknown>) => send(label, [{ op: 'transform_crowd', crowd_id: primary.id, ...fields }]);
    return (
      <section className="desk-inspector" aria-label="属性">
        <h2>{crowd.label} <small>{members.length} 人</small></h2>
        {alert}
        <div className="desk-inspector__grid">
          <NumberField label="中心 X（米）" value={center[0]} min={-500} max={500} disabled={!editable} onCommit={value => change('移动群演', { center: [value, center[1]] })} />
          <NumberField label="中心 Z（米）" value={center[1]} min={-500} max={500} disabled={!editable} onCommit={value => change('移动群演', { center: [center[0], value] })} />
          <NumberField label="朝向（°）" value={crowd.yaw_deg} min={-180} max={180} step={5} disabled={!editable} onCommit={value => change('旋转群演', { yaw_deg: value })} />
          <NumberField label="间距（米）" value={crowd.spacing} min={0.3} max={10} disabled={!editable} onCommit={value => change('调整群演间距', { spacing: value })} />
        </div>
        <button
          type="button" className="desk-button is-danger" disabled={!editable}
          onClick={() => {
            if (recorded || window.confirm(`删除这组 ${members.length} 人的群演？此操作不能撤销，之前的撤销记录也会清空。`)) {
              send(`删除 ${crowd.label}`, [{ op: 'remove_crowd', crowd_id: crowd.id }], { barrier: true, irreversible: !recorded });
            }
          }}
        >
          <Trash2 aria-hidden="true" /> 删除群演
        </button>
      </section>
    );
  }

  const camera = plan.cameras.find(item => item.id === primary.id);
  if (!camera) return null;
  const moveCamera = (key: 'position' | 'target', index: 0 | 1 | 2, value: number) => {
    const next = [...camera[key]];
    next[index] = value;
    send(`调整 ${camera.label || camera.id}`, [{ op: 'move_camera', camera_id: camera.id, [key]: next }]);
  };
  const axes = ['X', 'Y', 'Z'] as const;
  return (
    <section className="desk-inspector" aria-label="属性">
      <h2>{camera.label || camera.id} <small>{camera.lens_mm}mm · {camera.shot_size || '—'}</small></h2>
      {alert}
      <h3>机位</h3>
      <div className="desk-inspector__grid is-three">
        {axes.map((axis, index) => <NumberField key={axis} label={`${axis}（米）`} value={camera.position[index]} min={index === 1 ? 0.05 : -500} max={500} disabled={!editable} onCommit={value => moveCamera('position', index as 0 | 1 | 2, value)} />)}
      </div>
      <h3>注视点</h3>
      <div className="desk-inspector__grid is-three">
        {axes.map((axis, index) => <NumberField key={axis} label={`${axis}（米）`} value={camera.target[index]} min={-500} max={500} disabled={!editable} onCommit={value => moveCamera('target', index as 0 | 1 | 2, value)} />)}
      </div>
      <p className="desk-inspector__empty">焦距、景别和候选机位在「机位」页里调整。</p>
    </section>
  );
}
