import { useCallback, useEffect, useRef, useState } from 'react';
import { FlipHorizontal2, RotateCcw, Save, Trash2 } from 'lucide-react';

import { actorsInShot, type StageFigure, type StageOperation, type StagePlan, type StagePose, type StageShot } from '../../spatial/spatialTypes';
import { overrideFor, poseOperation } from '../deskOperations';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { MAX_POSE_NAME, deleteSavedPose, listSavedPoses, savePose, type SavedPose } from '../directorDeskApi';
import { HUMANOID_CLIPS, clipForPosture, humanoidClip } from '../lib/humanoidClips';
import {
  FINGER_PRESETS, POSE_CONTROLS, POSE_GROUPS, POSE_PRESETS, clampControl, clampPose, controlRange, expandFingerPreset, jointsOf, mirrorPose,
  normalizeBodyType, type FingerPresetId, type Joints, type PoseControl, type Side,
} from '../lib/poses';
import { crowdOf } from '../lib/stageMath';
import { BODY_TYPES, FIGURE_LABELS, actorColor } from '../three/stageLook';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  selection: SelectionRef[];
  editable: boolean;
  shotOnly: boolean;
  footLock: boolean;
  onShotOnly: (value: boolean) => void;
  onFootLock: (value: boolean) => void;
  onCommit: (request: EditRequest) => void;
  onPreview: (operations: StageOperation[] | null) => void;
}

const FIGURES: StageFigure[] = ['standin', 'mannequin', 'humanoid'];

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** A slider that draws while it moves and saves once, when it is let go; the number beside it saves on blur. */
function JointField({ control, value, range, disabled, onPreview, onCommit }: {
  control: PoseControl; value: number; range: [number, number]; disabled: boolean;
  onPreview: (value: number) => void; onCommit: (value: number) => void;
}) {
  const pending = useRef<number | null>(null);
  const armed = useRef(false);
  const release = useCallback(() => {
    armed.current = false;
    if (pending.current === null) return;
    const next = pending.current;
    pending.current = null;
    onCommit(next);
  }, [onCommit]);
  // The thumb is let go wherever the pointer is by then, not necessarily over the slider.
  const arm = () => {
    if (armed.current) return;
    armed.current = true;
    const once = () => {
      window.removeEventListener('pointerup', once);
      window.removeEventListener('mouseup', once);
      release();
    };
    window.addEventListener('pointerup', once);
    window.addEventListener('mouseup', once);
  };
  useEffect(() => () => { armed.current = false; }, []);
  const typed = (text: string) => {
    const next = Number(text);
    if (text.trim() === '' || !Number.isFinite(next)) return;
    const clamped = Math.min(range[1], Math.max(range[0], next));
    if (clamped !== value) onCommit(clamped);
  };
  return (
    <div className="desk-pose__joint">
      <span>{control.label}</span>
      <input
        type="range" aria-label={control.label} min={range[0]} max={range[1]} step={control.step} value={value} disabled={disabled}
        onChange={event => { pending.current = Number(event.target.value); onPreview(pending.current); arm(); }}
        onKeyUp={release} onBlur={release}
      />
      <input
        key={value} type="number" aria-label={`${control.label} 数值`} inputMode="decimal" min={range[0]} max={range[1]} step={control.step}
        defaultValue={value} disabled={disabled}
        onBlur={event => typed(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }}
      />
    </div>
  );
}

