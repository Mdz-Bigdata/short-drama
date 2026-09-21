import { useState, type ReactNode } from 'react';
import { Camera, CircleCheck, Eye, Plus, Star, Trash2, TriangleAlert } from 'lucide-react';

import type { StageCamera, StageOperation, StagePlan, StageShot } from '../../spatial/spatialTypes';
import type { EditRequest, GuideSettings } from '../deskTypes';
import { ANGLE_PRESETS, type AnglePresetId } from '../lib/anglePresets';
import { ASPECT_PRESETS, parseAspectRatio } from '../overlays/compositionGeometry';

interface Props {
  plan: StagePlan;
  shot?: StageShot;
  /** The lens the camera view is looking through. */
  lens?: StageCamera;
  guides: GuideSettings;
  editable: boolean;
  canUseView: boolean;
  /** The scene's backdrop is what the lens stands in front of, so it is edited here. */
  backdrop: ReactNode;
  onCommit: (request: EditRequest) => void;
  onPreview: (operations: StageOperation[] | null) => void;
  onLook: (cameraId: string) => void;
  onAddFromView: () => void;
  onAddPreset: (preset: AnglePresetId) => void;
  onGuides: (guides: Partial<GuideSettings>) => void;
}

const FOCALS = [18, 24, 35, 50, 85, 120];
const SIZES = ['全景', '中景', '近景', '特写'];
const GUIDE_TOGGLES: Array<{ key: 'frame' | 'thirds' | 'safe' | 'cross'; label: string }> = [
  { key: 'frame', label: '画幅遮幅' }, { key: 'thirds', label: '三分线' }, { key: 'safe', label: '9% 安全框' }, { key: 'cross', label: '中心十字' },
];

