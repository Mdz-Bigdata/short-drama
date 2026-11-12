import { useEffect, useRef } from 'react';
import { Clapperboard, ClipboardList, Film, Share2, Sliders, UserCheck, Video } from 'lucide-react';

import './AgentStageTabs.css';
import { t } from '../../i18n';


// 第 6、7 步(声音、成片)是同一个角色「剪辑合成师」，合成一个页签；页签按用户看到的七个角色连续编号(6.剪辑合成师、7.宣发)，id 和 stages 仍是后端的八步。
const AGENT_STAGES: ReadonlyArray<{ id: number; stages: readonly number[]; number: string; label: string; icon: typeof Film }> = [
  { id: 1, stages: [1], number: '1', label: '总导演', icon: Film },
  { id: 2, stages: [2], number: '2', label: '编剧', icon: ClipboardList },
  { id: 3, stages: [3], number: '3', label: '角色', icon: UserCheck },
  { id: 4, stages: [4], number: '4', label: '分镜', icon: Sliders },
  { id: 5, stages: [5], number: '5', label: '视觉', icon: Video },
  { id: 6, stages: [6, 7], number: '6', label: '剪辑合成师', icon: Clapperboard },
  { id: 8, stages: [8], number: '7', label: '宣发', icon: Share2 },
];

// 露出当前页签时多滚一点，让相邻页签探出半个头，看得出那边还有。
const REVEAL_MARGIN_PX = 24;

/** How far the strip must scroll sideways so the tab is fully visible; 0 when it already is. */
function scrollDeltaToReveal(
  strip: { left: number; right: number },
  tab: { left: number; right: number },
): number {
  if (tab.left < strip.left) return tab.left - strip.left - REVEAL_MARGIN_PX;
  if (tab.right > strip.right) return tab.right - strip.right + REVEAL_MARGIN_PX;
  return 0;
}


export function AgentStageTabs({ activeStage, onChange }: {
  activeStage: number;
  onChange: (stage: number) => void;
}) {
  const stripRef = useRef<HTMLElement>(null);

  // 阶段会被流水线自动推进，当前页签可能落在滚出去的那一截。只滚页签条自己：
  // scrollIntoView 会连带滚动外层看板，把正在往下看的人拽回页顶。
  useEffect(() => {
    const strip = stripRef.current;
    const tab = strip?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!strip || !tab) return;
    const delta = scrollDeltaToReveal(strip.getBoundingClientRect(), tab.getBoundingClientRect());
    if (delta !== 0) strip.scrollLeft += delta;
  }, [activeStage]);

  return (
    <nav ref={stripRef} className="agent-stage-tabs" aria-label={t('制作 Agent')}>
      {AGENT_STAGES.map(stage => {
        const Icon = stage.icon;
        const isActive = stage.stages.includes(activeStage);
        return (
          <button
            key={stage.id}
            type="button"
            className={`agent-stage-tab ${isActive ? 'is-active' : ''}`}
            aria-current={isActive ? 'step' : undefined}
            onClick={() => onChange(stage.id)}
          >
            <Icon aria-hidden="true" />
            {stage.number}.{t(stage.label)}
          </button>
        );
      })}
    </nav>
  );
}
