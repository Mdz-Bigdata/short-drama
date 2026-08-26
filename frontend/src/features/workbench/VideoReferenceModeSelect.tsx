import type { VideoReferenceMode } from '../../types';

import './VideoReferenceModeSelect.css';


interface Props {
  value: VideoReferenceMode;
  onChange: (mode: VideoReferenceMode) => void;
}

const STRATEGIES = [
  {
    key: 'first-last',
    title: '首尾帧生视频',
    description: '上传首帧与尾帧，精确锁定开始、结束画面并补全中间动画。',
    models: 'Seedance 2 / 2.5 · MiniMax H3 · Kling',
  },
  {
    key: 'multi-grid',
    title: '多图 / 宫格生视频',
    description: '读取连续分镜或宫格中的多镜头叙事关系，生成连贯过渡。',
    models: 'Grok · HappyHorse · Seedance 2 / 2.5 · MiniMax H3 · Kling · LTX 2.3',
  },
  {
    key: 'multimodal',
    title: '多模态全能参考 / 角色一致性',
    description: '使用参考图片、视频或音频锁定角色、动作、风格与镜头节奏。',
    models: 'Seedance 2 / 2.5 · MiniMax H3 · Kling',
  },
] as const;


export function VideoReferenceModeSelect({ value, onChange }: Props) {
  return (
    <div className="video-reference-field">
      <label htmlFor="video-reference-mode">运镜视频参考方式</label>
      <select
        id="video-reference-mode"
        value={value}
        onChange={event => onChange(event.target.value as VideoReferenceMode)}
      >
        <option value="auto">模型自动判断（镜头意图 + 素材 + 模型能力）</option>
        <option value="first_last_frame">首尾帧生视频</option>
        <option value="multi_reference">多图 / 宫格生视频</option>
        <option value="multimodal">多模态全能参考 / 角色一致性</option>
      </select>

      <div className="video-reference-field__strategies" aria-label="支持的视频生成方式">
        {STRATEGIES.map(strategy => (
          <div className="video-reference-field__strategy" key={strategy.key}>
            <strong>{strategy.title}</strong>
            <span>{strategy.description}</span>
            <small>{strategy.models}</small>
          </div>
        ))}
      </div>

      <p className="video-reference-field__hint">
        推荐保持“模型自动判断”：系统会综合镜头意图、现有素材和所选模型能力选择生成方式，并记录选择原因与未使用素材。
      </p>
    </div>
  );
}
