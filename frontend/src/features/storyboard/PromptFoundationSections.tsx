import { Aperture, Camera, FileText, Move3d, Palette, Route, ShieldCheck, Sparkles } from 'lucide-react';

import { PromptFields, PromptSection } from './PromptPrimitives';
import { PromptCharacters } from './PromptCharacters';
import { PromptScriptExcerpt } from './PromptScriptExcerpt';
import { GLOBAL_VISUAL_EXCLUSIONS } from './promptRules';
import { conciseNarrativeGoal } from './storyboardPromptSummary';
import type { PromptValue, StoryboardPromptDetail } from './storyboardPromptTypes';


export function PromptFoundationSections({ detail }: { detail: StoryboardPromptDetail }) {
  const foundation = detail.foundation;
  const scene = foundation.scene_and_props;
  return (
    <>
      <PromptSection title="剧本信息" icon={<FileText aria-hidden="true" />} meta={`${detail.shot_number} · ${detail.duration_seconds}s`}>
        <PromptScriptExcerpt key={`script:${detail.shot_number}`} detail={detail} />
        <PromptFields value={foundation.shot_information} className="prompt-detail__metadata" />
        <div className="prompt-detail__subgroup">
          <h3>本镜头叙事目标</h3>
          <p>{conciseNarrativeGoal(detail)}</p>
        </div>
        <PromptCharacters key={`characters:${detail.shot_number}`} characters={foundation.characters || []} />
        <div className="prompt-detail__subgroup">
          <h3>场景、道具、台词与声音</h3>
          <PromptFields value={scene} />
          {(foundation.verbatim_dialogue || []).map((line, index) => (
            <div className="prompt-detail__dialogue" key={index}>
              <span>{index + 1}</span><PromptFields value={line} />
            </div>
          ))}
        </div>
        {(foundation.timed_sounds || []).length > 0 && (
          <div className="prompt-detail__subgroup">
            <h3>时间点音效</h3>
            {(foundation.timed_sounds || []).map((cue, index) => (
              <div className="prompt-detail__dialogue" key={index}>
                <span>{index + 1}</span><PromptFields value={cue} />
              </div>
            ))}
          </div>
        )}
        <div className="prompt-detail__subgroup">
          <h3>污损时间表</h3>
          {(foundation.damage_timeline || []).length === 0
            ? <p className="prompt-detail__muted">本镜无污损变化；时间表之外禁止新增裂口、血迹或污渍。</p>
            : (foundation.damage_timeline || []).map((entry, index) => (
              <div className="prompt-detail__dialogue" key={index}>
                <span>{index + 1}</span><PromptFields value={entry} />
              </div>
            ))}
        </div>
        {foundation.extras_and_crowd && (
          <div className="prompt-detail__subgroup">
            <h3>敌人 / 群演</h3>
            <PromptFields value={foundation.extras_and_crowd} />
          </div>
        )}
      </PromptSection>

      <details className="prompt-detail__advanced">
        <summary>详细视觉、连续性与摄影参数</summary>
        <div className="prompt-detail__advanced-content">
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
        </div>
      </details>
    </>
  );
}
