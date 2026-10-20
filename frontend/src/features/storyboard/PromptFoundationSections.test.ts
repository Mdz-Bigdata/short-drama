import { describe, expect, it } from 'vitest';

import { conciseNarrativeGoal, scriptReadingView } from './storyboardPromptSummary';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';


function detailWith(goal: string, events: string[]) {
  return {
    foundation: { narrative_goal: goal },
    beats: events.map((core_event, index) => ({ index: index + 1, core_event })),
  } as StoryboardPromptDetail;
}

describe('conciseNarrativeGoal', () => {
  it('replaces legacy slot labels with a meaningful first-middle-last story chain', () => {
    const detail = detailWith(
      Array.from({ length: 9 }, (_, index) => `第${index + 1}个因果/情绪信息单元`).join('；'),
      Array.from({ length: 9 }, (_, index) => `动作${index + 1}`),
    );

    expect(conciseNarrativeGoal(detail)).toBe('动作1 → 动作5 → 动作9');
  });

  it('keeps an authored narrative goal unchanged', () => {
    const detail = detailWith('沈砚发现血痕并确认仇人身份', ['沈砚低头', '沈砚抬眼']);

    expect(conciseNarrativeGoal(detail)).toBe('沈砚发现血痕并确认仇人身份');
  });
});

describe('scriptReadingView', () => {
  const readingDetail = (script_text: string, shot_number = 'E1S01') => ({
    ...detailWith('', []),
    episode: '第1集',
    shot_number,
    scene_number: 1,
    foundation: { script_text },
  }) as StoryboardPromptDetail;

  it('extracts the current scene from a flattened multi-episode source without deleting the source', () => {
    const source = '第1集 血碑 场景1：天文台 沈砚跪在石阶，划出三道血痕。 场景2：宫门 贺兰霆走远。 第2集 朝会 场景1：大殿 皇帝现身。';
    const view = scriptReadingView(readingDetail(source));

    expect(view.scope).toBe('scene');
    expect(view.excerpt).toContain('划出三道血痕');
    expect(view.excerpt).not.toContain('贺兰霆走远');
    expect(view.excerpt).not.toContain('皇帝现身');
    expect(view.source).toBe(source);
    expect(view.expandable).toBe(true);
  });

  it('uses an explicit current shot identifier before screenplay scene numbering', () => {
    const view = scriptReadingView(readingDetail('E1S01 石阶血痕。 E1S02 黑靴入画。 E2S01 皇帝现身。', 'E1S02'));

    expect(view.excerpt).toContain('黑靴入画');
    expect(view.excerpt).not.toContain('石阶血痕');
    expect(view.excerpt).not.toContain('皇帝现身');
  });

  it('labels episode-only material honestly when the requested shot cannot be located', () => {
    const view = scriptReadingView(readingDetail('第1集 血碑 场景1：石阶血痕。 第2集 朝会 场景1：皇帝现身。', 'E1S08'));

    expect(view.scope).toBe('episode');
    expect(view.excerpt).not.toContain('皇帝现身');
    expect(view.label).toContain('本集原文参考');
  });

  it('does not mistake the second outline shot for the second screenplay scene', () => {
    const view = scriptReadingView(readingDetail('第1集 血碑 场景1：石阶血痕。 场景2：宫门送别。 第2集 朝会 场景1：皇帝现身。', 'E1S02'));

    expect(view.scope).toBe('episode');
    expect(view.excerpt).toContain('石阶血痕');
    expect(view.excerpt).not.toContain('皇帝现身');
    expect(view.label).toContain('未定位到独立镜头段落');
  });

  it('does not mislabel another episode as the current scene', () => {
    const view = scriptReadingView(readingDetail('第十二集 朝会 场景1：皇帝现身。'));

    expect(view.scope).toBe('source');
    expect(view.label).toContain('剧本原文预览');
  });

  it('keeps short already scene-bound text compact and creates readable paragraphs for flattened text', () => {
    const short = scriptReadingView(readingDetail('沈砚跪在石阶上。'));
    expect(short.excerpt).toBe('沈砚跪在石阶上。');
    expect(short.expandable).toBe(false);

    const long = scriptReadingView(readingDetail('石阶上的血痕逐渐洇开。'.repeat(100)));
    expect(long.excerptParagraphs.length).toBeGreaterThan(1);
    expect(long.excerptParagraphs.join('')).toBe(long.source);
    expect(long.expandable).toBe(true);
  });
});
