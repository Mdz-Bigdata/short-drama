import { Aperture, Camera, FileText, Move3d, Palette, Route, ShieldCheck, Sparkles } from 'lucide-react';

import { PromptFields, PromptSection } from './PromptPrimitives';
import { GLOBAL_VISUAL_EXCLUSIONS } from './promptRules';
import type { PromptValue, StoryboardPromptDetail } from './storyboardPromptTypes';


export function PromptFoundationSections({ detail }: { detail: StoryboardPromptDetail }) {
  const foundation = detail.foundation;
  const scene = foundation.scene_and_props;
  return (
    <>
      <PromptSection title="剧本信息" icon={<FileText aria-hidden="true" />} meta={`${detail.shot_number} · ${detail.duration_seconds}s`}>
        <blockquote className="prompt-detail__script">{foundation.script_text || '未提供剧本原文'}</blockquote>
        <PromptFields value={foundation.shot_information} />
        <div className="prompt-detail__subgroup">
          <h3>本镜头叙事目标</h3>
          <p>{foundation.narrative_goal || '未注明'}</p>
        </div>
        <div className="prompt-detail__subgroup">
          <h3>出场角色</h3>
          <div className="prompt-detail__card-grid">
            {(foundation.characters || []).map((character, index) => <PromptFields key={index} value={character} />)}
          </div>
        </div>
        <div className="prompt-detail__subgroup">
          <h3>场景、道具、台词与声音</h3>
          <PromptFields value={scene} />
          {(foundation.verbatim_dialogue || []).map((line, index) => (
            <div className="prompt-detail__dialogue" key={index}>
              <span>{index + 1}</span><PromptFields value={line} />
            </div>
          ))}
        </div>
      </PromptSection>

      <PromptSection title="全局视觉规范" icon={<Sparkles aria-hidden="true" />}>
        <PromptFields value={foundation.global_visual_rules} />
        <div className="prompt-detail__subgroup">
          <h3>通用排除项</h3>
          <div className="prompt-detail__rules">
            {GLOBAL_VISUAL_EXCLUSIONS.map(rule => <p key={rule}>{rule}</p>)}
          </div>
        </div>
      </PromptSection>
      <PromptSection title="连续性锁定项" icon={<ShieldCheck aria-hidden="true" />}>
        <PromptFields value={foundation.continuity_locks} />
        <div className="prompt-detail__rules">
          {['物体状态承接上一拍', '人物位移符合真实距离和速度', '不得无过程换手、转向、换脚或改变站位', '光源方向不得无原因跳变', '不得跨越既定摄影机轴线', '后一拍从前一拍结束状态自然开始'].map(rule => <p key={rule}>{rule}</p>)}
        </div>
      </PromptSection>
      <PromptSection title="画面设计" icon={<Aperture aria-hidden="true" />}>
        <PromptFields value={foundation.shot_visual_design} />
      </PromptSection>
      <PromptSection title="色调设计" icon={<Palette aria-hidden="true" />}>
        <PromptFields value={foundation.color_design} />
      </PromptSection>
      <PromptSection title="动势设计" icon={<Move3d aria-hidden="true" />}>
        <PromptFields value={foundation.dynamics_design} />
      </PromptSection>
      <PromptSection title="运镜设计" icon={<Camera aria-hidden="true" />}>
        <PromptFields value={foundation.camera_design} />
      </PromptSection>
      <PromptSection title="转场设计" icon={<Route aria-hidden="true" />}>
        <PromptFields value={foundation.transition_design as Record<string, PromptValue>} />
      </PromptSection>
    </>
  );
}
