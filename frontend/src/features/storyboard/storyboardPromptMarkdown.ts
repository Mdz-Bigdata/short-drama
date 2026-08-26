import { promptLabel } from './promptLabels';
import { FINAL_OUTPUT_CONTENTS, GLOBAL_VISUAL_EXCLUSIONS, TIME_BEAT_PLANNING_RULES } from './promptRules';
import type { PromptValue, StoryboardPromptDetail } from './storyboardPromptTypes';


function renderValue(value: PromptValue, depth = 0): string[] {
  if (value === null || value === undefined || value === '') return ['未注明'];
  if (typeof value !== 'object') return [typeof value === 'boolean' ? (value ? '是' : '否') : String(value)];
  if (Array.isArray(value)) {
    if (value.length === 0) return ['无'];
    return value.flatMap((item, index) => {
      if (typeof item !== 'object' || item === null) return [`${index + 1}. ${String(item)}`];
      return [`${index + 1}.`, ...renderValue(item, depth + 1).map(line => `   ${line}`)];
    });
  }
  return Object.entries(value).flatMap(([key, field]) => {
    if (typeof field === 'object' && field !== null) {
      return [`${'  '.repeat(depth)}- **${promptLabel(key)}：**`, ...renderValue(field, depth + 1)];
    }
    return [`${'  '.repeat(depth)}- **${promptLabel(key)}：** ${renderValue(field, depth + 1)[0]}`];
  });
}

export function storyboardPromptMarkdown(detail: StoryboardPromptDetail): string {
  const sections: Array<[string, PromptValue]> = [
    ['最终输出内容', [...FINAL_OUTPUT_CONTENTS]],
    ['镜头基础信息', detail.foundation.shot_information],
    ['剧本原文', detail.foundation.script_text],
    ['本镜头叙事目标', detail.foundation.narrative_goal],
    ['出场角色', detail.foundation.characters],
    ['场景、道具、台词与声音', { scene: detail.foundation.scene_and_props, dialogue: detail.foundation.verbatim_dialogue }],
    ['全局视觉规范', detail.foundation.global_visual_rules],
    ['通用排除项', [...GLOBAL_VISUAL_EXCLUSIONS]],
    ['连续性锁定项', detail.foundation.continuity_locks],
    ['镜头画面设计', detail.foundation.shot_visual_design],
    ['色调设计', detail.foundation.color_design],
    ['动势设计', detail.foundation.dynamics_design],
    ['运镜设计', detail.foundation.camera_design],
    ['转场设计', detail.foundation.transition_design],
    ['时间拍点规划规则', [...TIME_BEAT_PLANNING_RULES]],
    ['时间拍点', detail.beats as unknown as PromptValue],
    ['逐拍静帧提示词', detail.still_prompts as PromptValue],
    ['分段运镜视频提示词', detail.video_segments as PromptValue],
    ['宫格合成说明', detail.grid_pages as PromptValue],
    ['连续性自检结果', detail.continuity_checks as PromptValue],
  ];
  return [
    `# 通用分镜提示词 · ${detail.project_name} · ${detail.shot_number} · 第 1 页`,
    '',
    ...sections.flatMap(([title, value]) => [`## ${title}`, '', ...renderValue(value), '']),
  ].join('\n');
}
