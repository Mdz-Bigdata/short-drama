import { useState, type FormEvent } from 'react';
import { Dices, X } from 'lucide-react';

import { BODY_TYPES } from '../three/stageLook';

export interface CrowdRequest {
  label: string;
  rows: number;
  columns: number;
  spacing: number;
  body_type: string;
  seed: number;
}

// The server's own limits (StageCrowd): 20 × 20 at most, 150 people in one array.
const MAX_CROWD = 150;

function randomSeed() {
  return Math.floor(Math.random() * 100000);
}

export function CrowdDialog({ defaultLabel, onSubmit, onClose }: { defaultLabel: string; onSubmit: (request: CrowdRequest) => void; onClose: () => void }) {
  const [label, setLabel] = useState(defaultLabel);
  const [rows, setRows] = useState(3);
  const [columns, setColumns] = useState(4);
  const [spacing, setSpacing] = useState(1);
  const [bodyType, setBodyType] = useState('standard');
  const [seed, setSeed] = useState(randomSeed);
  const count = rows * columns;
  const valid = label.trim() !== '' && rows >= 1 && rows <= 20 && columns >= 1 && columns <= 20 && count <= MAX_CROWD && spacing >= 0.3 && spacing <= 10;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (valid) onSubmit({ label: label.trim(), rows, columns, spacing, body_type: bodyType, seed });
  };

  return (
    <div className="desk-modal__backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <form className="desk-modal" role="dialog" aria-modal="true" aria-labelledby="desk-crowd-title" onSubmit={submit}>
        <header>
          <h2 id="desk-crowd-title">添加群演阵列</h2>
          <button type="button" className="desk-icon" aria-label="关闭" onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <label className="desk-field"><span>名称</span><input value={label} maxLength={40} onChange={event => setLabel(event.target.value)} /></label>
        <div className="desk-modal__grid">
          <label className="desk-field"><span>行数</span><input type="number" min={1} max={20} value={rows} onChange={event => setRows(Math.round(Number(event.target.value)))} /></label>
          <label className="desk-field"><span>列数</span><input type="number" min={1} max={20} value={columns} onChange={event => setColumns(Math.round(Number(event.target.value)))} /></label>
          <label className="desk-field"><span>间距（米）</span><input type="number" min={0.3} max={10} step={0.1} value={spacing} onChange={event => setSpacing(Number(event.target.value))} /></label>
          <label className="desk-field">
            <span>体型</span>
            <select value={bodyType} onChange={event => setBodyType(event.target.value)}>
              {BODY_TYPES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="desk-field">
            <span>随机种子</span>
            <input type="number" min={0} max={999999} value={seed} onChange={event => setSeed(Math.round(Number(event.target.value)))} />
          </label>
          <button type="button" className="desk-button" onClick={() => setSeed(randomSeed())}><Dices aria-hidden="true" /> 换一组</button>
        </div>
        {/* The same seed always gives the same heights and offsets, so a crowd can be rebuilt exactly. */}
        <p className="desk-modal__note">共 {count} 人{count > MAX_CROWD ? `，超过上限 ${MAX_CROWD} 人` : ''}。群演按白模渲染，作为一个整体选择和移动。</p>
        <footer>
          <button type="button" className="desk-button" onClick={onClose}>取消</button>
          <button type="submit" className="desk-button is-primary" disabled={!valid}>添加</button>
        </footer>
      </form>
    </div>
  );
}