function ShotChecks({ plan, shot }: { plan: StagePlan; shot: StageShot }) {
  const flagged = plan.checks.filter(check => !check.passed && check.shot_ids.includes(shot.shot_id));
  return (
    <ul className="desk-checks" aria-label="本镜校验">
      {shot.screen.map(state => {
        const inFrame = state.visible;
        const clear = !state.occluded_by;
        return (
          <li key={state.name} className={inFrame && clear ? 'is-passed' : 'is-warning'}>
            {inFrame && clear ? <CircleCheck aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
            <span>
              <strong>{state.name}</strong>
              {!inFrame ? ' 出画，镜头里看不到' : !clear ? ` 被${state.occluded_by}挡住` : ` 在画内 · ${state.region || '居中'}，无遮挡`}
            </span>
          </li>
        );
      })}
      {flagged.map(check => (
        <li key={check.code} className={`is-${check.severity}`}>
          <TriangleAlert aria-hidden="true" />
          <span>{check.detail}</span>
        </li>
      ))}
      {shot.screen.length === 0 && flagged.length === 0 && <li className="is-passed"><CircleCheck aria-hidden="true" /><span>本镜没有遮挡或出画问题。</span></li>}
    </ul>
  );
}

export function CameraPanel({ plan, shot, lens, guides, editable, canUseView, backdrop, onCommit, onPreview, onLook, onAddFromView, onAddPreset, onGuides }: Props) {
  // The slider's value while it is held; `null` hands the display back to the plan.
  const [focal, setFocal] = useState<number | null>(null);
  const custom = guides.aspect !== '' && !(ASPECT_PRESETS as readonly string[]).includes(guides.aspect);
  const [customText, setCustomText] = useState(custom ? guides.aspect : '');

  if (!shot) return <section className="desk-camera" aria-label="机位"><h2>机位</h2><p className="desk-inspector__empty">本场还没有镜头。</p>{backdrop}</section>;

  const cameras = [shot.camera_id, ...(shot.alt_camera_ids || [])].flatMap(id => plan.cameras.filter(camera => camera.id === id));
  const filming = lens?.id === shot.camera_id;
  const lensOperation = (value: number): StageOperation => ({ op: 'move_camera', camera_id: lens?.id, lens_mm: value });
  // While the slider is held `lens` already carries the previewed focal length, so only a preset
  // click can be compared against it; a released slider always sends what it shows.
  const sendFocal = (value: number, held = false) => {
    setFocal(null);
    onPreview(null);
    if (lens && (held || value !== lens.lens_mm)) onCommit({ label: `焦距 ${value}mm`, operations: [lensOperation(value)] });
  };

  return (
    <section className="desk-camera" aria-label="机位">
      <h2><Camera aria-hidden="true" /> 第 {shot.shot_id} 镜机位</h2>
      <ul className="desk-camera__list">
        {cameras.map(camera => {
          const main = camera.id === shot.camera_id;
          return (
            <li key={camera.id} className={camera.id === lens?.id ? 'is-viewing' : ''}>
              <span>
                <strong>{camera.label || camera.id}</strong>
                <small>{main ? '主机位' : '候选'} · {camera.lens_mm}mm</small>
              </span>
              <button type="button" className="desk-icon" aria-pressed={camera.id === lens?.id} aria-label={`查看 ${camera.label || camera.id}`} onClick={() => onLook(camera.id)}><Eye aria-hidden="true" /></button>
              {!main && (
                <>
                  <button type="button" className="desk-icon" aria-label={`将 ${camera.label || camera.id} 设为主机位`} disabled={!editable} onClick={() => onCommit({ label: '设为主机位', operations: [{ op: 'use_camera', shot_id: shot.shot_id, camera_id: camera.id }] })}><Star aria-hidden="true" /></button>
                  <button type="button" className="desk-icon" aria-label={`删除 ${camera.label || camera.id}`} disabled={!editable} onClick={() => onCommit({ label: '删除候选机位', operations: [{ op: 'remove_camera', camera_id: camera.id }], barrier: true })}><Trash2 aria-hidden="true" /></button>
                </>
              )}
            </li>
          );
        })}
      </ul>
      <button type="button" className="desk-button" disabled={!editable || !canUseView} title={canUseView ? undefined : '需要先打开导演视角'} onClick={onAddFromView}>
        <Plus aria-hidden="true" /> 从当前视角添加机位
      </button>
      <h3>快速角度</h3>
      <div className="desk-chips" role="group" aria-label="快速角度">
        {ANGLE_PRESETS.map(preset => (
          <button key={preset.id} type="button" className="desk-chip" disabled={!editable || shot.subjects.length === 0} onClick={() => onAddPreset(preset.id)}>{preset.label}</button>
        ))}
      </div>

      <h3>焦距 {lens ? <small>{focal ?? lens.lens_mm}mm</small> : null}</h3>
      <div className="desk-chips" role="group" aria-label="焦距预设">
        {FOCALS.map(value => (
          <button key={value} type="button" className="desk-chip" aria-pressed={lens?.lens_mm === value} disabled={!editable || !lens} onClick={() => sendFocal(value)}>{value}</button>
        ))}
      </div>
      <input
        className="desk-camera__slider" type="range" aria-label="焦距（毫米）" min={8} max={300} step={1} disabled={!editable || !lens}
        value={focal ?? lens?.lens_mm ?? 35}
        // The lens view follows the thumb; the PATCH waits until it is let go.
        onChange={event => { const value = Number(event.target.value); setFocal(value); onPreview([lensOperation(value)]); }}
        onPointerUp={() => { if (focal !== null) sendFocal(focal, true); }}
        onKeyUp={() => { if (focal !== null) sendFocal(focal, true); }}
        onBlur={() => { if (focal !== null) sendFocal(focal, true); }}
      />

      <h3>景别</h3>
      <div className="desk-chips" role="group" aria-label="景别">
        {SIZES.map(size => (
          <button
            key={size} type="button" className="desk-chip" aria-pressed={filming && lens?.shot_size === size}
            // frame_shot re-frames the lens that films; a candidate is promoted first, then framed.
            disabled={!editable || !filming} title={filming ? undefined : '景别取景作用于主机位'}
            onClick={() => onCommit({ label: `取景 ${size}`, operations: [{ op: 'frame_shot', shot_id: shot.shot_id, size }], barrier: true })}
          >{size}</button>
        ))}
      </div>

      <h3>构图辅助</h3>
      <label className="desk-field is-wide">
        <span>画幅</span>
        <select
          aria-label="画幅" value={custom ? 'custom' : guides.aspect}
          onChange={event => {
            if (event.target.value !== 'custom') { onGuides({ aspect: event.target.value }); return; }
            const start = parseAspectRatio(customText) ? customText.trim() : '1.85:1';
            setCustomText(start);
            onGuides({ aspect: start });
          }}
        >
          <option value="">跟随成片（{plan.aspect_ratio}）</option>
          {ASPECT_PRESETS.map(value => <option key={value} value={value}>{value}</option>)}
          <option value="custom">自定义…</option>
        </select>
      </label>
      {custom && (
        <label className="desk-field is-wide">
          <span>自定义 宽:高</span>
          <input
            aria-label="自定义画幅" value={customText} placeholder="1.85:1"
            onChange={event => { setCustomText(event.target.value); if (parseAspectRatio(event.target.value)) onGuides({ aspect: event.target.value.trim() }); }}
          />
          {!parseAspectRatio(customText) && <small className="desk-field__problem">写成 宽:高，例如 1.85:1</small>}
        </label>
      )}
      <div className="desk-toggles">
        {GUIDE_TOGGLES.map(item => (
          <label key={item.key}><input type="checkbox" checked={guides[item.key]} onChange={event => onGuides({ [item.key]: event.target.checked })} /> {item.label}</label>
        ))}
      </div>

      {backdrop}

      <h3>本镜校验</h3>
      <ShotChecks plan={plan} shot={shot} />
    </section>
  );
}
