import { describe, expect, it } from 'vitest';

import { storyboardPromptMarkdown } from './storyboardPromptMarkdown';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';


function detail(extra: Partial<StoryboardPromptDetail['foundation']> = {}) {
  return {
    project_name: '天牢月光',
    episode: '第1集',
    scene_number: 1,
    shot_number: 'E1S01',
    duration_seconds: 6,
    aspect_ratio: '9:16',
    fps: 24,
    grid_spec: '3x3',
    foundation: {
      narrative_goal: '沈砚抬头望月',
      timed_sounds: [{ start_seconds: 0, end_seconds: 4, description: '铁链轻响' }],
      damage_timeline: [{ seconds: 2, subject: '沈砚', change: '泥点沾上袖口' }],
      ...extra,
    },
    beats: [{ index: 1, core_event: '沈砚抬头望月' }],
    still_prompts: [],
    video_segments: [],
    grid_pages: [],
    continuity_checks: [],
  } as unknown as StoryboardPromptDetail;
}


describe('storyboardPromptMarkdown', () => {
  it('exports sound cues and the damage table with readable labels', () => {
    const markdown = storyboardPromptMarkdown(detail());

    expect(markdown).toContain('## 时间点音效');
    expect(markdown).toContain('**描述：** 铁链轻响');
    expect(markdown).toContain('## 污损时间表');
    expect(markdown).toContain('**变化：** 泥点沾上袖口');
    expect(markdown).not.toContain('## 敌人 / 群演');
  });

  it('only adds the crowd section when the shot has extras', () => {
    const markdown = storyboardPromptMarkdown(detail({
      extras_and_crowd: { label: '狱卒们', initial_distribution: '走廊尽头', motion_parameters: '列队走来', stagger_seconds: 0.3 },
    }));

    expect(markdown).toContain('## 敌人 / 群演');
    expect(markdown).toContain('**群体名称：** 狱卒们');
    expect(markdown).toContain('**个体错开秒数：** 0.3');
  });
});
