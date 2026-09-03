import { describe, expect, it } from 'vitest';

import { extractSceneDialogues, splitScriptEpisodes, type SceneDialogueLine } from './scriptOutlineUtils';

/** 回归用例只约定 kind/speaker/text 三个字段；cue 另行单测。 */
function pick(lines: SceneDialogueLine[]) {
  return lines.map(({ kind, speaker, text }) =>
    speaker === undefined ? { kind, text } : { kind, speaker, text });
}

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

describe('extractSceneDialogues regression suite (E4 + edge cases)', () => {
  it('E4S01 pure scenery/action shot yields nothing (anti-overextraction control)', () => {
    const scene = {
      scene_id: 'E4S01',
      content: '尚服局司衣库夜，暖烛摇曳。谢云谣伏在绣架前，针定住一片绛紫袖口。门外两个灰衣人低语。',
      characters: ['谢云谣'],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('E4S02 recovers action-cue speakers and the leading reported-speech sentence', () => {
    const scene = {
      scene_id: 'E4S02',
      content: '灰衣人议论太常寺有个不懂规矩的沈砚。谢云谣针尖一停：谁？灰衣人：沈砚。',
      characters: ['谢云谣', '灰衣人'],
    };
    const lines = extractSceneDialogues(scene);
    expect(pick(lines)).toEqual([
      // 首句是转述（议论=言说动词）：按「零遗漏」要求提取，句中的沈砚不在句首、不会被误判成说话人
      { kind: '台词', speaker: '灰衣人', text: '太常寺有个不懂规矩的沈砚' },
      { kind: '台词', speaker: '谢云谣', text: '谁？' },
      { kind: '台词', speaker: '灰衣人', text: '沈砚。' },
    ]);
    expect(lines[0].cue).toBe('转述'); // 间接引语必须带转述标识，不冒充逐字台词
    expect(lines[1].cue).toBe('针尖一停'); // 动作提示进 cue，不混进台词正文
  });

  it('E4S03 extracts the trailing reported answer as a marked 转述 line, never merged into the colon line', () => {
    const scene = {
      scene_id: 'E4S03',
      content: '谢云谣垂眼继续刺绣：他动了谁的棋。灰衣人答丞相。她扯断线，指尖压在针孔上渗出血珠。',
      characters: ['谢云谣', '灰衣人'],
    };
    const lines = extractSceneDialogues(scene);
    expect(pick(lines)).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '他动了谁的棋。' },
      { kind: '台词', speaker: '灰衣人', text: '丞相' },
    ]);
    expect(lines[1].cue).toBe('转述');
    // 「她扯断线…」句首非在册角色名，叙述句绝不进对话列
  });

  it('E4S04 handles a single speech-verb action cue and cuts camera directions', () => {
    const scene = {
      scene_id: 'E4S04',
      content: '谢云谣吩咐：替我查，贺兰霆为什么留他。镜头特写她冷静的面容。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '替我查，贺兰霆为什么留他。' },
    ]);
  });

  it('E4S05 pure scenery/action shot yields nothing (anti-overextraction control)', () => {
    const scene = {
      scene_id: 'E4S05',
      content: '太常寺天文台夜，沈砚半蹲在星盘前，手指按在一颗铜珠上。门被无声推开。',
      characters: ['沈砚'],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('E4S06 splits a two-part reported exchange into two marked 转述 lines', () => {
    const scene = {
      scene_id: 'E4S06',
      content: '黑衣人现身。沈砚问来取什么，黑衣人答星图。沈砚指向桌上。黑衣人探手握住竹简转身欲走。',
      characters: ['沈砚', '黑衣人'],
    };
    const lines = extractSceneDialogues(scene);
    expect(pick(lines)).toEqual([
      { kind: '台词', speaker: '沈砚', text: '来取什么' },
      { kind: '台词', speaker: '黑衣人', text: '星图' },
    ]);
    expect(lines.every(line => line.cue === '转述')).toBe(true);
    // 「现身」「指向」「探手」都不是言说动词：动作叙述句不被卷入
  });

  it('转述通道：单字动词构词与无动词叙述不误报', () => {
    const characters = ['萧遥', '沈砚'];
    // 说了算/答应了他：单字动词后首字是构词字，拒绝提取
    expect(extractSceneDialogues({ content: '萧遥说了算。', characters })).toEqual([]);
    expect(extractSceneDialogues({ content: '沈砚答应了他。', characters })).toEqual([]);
    // 句首非在册角色名：未知名字绝不走转述通道（与冒号通道的放宽不同）
    expect(extractSceneDialogues({ content: '老仆答有客到。', characters })).toEqual([]);
    // 角色名在句中不算：只认句首
    expect(extractSceneDialogues({ content: '门外有人议论沈砚说过的话。', characters })).toEqual([]);
  });

  it('转述通道：动词与名字间允许 0-4 字间隙，取词过短拒绝', () => {
    const characters = ['萧遥'];
    const lines = extractSceneDialogues({ content: '萧遥又低声问今晚谁值守。', characters });
    expect(pick(lines)).toEqual([{ kind: '台词', speaker: '萧遥', text: '今晚谁值守' }]);
    expect(lines[0].cue).toBe('转述');
    // 取词只剩 1 字：信息量不足，放弃
    expect(extractSceneDialogues({ content: '萧遥问天。', characters })).toEqual([]);
  });

  it('E4S07 keeps a multi-sentence line intact past the first full stop', () => {
    const scene = {
      scene_id: 'E4S07',
      content: '沈砚头也不抬：贺兰霆的人从不空手。你回去替我问一句——蛇要出洞了吗？',
      characters: ['沈砚', '黑衣人'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '沈砚', text: '贺兰霆的人从不空手。你回去替我问一句——蛇要出洞了吗？' },
    ]);
  });

  it('E4S08 pure action shot yields nothing (anti-overextraction control)', () => {
    const scene = {
      scene_id: 'E4S08',
      content: '沈砚慢慢站起，烛光照亮半张脸。黑衣人破窗而逃。沈砚望向窗外，眼底映出火光。',
      characters: ['沈砚'],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('EDGE01 classifies a （内心独白） parenthetical as inner monologue with a speaker', () => {
    const scene = {
      scene_id: 'EDGE01',
      content: '谢云谣（内心独白）：他究竟想做什么。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '内心独白', speaker: '谢云谣', text: '他究竟想做什么。' },
    ]);
  });

  it('EDGE02 handles a bare 内心独白： label without a speaker', () => {
    const scene = {
      scene_id: 'EDGE02',
      content: '内心独白：这局棋，从我进宫那天就开始了。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '内心独白', text: '这局棋，从我进宫那天就开始了。' },
    ]);
  });

  it('EDGE03 keeps a （内心） monologue and an adjacent spoken line by the same speaker in order', () => {
    const scene = {
      scene_id: 'EDGE03',
      content: '沈砚（内心）：不能让她知道。\n沈砚：夜深了，回吧。',
      characters: ['沈砚'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '内心独白', speaker: '沈砚', text: '不能让她知道。' },
      { kind: '台词', speaker: '沈砚', text: '夜深了，回吧。' },
    ]);
  });

  it('EDGE04 treats ownerless 画外音 and annotated 旁白 as narration', () => {
    const scene = {
      scene_id: 'EDGE04',
      content: '画外音：三年前，谢家满门抄斩，只有一人活了下来。\n旁白（低沉男声）：这一夜，注定无人安眠。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '旁白', text: '三年前，谢家满门抄斩，只有一人活了下来。' },
      { kind: '旁白', text: '这一夜，注定无人安眠。' },
    ]);
  });

  it('EDGE05 ignores slugline labels even when their values contain character names', () => {
    const scene = {
      scene_id: 'EDGE05',
      content: '时间：夜\n地点：尚服局司衣库\n人物：谢云谣、灰衣人\n谢云谣：把灯熄了。',
      characters: ['谢云谣', '灰衣人'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '把灯熄了。' },
    ]);
  });

  it('EDGE06 handles half-width colons, latin names and mixed-language lines', () => {
    const scene = {
      scene_id: 'EDGE06',
      content: 'Kevin: We had a deal.\n谢云谣（用英语）：Then sign it, Kevin.\nKevin耸耸肩: Fine.',
      characters: ['Kevin', '谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: 'Kevin', text: 'We had a deal.' },
      { kind: '台词', speaker: '谢云谣', text: 'Then sign it, Kevin.' },
      { kind: '台词', speaker: 'Kevin', text: 'Fine.' },
    ]);
  });

  it('EDGE07 anchors long interpunct names by roster prefix instead of whole-segment equality', () => {
    const scene = {
      scene_id: 'EDGE07',
      content: '阿史那·云格冷笑：草原上没有第二种规矩。\n谢云谣：那就立一种新的。',
      characters: ['阿史那·云格', '谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '阿史那·云格', text: '草原上没有第二种规矩。' },
      { kind: '台词', speaker: '谢云谣', text: '那就立一种新的。' },
    ]);
  });

  it('EDGE08 extracts alternating same-line dialogue including single-character replies', () => {
    const scene = {
      scene_id: 'EDGE08',
      content: '谢云谣：你怕吗？沈砚：怕。谢云谣：那就好。',
      characters: ['谢云谣', '沈砚'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '你怕吗？' },
      { kind: '台词', speaker: '沈砚', text: '怕。' },
      { kind: '台词', speaker: '谢云谣', text: '那就好。' },
    ]);
  });

  it('EDGE09 preserves leading ellipsis, dashes and corner quotes verbatim', () => {
    const scene = {
      scene_id: 'EDGE09',
      content: '沈砚：……你说什么？谢云谣：我说——你聋了吗？沈砚：「他不会来了。」',
      characters: ['沈砚', '谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '沈砚', text: '……你说什么？' },
      { kind: '台词', speaker: '谢云谣', text: '我说——你聋了吗？' },
      { kind: '台词', speaker: '沈砚', text: '「他不会来了。」' },
    ]);
  });

  it('EDGE10 keeps a colon inside a line from splitting or emptying it', () => {
    const scene = {
      scene_id: 'EDGE10',
      content: '沈砚：记住三个字：别回头。',
      characters: ['沈砚'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '沈砚', text: '记住三个字：别回头。' },
    ]);
  });

  it('EDGE11 allows commas inside the action cue between name and colon', () => {
    const scene = {
      scene_id: 'EDGE11',
      content: '谢云谣放下针，抬眼：说下去。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '说下去。' },
    ]);
  });

  it('EDGE12 keeps markdown stripping, parentheticals and 【 as a hard text boundary', () => {
    const scene = {
      scene_id: 'EDGE12',
      content: '**谢云谣（冷笑）：** 你也配。【转场】夜色更深。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '你也配。' },
    ]);
  });

  it('EDGE13 extracts name-like unlisted speakers while section labels stay ignored', () => {
    const scene = {
      scene_id: 'EDGE13',
      content: '高光爆点：谢云谣当众揭穿绣样。谢云谣：来人。小翠：奴婢在。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '来人。' },
      { kind: '台词', speaker: '小翠', text: '奴婢在。' },
    ]);
  });

  it('EDGE14 returns an empty list for whitespace-only content', () => {
    const scene = {
      scene_id: 'EDGE14',
      content: '   \n  ',
      characters: ['谢云谣'],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('merges known speakers passed in from the whole screenplay roster', () => {
    const scene = {
      scene_id: 'EXTRA01',
      content: '贺兰霆抱臂看着她：你倒是不怕死。',
      characters: [],
    };
    expect(pick(extractSceneDialogues(scene, ['贺兰霆', '谢云谣']))).toEqual([
      { kind: '台词', speaker: '贺兰霆', text: '你倒是不怕死。' },
    ]);
  });
});

describe('extractSceneDialogues review fixes (missed lines)', () => {
  it('FIX01 splits an unlisted 「名，动作：」 segment into speaker plus cue at the comma', () => {
    const scene = {
      scene_id: 'FIX01',
      content: '老仆，躬身：老爷回来了。',
      characters: [],
    };
    expect(extractSceneDialogues(scene)).toEqual([
      { kind: '台词', speaker: '老仆', cue: '躬身', text: '老爷回来了。' },
    ]);
  });

  it('FIX02 keeps a roster line whose long action tail ends in a speech verb', () => {
    const scene = {
      scene_id: 'FIX02',
      content: '谢云谣接过茶盏缓缓轻轻放在桌上又抬起头看着他说道：多谢。',
      characters: ['谢云谣'],
    };
    expect(extractSceneDialogues(scene)).toEqual([
      { kind: '台词', speaker: '谢云谣', cue: '接过茶盏缓缓轻轻放在桌上又抬起头看着他', text: '多谢。' },
    ]);
  });

  it('FIX03 merges a speakerless wrapped continuation line into the same utterance', () => {
    const scene = {
      scene_id: 'FIX03',
      content: '谢云谣：我说的第一句。\n这是同一段话被换行的第二句。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '我说的第一句。这是同一段话被换行的第二句。' },
    ]);
  });

  it('FIX03b still stops the merge at roster-name and camera-word lines', () => {
    const scene = {
      scene_id: 'FIX03b',
      content: '谢云谣：住手。\n谢云谣冲上前去。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '住手。' },
    ]);
    const camera = {
      scene_id: 'FIX03c',
      content: '谢云谣：住手。\n镜头拉远。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(camera))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '住手。' },
    ]);
  });

  it('FIX04 strips a bare OS suffix into an inner monologue for an unlisted speaker', () => {
    const scene = {
      scene_id: 'FIX04',
      content: '小翠OS：完了。',
      characters: [],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '内心独白', speaker: '小翠', text: '完了。' },
    ]);
  });

  it('FIX05 classifies inner-voice phrases like 脑海中响起/心中默念 as speakerless monologue', () => {
    const scene = {
      scene_id: 'FIX05',
      content: '脑海中响起：别相信他。\n心中默念：千万别露馅。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '内心独白', text: '别相信他。' },
      { kind: '内心独白', text: '千万别露馅。' },
    ]);
  });

  it('FIX06 splits space-separated alternating roster dialogue on one line', () => {
    const scene = {
      scene_id: 'FIX06',
      content: '谢云谣：好 萧策：不好',
      characters: ['谢云谣', '萧策'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '好' },
      { kind: '台词', speaker: '萧策', text: '不好' },
    ]);
  });

  it('FIX07 absorbs a time-phrase colon inside a line instead of fabricating a speaker', () => {
    const scene = {
      scene_id: 'FIX07',
      content: '萧策：听着。今晚三更：北门见。',
      characters: ['萧策'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '萧策', text: '听着。今晚三更：北门见。' },
    ]);
  });

  it('FIX08 accepts unlisted latin-initial and space-separated speaker names', () => {
    const scene = {
      scene_id: 'FIX08',
      content: 'J.K.：你好。\n林 医生：请坐。',
      characters: [],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: 'J.K.', text: '你好。' },
      { kind: '台词', speaker: '林 医生', text: '请坐。' },
    ]);
  });

  it('FIX09 reads the line-leading 「角色。台词」 notation for roster names', () => {
    const scene = {
      scene_id: 'FIX09',
      content: '谢云谣。你终于来了。',
      characters: ['谢云谣'],
    };
    expect(pick(extractSceneDialogues(scene))).toEqual([
      { kind: '台词', speaker: '谢云谣', text: '你终于来了。' },
    ]);
  });
});

describe('extractSceneDialogues review fixes (fabricated speakers)', () => {
  it('FIX10 treats 内景/外景 sluglines as labels, not speakers', () => {
    const scene = {
      scene_id: 'FIX10',
      content: '内景：书房\n外景：山路',
      characters: [],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('FIX11 treats a bare 台词 section label as a label, not a speaker', () => {
    const scene = {
      scene_id: 'FIX11',
      content: '台词：谢云谣不肯说。',
      characters: [],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('FIX12 treats production labels 道具/灯光/服装/机位 as labels, not speakers', () => {
    const scene = {
      scene_id: 'FIX12',
      content: '道具：绣绷\n灯光：昏黄\n服装：素色宫装\n机位：过肩',
      characters: [],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
  });

  it('FIX13 never promotes a narrative subject with aspect particles into a speaker', () => {
    const scene = {
      scene_id: 'FIX13',
      content: '桌上摆着三样东西：针、线、剪刀。',
      characters: [],
    };
    expect(extractSceneDialogues(scene)).toEqual([]);
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
