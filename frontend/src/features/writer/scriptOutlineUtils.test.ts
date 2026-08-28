import { describe, expect, it } from 'vitest';

import { extractSceneDialogues, splitScriptEpisodes } from './scriptOutlineUtils';

describe('extractSceneDialogues', () => {
  it('recovers speaker lines and narration from a flattened scene body', () => {
    const scene = {
      scene_id: 'E1S01',
      content: '前3秒钩子/视觉： 一只手从泥浆中伸出。 对白： 萧遥：这里不是长江。 '
        + '流民甲（画外，远处声若洪钟）：那姓萧的没死！ 旁白：钟响三遍，百鬼赴宴。 '
        + '动作： 萧遥摸向自己后脑。 萧遥：要死，一起。',
      characters: ['萧遥', '流民甲'],
    };
    const lines = extractSceneDialogues(scene);
    expect(lines).toEqual([
      { kind: '台词', speaker: '萧遥', text: '这里不是长江。' },
      { kind: '台词', speaker: '流民甲', text: '那姓萧的没死！' },
      { kind: '旁白', text: '钟响三遍，百鬼赴宴。' },
      { kind: '台词', speaker: '萧遥', text: '要死，一起。' },
    ]);
  });

  it('ignores section labels that are not known characters', () => {
    const scene = {
      scene_id: 'E1S02',
      content: '冲突升级： 火把围拢。 高光爆点： 独眼流民冲进来。',
      characters: ['萧遥'],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('strips markdown emphasis markers before matching speakers', () => {
    const scene = {
      scene_id: 'E1S03',
      content: '**萧遥（停顿后）：** 你的侍从太差了。',
      characters: ['萧遥'],
    };
    expect(extractSceneDialogues(scene)).toEqual([
      { kind: '台词', speaker: '萧遥', text: '你的侍从太差了。' },
    ]);
  });

  it('returns nothing for an empty scene', () => {
    expect(extractSceneDialogues({ scene_id: 'E1S04' })).toEqual([]);
  });
});

describe('splitScriptEpisodes', () => {
  it('splits a screenplay into per-episode plain text chunks', () => {
    const script = [
      '### 三、分集剧本',
      '',
      '#### 第1集 乱葬坑里有人醒',
      '',
      '**【场景1：建康城外乱葬岗】**',
      '萧遥：这里不是长江。',
      '',
      '#### 第2集 我教贵人写个字',
      '',
      '牛车前，一个仆役正用鞭子抽打一个倒地老人。',
      '',
      '#### 第十二集 大结局',
      '尾声。',
    ].join('\n');
    const episodes = splitScriptEpisodes(script);
    expect(episodes.map(episode => episode.number)).toEqual([1, 2, 12]);
    expect(episodes[0].title).toBe('乱葬坑里有人醒');
    expect(episodes[0].text).toContain('萧遥：这里不是长江。');
    expect(episodes[0].text).not.toContain('牛车前');
    expect(episodes[1].text).toContain('牛车前');
    expect(episodes[2].title).toBe('大结局');
  });

  it('keeps the fullest chunk when an episode heading repeats in a synopsis', () => {
    const script = [
      '第1集 目录占位',
      '#### 第1集 正式内容',
      '完整的第一集正文，比目录行长得多，因此应当被保留下来。',
    ].join('\n');
    const episodes = splitScriptEpisodes(script);
    expect(episodes).toHaveLength(1);
    expect(episodes[0].text).toContain('完整的第一集正文');
  });

  it('falls back to a single full-script chunk when no episode headings exist', () => {
    const episodes = splitScriptEpisodes('没有分集标题的剧本正文。');
    expect(episodes).toEqual([
      { number: 1, title: '完整剧本', text: '没有分集标题的剧本正文。' },
    ]);
  });

  it('returns an empty list for a blank script', () => {
    expect(splitScriptEpisodes('')).toEqual([]);
  });
});
