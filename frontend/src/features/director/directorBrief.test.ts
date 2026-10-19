import { describe, expect, it } from 'vitest';

import { findBrief, localizeIds } from './directorBrief';

const PLAN = [
  '# 《冒牌皇帝》总导演定调方案与三幕大纲',
  '**Artifact 交付**：`director_constitution` / `genre_audience_strategy` / `series_narrative_arc` / `highlight_map`',
  '---',
  '| 来源 | 内容 | 状态 |',
  '| 项目任务书 | 剧名《冒牌皇帝》、platform=douyin、language=zh-CN | 已确认 |',
  '## 二、导演宪法 `director_constitution`',
  '| 维度 | 定调 | 硬性要求 |',
  '|---|---|---|',
  '| **主题** | 假身份压不住真担当：一个靠演戏活命的人，最后演成了自己 | 每集必须有一次「演」与「真」的对照 |',
  '**主旋律 = 冒名者的每一次“装”，都被逼成真的。**',
].join('\n');

describe('director brief', () => {
  it('leads with the plan’s theme instead of the deliverables list', () => {
    const brief = findBrief(PLAN);
    expect(brief).toBe('假身份压不住真担当：一个靠演戏活命的人，最后演成了自己');
    expect(brief).not.toMatch(/[A-Za-z]{4,}/);
  });

  it('falls back to the main-theme line, then to the first Chinese prose sentence', () => {
    expect(findBrief(PLAN.replace(/\| \*\*主题\*\*.*\n/, ''))).toBe('冒名者的每一次“装”，都被逼成真的。');
    const prose = '# 方案\n**Artifact 交付**：`highlight_map`\n| a | b |\n本剧以一个乞丐被迫冒充皇帝为引子，层层揭开宫廷阴谋。';
    expect(findBrief(prose)).toBe('本剧以一个乞丐被迫冒充皇帝为引子，层层揭开宫廷阴谋。');
    expect(findBrief('# only a title\n| a | b |')).toContain('以人物欲望为引擎');
  });

  it('names deliverables in Chinese and drops ids it does not know', () => {
    expect(localizeIds('交付：`director_constitution` / `highlight_map` / `unknown_thing`')).toBe('交付：导演宪法 / 高光地图 /');
  });
});

describe('the full plan in Chinese', () => {
  it('translates deliverable ids, episode codes and common English terms', async () => {
    const { localizePlan } = await import('./directorBrief');
    const text = localizePlan([
      '**Artifact 交付**：`director_constitution` / `genre_audience_strategy` / `director_approval`',
      '## 一、输入来源、假设与 BLOCKED 清单',
      '| 项目任务书 | 剧名《冒牌皇帝》、platform=douyin、language=zh-CN、form=live_action | 已确认 |',
      '### 2.3 前 2 秒黄金 Hook（EP01 实拍指令）',
      '| 0.0-1.2s | 金銮殿 | 鼓点 | Pattern Interrupt：静得反常 |',
      'EP10、EP45 设付费墙；Want：活命 / Need：担当；BGM 降 6dB；50mm；LUT 单一',
      '变量名 some_unknown_field 保持原样',
    ].join('\n'));
    expect(text).toContain('**交付物**：导演宪法 / 题材与受众策略 / 导演审批');
    expect(text).toContain('假设与 待补 清单');
    expect(text).toContain('平台=抖音、语言=简体中文、形式=真人实拍');
    expect(text).toContain('黄金 钩子（第1集 实拍指令）');
    expect(text).toContain('打破惯性：静得反常');
    expect(text).toContain('第10集、第45集 设付费墙；外在目标：活命 / 内在需求：担当；背景音乐 降 6dB；50mm；LUT 单一');
    expect(text).toContain('some_unknown_field');
    expect(text).not.toMatch(/director_|genre_|EP\d|BLOCKED|platform=|Artifact/);
  });
});
