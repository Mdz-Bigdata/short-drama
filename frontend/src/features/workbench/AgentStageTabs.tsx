import { ClipboardList, Film, Layers, Music, Share2, Sliders, UserCheck, Video } from 'lucide-react';

import './AgentStageTabs.css';


const AGENT_STAGES = [
  { id: 1, label: '总导演', icon: Film },
  { id: 2, label: '编剧', icon: ClipboardList },
  { id: 3, label: '角色', icon: UserCheck },
  { id: 4, label: '分镜', icon: Sliders },
  { id: 5, label: '视觉', icon: Video },
  { id: 6, label: '音频', icon: Music },
  { id: 7, label: '合成', icon: Layers },
  { id: 8, label: '宣发', icon: Share2 },
] as const;


export function AgentStageTabs({ activeStage, onChange }: {
  activeStage: number;
  onChange: (stage: number) => void;
}) {
  return (
    <nav className="agent-stage-tabs" aria-label="八种制作 Agent">
      {AGENT_STAGES.map(stage => {
        const Icon = stage.icon;
        const isActive = activeStage === stage.id;
        return (
          <button
            key={stage.id}
            type="button"
            className={`agent-stage-tab ${isActive ? 'is-active' : ''}`}
            aria-current={isActive ? 'step' : undefined}
            onClick={() => onChange(stage.id)}
          >
            <Icon aria-hidden="true" />
            {stage.id}.{stage.label}
          </button>
        );
      })}
    </nav>
  );
}
