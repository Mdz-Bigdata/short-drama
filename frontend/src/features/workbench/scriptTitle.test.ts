import { describe, expect, it } from 'vitest';

import { getScriptDisplayName, normalizeScriptTitle } from './scriptTitle';

describe('getScriptDisplayName', () => {
  it('prefers the uploaded script file name and removes its path and extension', () => {
    expect(getScriptDisplayName({
      titleSuggestion: '现代文学系博士穿越魏晋时期，以历史知识、现代思维与学识，从底层流浪乞儿成长为一代宰执。',
      scriptName: '/uploads/渡口.final.md',
    })).toBe('渡口.final');
  });

  it('falls back to the creative title when no script file name is available', () => {
    expect(getScriptDisplayName({ titleSuggestion: '大熊猫医官' })).toBe('大熊猫医官');
  });

  it('uses the generated screenplay title instead of a long creative synopsis', () => {
    expect(getScriptDisplayName({
      titleSuggestion: '现代文学系博士穿越魏晋时期，以历史知识、现代思维与学识，从底层流浪乞儿成长为一代宰执。',
    }, `
### 三、分集剧本

#### 第1集 乱葬坑里有人醒

【场景1：建康城外乱葬岗 / 夜】
    `)).toBe('乱葬坑里有人醒');
  });

  it('prefers an explicit screenplay title over the first episode title', () => {
    expect(getScriptDisplayName({ titleSuggestion: '长篇故事大纲' }, `
剧名：《雾港疑云》
第1集 雨夜来客
    `)).toBe('雾港疑云');
  });

  it('uses a stable fallback for empty task configuration', () => {
    expect(getScriptDisplayName({ titleSuggestion: '   ', scriptName: ' .md ' })).toBe('未命名剧本');
  });

  it('does not present a long story synopsis as the screenplay name', () => {
    expect(getScriptDisplayName({
      titleSuggestion: '现代文学系博士穿越魏晋时期，以历史知识、现代思维与学识，从底层流浪乞儿成长为一代宰执。',
    })).toBe('未命名剧本');
  });

  it('never shows the creation prompt as the screenplay name', () => {
    // The project is created from a chat message, so titleSuggestion is the request.
    expect(getScriptDisplayName({ titleSuggestion: '请帮我生成一个古装权谋短剧' })).toBe('未命名剧本');
    expect(getScriptDisplayName({ titleSuggestion: '帮我写一部甜宠短剧' })).toBe('未命名剧本');
    expect(getScriptDisplayName({ titleSuggestion: '我想要一个悬疑短剧' })).toBe('未命名剧本');
  });

  it('replaces the creation prompt with the analysed drama name', () => {
    expect(getScriptDisplayName(
      { titleSuggestion: '请帮我生成一个古装权谋短剧' },
      '第1集 市井无赖\n陈九：台词。',
      '流氓天子',
    )).toBe('流氓天子');
  });

  it('replaces the creation prompt with the name the screenplay opens with', () => {
    expect(getScriptDisplayName(
      { titleSuggestion: '请帮我生成一个古装权谋短剧' },
      '《流氓天子》分集剧本\n【series_bible】\n第1集 市井无赖',
    )).toBe('流氓天子');
  });

  it('prefers the series name over an episode subtitle', () => {
    // 「市井无赖」 names episode 1, not the drama.
    expect(getScriptDisplayName(
      {},
      '《流氓天子》分集剧本\n第1集 市井无赖\n陈九：台词。',
    )).toBe('流氓天子');
  });

  it('does not take a referenced guideline document as the drama name', () => {
    expect(getScriptDisplayName(
      {},
      '依据《AI漫剧短剧剧本黄金叙事结构》撰写\n《流氓天子》分集剧本\n第1集 市井',
    )).toBe('流氓天子');
  });

  it('still honours a deliberately chosen project name', () => {
    expect(getScriptDisplayName({ titleSuggestion: '乱葬坑里有人醒' })).toBe('乱葬坑里有人醒');
    expect(getScriptDisplayName({ titleSuggestion: '十二小时' })).toBe('十二小时');
  });

  it('ignores an analysed title that is itself a request', () => {
    expect(getScriptDisplayName(
      { titleSuggestion: '乱葬坑里有人醒' },
      '',
      '请帮我生成一个古装权谋短剧',
    )).toBe('乱葬坑里有人醒');
  });

  it('applies the same title-length rule to uploaded, generated, and suggested titles', () => {
    const longTitle = '这是一段超过三十二个汉字并且明显更像故事摘要而不是正式剧本名称的内容';
    expect(normalizeScriptTitle(longTitle)).toBe('');
    expect(getScriptDisplayName({
      scriptName: `/uploads/${longTitle}.md`,
      titleSuggestion: '雾港疑云',
    }, `剧名：${longTitle}`)).toBe('雾港疑云');
  });
});
