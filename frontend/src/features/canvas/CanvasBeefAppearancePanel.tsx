import { useState } from 'react';
import { Palette } from 'lucide-react';

import { t } from '../../i18n';
import {
  DEFAULT_CUSTOM, normaliseHex, saveBoardAppearance, saveDefaultAppearance,
  type CanvasAppearance, type CanvasGrid, type CanvasThemeChoice,
} from './canvasBeefAppearance';
import './CanvasBeef.css';

const THEMES: Array<[CanvasThemeChoice, string]> = [['follow', '跟随全局'], ['light', '浅色'], ['dark', '深色'], ['custom', '自定义']];
const GRIDS: Array<[CanvasGrid, string]> = [['dots', '点阵'], ['lines', '线稿'], ['blank', '空白']];

function HexInput({ label, value, onValid }: { label: string; value: string; onValid: (hex: string) => void }) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  // Typing keeps its own text; a valid colour is written through at once, and a new value from outside replaces the text.
  if (value !== seen) {
    setSeen(value);
    if (normaliseHex(text) !== value) setText(value);
  }
  return (
    <label className="canvas-beef-field canvas-beef-field--inline">
      {label}
      <span className="canvas-beef-swatch" style={{ background: value }} aria-hidden="true" />
      <input value={text} maxLength={7} spellCheck={false} aria-invalid={!normaliseHex(text)}
        onChange={event => { setText(event.target.value); const hex = normaliseHex(event.target.value); if (hex) onValid(hex); }} />
    </label>
  );
}

export interface CanvasBeefAppearancePanelProps {
  canvasId: string;
  accountId: string;
  value: CanvasAppearance;
  onChange: (value: CanvasAppearance) => void;
  /** Off where the board already has its own background picker (dots / grid / blank). */
  showGrid?: boolean;
}

/** A board's theme (follow the workspace, light, dark or custom) and grid, kept for the board; any of them can be the default for new boards. */
export function CanvasBeefAppearancePanel({ canvasId, accountId, value, onChange, showGrid = true }: CanvasBeefAppearancePanelProps) {
  const [saved, setSaved] = useState(false);
  const change = (next: CanvasAppearance) => {
    setSaved(false);
    saveBoardAppearance(canvasId, next);
    onChange(next);
  };
  const custom = value.custom;
  return (
    <section className="canvas-beef-appearance" aria-label={t('画布外观')}>
      <strong><Palette size={13} aria-hidden="true" /> {t('画布外观')}</strong>
      <div role="radiogroup" aria-label={t('主题')}>
        {THEMES.map(([id, label]) => (
          <label key={id} className={value.theme === id ? 'is-chosen' : ''}>
            <input type="radio" name={`canvas-theme-${canvasId}`} checked={value.theme === id} onChange={() => change({ ...value, theme: id })} />{t(label)}
          </label>
        ))}
      </div>
      {showGrid && <div role="radiogroup" aria-label={t('网格')}>
        {GRIDS.map(([id, label]) => (
          <label key={id} className={value.grid === id ? 'is-chosen' : ''}>
            <input type="radio" name={`canvas-grid-${canvasId}`} checked={value.grid === id} onChange={() => change({ ...value, grid: id })} />{t(label)}
          </label>
        ))}
      </div>}
      {value.theme === 'custom' && (
        <div className="canvas-beef-appearance__custom">
          <HexInput label={t('背景色')} value={custom.background}
            onValid={hex => change({ ...value, custom: { ...custom, background: hex, brightness: 0 } })} />
          <label className="canvas-beef-field canvas-beef-field--inline">
            {t('明亮度')}
            <input type="range" min={-0.5} max={0.5} step={0.02} value={custom.brightness}
              onChange={event => change({ ...value, custom: { ...custom, brightness: Number(event.target.value) } })} />
          </label>
          <HexInput label={t('网格颜色')} value={custom.grid} onValid={hex => change({ ...value, custom: { ...custom, grid: hex } })} />
          <label className="canvas-beef-field canvas-beef-field--inline">
            {t('网格强度')}
            <input type="range" min={0} max={1} step={0.05} value={custom.gridStrength}
              onChange={event => change({ ...value, custom: { ...custom, gridStrength: Number(event.target.value) } })} />
          </label>
          <button type="button" onClick={() => change({ ...value, custom: DEFAULT_CUSTOM })}>{t('恢复默认颜色')}</button>
        </div>
      )}
      <button type="button" onClick={() => { saveDefaultAppearance(accountId, value); setSaved(true); }}>{t('保存为默认')}</button>
      {saved && <span role="status" className="canvas-beef-muted">{t('新建的画布会用这套外观')}</span>}
    </section>
  );
}