export function PosePanel({ plan, shot, selection, editable, shotOnly, footLock, onShotOnly, onFootLock, onCommit, onPreview }: Props) {
  const [saved, setSaved] = useState<SavedPose[]>([]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    listSavedPoses(controller.signal).then(setSaved).catch(error => { if (!controller.signal.aborted) setNotice(messageOf(error, '自定义姿势读取失败。')); });
    return () => controller.abort();
  }, []);

  const library = useCallback(async (work: () => Promise<SavedPose[]>, done: string) => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      setSaved(await work());
      setNotice(done);
    } catch (error) {
      setNotice(messageOf(error, '操作失败，请稍后重试。'));
    } finally {
      setBusy(false);
    }
  }, [busy]);

  const primary = selection[selection.length - 1];
  if (primary?.kind === 'crowd') {
    const crowd = crowdOf(plan, primary.id);
    const members = plan.actors.filter(item => item.crowd_id === primary.id);
    if (!members.length) return <section className="desk-pose" aria-label="姿势"><h2>姿势</h2><p className="desk-inspector__empty">这组群演已不在场上。</p></section>;
    // One operation for the whole array: forty people are not switched one at a time.
    const wholeCrowd = (label: string, fields: Record<string, unknown>) =>
      onCommit({ label: `${crowd?.label || '群演'}：${label}`, operations: [{ op: 'set_figure', crowd_id: primary.id, ...fields }] });
    const shared = <T,>(read: (actor: typeof members[number]) => T, fallback: T): T | null => {
      const first = read(members[0]) ?? fallback;
      return members.every(item => (read(item) ?? fallback) === first) ? first : null;
    };
    const figure = shared(item => item.figure, 'standin' as StageFigure);
    const bodyType = shared(item => normalizeBodyType(item.body_type), 'standard');
    return (
      <section className="desk-pose" aria-label="姿势">
        <h2>{crowd?.label || '群演'} <small>{members.length} 人</small></h2>
        <div className="desk-segment is-wide" role="radiogroup" aria-label="整组人偶类型">
          {FIGURES.map(kind => (
            <button
              key={kind} type="button" role="radio" aria-checked={figure === kind} className={figure === kind ? 'is-active' : ''} disabled={!editable}
              onClick={() => wholeCrowd(`整组改为${FIGURE_LABELS[kind]}`, { figure: kind })}
            >{FIGURE_LABELS[kind]}</button>
          ))}
        </div>
        {figure !== 'standin' && <p className="desk-pose__warning" role="note">整组白模带四肢：群演越多越费显卡，也更需要在动作描述里写清肢体动作</p>}
        {figure === null && <p className="desk-inspector__empty">这组群演的人偶类型不一致，点一个按钮会把整组统一过去。</p>}
        <div className="desk-inspector__grid">
          <label className="desk-field">
            <span>体型</span>
            <select aria-label="整组体型" value={bodyType ?? ''} disabled={!editable} onChange={event => wholeCrowd('整组调整体型', { body_type: event.target.value })}>
              {bodyType === null && <option value="">（不一致）</option>}
              {BODY_TYPES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="desk-field">
            <span>颜色</span>
            <input
              key={actorColor(members[0])} type="color" aria-label="整组颜色" defaultValue={actorColor(members[0])} disabled={!editable}
              onBlur={event => { if (event.target.value !== actorColor(members[0])) wholeCrowd('整组调整颜色', { color: event.target.value }); }}
            />
          </label>
          <button type="button" className="desk-button" disabled={!editable || !members.some(item => item.color)} onClick={() => wholeCrowd('整组恢复群演色', { color: '' })}>用群演色</button>
        </div>
        <p className="desk-captures__note">姿势按单人设置：在大纲里点开这组，选中其中一个人再摆。</p>
      </section>
    );
  }
  const actor = primary?.kind === 'actor' ? actorsInShot(plan, shot).find(item => item.name === primary.name) : undefined;
  if (!actor) {
    return (
      <section className="desk-pose" aria-label="姿势">
        <h2>姿势</h2>
        <p className="desk-inspector__empty">{primary?.kind === 'actor' ? '本镜中该角色不在场。' : '选择一个角色后，可以切换人偶类型、套用预设或逐个关节摆姿势；选中一整组群演可以统一切换人偶类型。'}</p>
      </section>
    );
  }

  const figure = actor.figure ?? 'standin';
  const bodyType = normalizeBodyType(actor.body_type);
  // A shot that already poses this actor on its own is what the viewport shows, so that is what gets edited.
  const overridden = Boolean(overrideFor(shot, actor.name)?.pose);
  const perShot = Boolean(shot) && (shotOnly || overridden);
  const shotId = perShot ? shot?.shot_id : undefined;
  const joints = jointsOf(actor);
  const pose: StagePose = { preset: actor.pose?.preset || '', joints, clip: actor.pose?.clip || '', clip_phase: actor.pose?.clip_phase ?? 0 };
  const disabled = !editable;

  const operation = (next: StagePose | null) => poseOperation(actor.name, shotId, next && { ...next, joints: clampPose(next.joints, bodyType) });
  const commit = (label: string, next: StagePose | null) => onCommit({ label: `${actor.name}：${label}`, operations: [operation(next)] });
  const preview = (next: StagePose) => onPreview([operation(next)]);
  const withJoints = (changes: Joints): StagePose => ({ ...pose, joints: { ...joints, ...changes } });
  const setFigure = (label: string, fields: Record<string, unknown>) => onCommit({ label: `${actor.name}：${label}`, operations: [{ op: 'set_figure', name: actor.name, ...fields }] });
  const color = actorColor(actor);
  const clip = humanoidClip(pose.clip || clipForPosture(actor.posture));
  const withClip = (clipId: string, phase: number): StagePose => ({ ...pose, preset: humanoidClip(clipId).posture, clip: clipId, clip_phase: phase });

  return (
    <section className="desk-pose" aria-label="姿势">
      <h2>{actor.name} <small>{FIGURE_LABELS[figure]}</small></h2>
      <div className="desk-segment is-wide" role="radiogroup" aria-label="人偶类型">
        {FIGURES.map(kind => (
          <button key={kind} type="button" role="radio" aria-checked={figure === kind} className={figure === kind ? 'is-active' : ''} disabled={disabled} onClick={() => { if (kind !== figure) setFigure(`改为${FIGURE_LABELS[kind]}`, { figure: kind }); }}>
            {FIGURE_LABELS[kind]}
          </button>
        ))}
      </div>
      {figure !== 'standin' && <p className="desk-pose__warning" role="note">白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化</p>}
      <div className="desk-inspector__grid">
        <label className="desk-field">
          <span>体型</span>
          <select aria-label="体型" value={bodyType} disabled={disabled} onChange={event => setFigure('调整体型', { body_type: event.target.value })}>
            {BODY_TYPES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <label className="desk-field">
          <span>颜色</span>
          <input key={color} type="color" aria-label="颜色" defaultValue={color} disabled={disabled} onBlur={event => { if (event.target.value !== color) setFigure('调整颜色', { color: event.target.value }); }} />
        </label>
        <button type="button" className="desk-button" disabled={disabled || !actor.color} onClick={() => setFigure('恢复角色色', { color: '' })}>用角色色</button>
      </div>

      <div className="desk-toggles">
        <label title={overridden ? '本镜已有单独的姿势，修改只作用于本镜' : undefined}>
          <input type="checkbox" checked={perShot} disabled={!shot || overridden} onChange={event => onShotOnly(event.target.checked)} /> 只改这一镜
        </label>
        {figure === 'mannequin' && <label><input type="checkbox" checked={footLock} onChange={event => onFootLock(event.target.checked)} /> 拖动脚踝时锁定脚高</label>}
      </div>
      {overridden && (
        <button type="button" className="desk-button" disabled={disabled} onClick={() => onCommit({ label: `${actor.name}：清除本镜姿势`, operations: [poseOperation(actor.name, shot?.shot_id, null)] })}>
          清除本镜姿势，回到全场姿势
        </button>
      )}

      {figure === 'standin' && <p className="desk-inspector__empty">白模柱体没有四肢，是给视频模型最安全的参考。要摆姿势，先改为「关节人偶」或「蒙皮人形」。</p>}

      {figure === 'humanoid' && (
        <>
          <h3>动作片段</h3>
          <label className="desk-field is-wide">
            <span>片段</span>
            <select aria-label="动作片段" value={clip.id} disabled={disabled} onChange={event => commit(`动作 ${humanoidClip(event.target.value).name}`, withClip(event.target.value, 0))}>
              {HUMANOID_CLIPS.map(item => <option key={item.id} value={item.id}>{item.group} · {item.name}</option>)}
            </select>
          </label>
          <JointField
            control={{ key: 'clip_phase', label: `进度（共 ${clip.duration.toFixed(1)} 秒）`, group: 'torso', min: 0, max: 1, step: 0.01 }}
            value={pose.clip_phase ?? 0} range={[0, 1]} disabled={disabled}
            onPreview={value => preview(withClip(clip.id, value))} onCommit={value => commit('动作进度', withClip(clip.id, value))}
          />
        </>
      )}

      {figure === 'mannequin' && (
        <>
          <div className="desk-pose__actions">
            <button type="button" className="desk-button" disabled={disabled} onClick={() => commit('左右镜像', mirrorPose(pose))}><FlipHorizontal2 aria-hidden="true" /> 左右镜像</button>
            <button type="button" className="desk-button" disabled={disabled} onClick={() => commit('复位', { preset: 'stand', joints: {}, clip: '', clip_phase: 0 })}><RotateCcw aria-hidden="true" /> 复位</button>
          </div>
          <h3>预设姿势</h3>
          <div className="desk-pose__presets" role="group" aria-label="预设姿势">
            {POSE_PRESETS.map(preset => (
              <button key={preset.id} type="button" className={pose.preset === preset.id ? 'is-active' : ''} aria-pressed={pose.preset === preset.id} disabled={disabled} onClick={() => commit(preset.label, { preset: preset.id, joints: preset.joints, clip: '', clip_phase: 0 })}>
                {preset.label}
              </button>
            ))}
          </div>
          <h3>关节</h3>
          {POSE_GROUPS.map(group => {
            const side: Side | null = group.id === 'leftHand' ? 'left' : group.id === 'rightHand' ? 'right' : null;
            return (
              <details key={group.id} className="desk-pose__group">
                <summary>{group.label}</summary>
                {side && (
                  <div className="desk-pose__fingers" role="group" aria-label={`${group.label}手型`}>
                    {FINGER_PRESETS.map(item => (
                      <button key={item.id} type="button" className="desk-button" disabled={disabled} onClick={() => commit(`${group.label}${item.label}`, withJoints(expandFingerPreset(side, item.id as FingerPresetId)))}>{item.label}</button>
                    ))}
                  </div>
                )}
                {POSE_CONTROLS.filter(control => control.group === group.id).map(control => (
                  <JointField
                    key={control.key} control={control} value={joints[control.key] ?? 0} range={controlRange(control.key, bodyType) ?? [control.min, control.max]} disabled={disabled}
                    onPreview={value => preview(withJoints({ [control.key]: clampControl(control.key, value, bodyType) }))}
                    onCommit={value => commit(control.label, withJoints({ [control.key]: clampControl(control.key, value, bodyType) }))}
                  />
                ))}
              </details>
            );
          })}

          <h3>自定义姿势 <small>{saved.length}</small></h3>
          <p className="desk-captures__note">保存在你的账号下，换一个项目也能用。</p>
          <form
            className="desk-pose__save"
            onSubmit={event => {
              event.preventDefault();
              const label = name.trim();
              if (!label) { setNotice('先给姿势起个名字。'); return; }
              const replacing = saved.some(item => item.name === label);
              if (replacing && !window.confirm(`已经有一个叫「${label}」的姿势，用当前姿势替换它吗？`)) return;
              void library(() => savePose(label, { preset: pose.preset, joints: clampPose(joints, 'standard'), clip: '', clip_phase: 0 }), `已保存「${label}」。`).then(() => setName(''));
            }}
          >
            <input aria-label="姿势名称" placeholder="姿势名称" value={name} maxLength={MAX_POSE_NAME} onChange={event => setName(event.target.value)} />
            <button type="submit" className="desk-button" disabled={busy}><Save aria-hidden="true" /> 保存为自定义姿势</button>
          </form>
          {notice && <p className="desk-captures__notice" role="status">{notice}</p>}
          <ul className="desk-pose__saved">
            {saved.map(item => (
              <li key={item.id}>
                <span>{item.name}</span>
                <button type="button" className="desk-button" aria-label={`应用 ${item.name}`} disabled={disabled} onClick={() => commit(`应用「${item.name}」`, { preset: item.pose.preset || '', joints: item.pose.joints || {}, clip: '', clip_phase: 0 })}>应用</button>
                <button type="button" className="desk-icon" aria-label={`删除 ${item.name}`} disabled={busy} onClick={() => { if (window.confirm(`删除自定义姿势「${item.name}」？`)) void library(() => deleteSavedPose(item.id), '已删除。'); }}><Trash2 aria-hidden="true" /></button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
