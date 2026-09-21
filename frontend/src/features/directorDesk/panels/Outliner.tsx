import { Eye, EyeOff, Lock, LockOpen, Plus, Users } from 'lucide-react';

import type { LandmarkShape, StagePlan, StageShot } from '../../spatial/spatialTypes';
import { refKey, type SelectionRef } from '../deskTypes';
import { crowdIds, crowdMembers, crowdOf } from '../lib/stageMath';
import { SHAPE_LABELS } from '../three/stageLook';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  selection: SelectionRef[];
  hidden: string[];
  locked: string[];
  editable: boolean;
  onSelect: (ref: SelectionRef, additive: boolean) => void;
  onToggleHidden: (key: string) => void;
  onToggleLocked: (key: string) => void;
  onAddProp: (shape: LandmarkShape) => void;
  onAddCrowd: () => void;
}

const SHAPES = Object.keys(SHAPE_LABELS) as LandmarkShape[];

export function Outliner({ plan, shot, selection, hidden, locked, editable, onSelect, onToggleHidden, onToggleLocked, onAddProp, onAddCrowd }: Props) {
  const selected = new Set(selection.map(refKey));
  const row = (ref: SelectionRef, title: string, detail: string) => {
    const key = refKey(ref);
    const isHidden = hidden.includes(key);
    const isLocked = locked.includes(key);
    return (
      <li key={key} className={`desk-outliner__row ${selected.has(key) ? 'is-selected' : ''} ${isHidden ? 'is-hidden' : ''}`}>
        <button type="button" className="desk-outliner__name" aria-pressed={selected.has(key)} onClick={event => onSelect(ref, event.shiftKey)}>
          <strong>{title}</strong>
          <small>{detail}</small>
        </button>
        {/* Visibility and lock are the operator's own view of the stage: never sent, never saved. */}
        <button type="button" className="desk-icon" aria-pressed={isHidden} aria-label={`${isHidden ? '显示' : '隐藏'} ${title}`} onClick={() => onToggleHidden(key)}>
          {isHidden ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </button>
        <button type="button" className="desk-icon" aria-pressed={isLocked} aria-label={`${isLocked ? '解锁' : '锁定'} ${title}`} onClick={() => onToggleLocked(key)}>
          {isLocked ? <Lock aria-hidden="true" /> : <LockOpen aria-hidden="true" />}
        </button>
      </li>
    );
  };
  const cast = plan.actors.filter(actor => !actor.crowd_id);
  const crowds = crowdIds(plan);
  const shotCameras = new Set([shot?.camera_id, ...(shot?.alt_camera_ids || [])]);

  return (
    <aside className="desk-outliner" aria-label="场景大纲">
      <section aria-label="角色">
        <h2>角色 <small>{cast.length}</small></h2>
        <ul>{cast.map(actor => row({ kind: 'actor', name: actor.name }, actor.name, shot?.subjects.includes(actor.name) ? '本镜主体' : actor.role === 'principal' ? '主角' : '配角'))}</ul>
      </section>
      <section aria-label="群演">
        <h2>
          群演 <small>{crowds.length}</small>
          <button type="button" className="desk-icon" aria-label="添加群演阵列" disabled={!editable} onClick={onAddCrowd}><Users aria-hidden="true" /></button>
        </h2>
        {crowds.length === 0 && <p className="desk-outliner__empty">还没有群演阵列</p>}
        <ul>{crowds.map(id => row({ kind: 'crowd', id }, crowdOf(plan, id)?.label || id, `${crowdMembers(plan, id).length} 人`))}</ul>
      </section>
      <section aria-label="道具">
        <h2>道具 <small>{plan.landmarks.length}</small></h2>
        <div className="desk-outliner__shapes" role="group" aria-label="添加道具">
          {SHAPES.map(shape => (
            <button key={shape} type="button" className="desk-chip" disabled={!editable} onClick={() => onAddProp(shape)}>
              <Plus aria-hidden="true" /> {SHAPE_LABELS[shape]}
            </button>
          ))}
        </div>
        <ul>{plan.landmarks.map(item => row({ kind: 'landmark', name: item.name }, item.name, SHAPE_LABELS[item.shape ?? 'box']))}</ul>
      </section>
      <section aria-label="机位">
        <h2>机位 <small>{plan.cameras.length}</small></h2>
        <ul>
          {plan.cameras.map(camera => row(
            { kind: 'camera', id: camera.id }, camera.label || camera.id,
            `${camera.lens_mm}mm${camera.id === shot?.camera_id ? ' · 本镜主机位' : shotCameras.has(camera.id) ? ' · 本镜候选' : ''}`,
          ))}
        </ul>
      </section>
    </aside>
  );
}
