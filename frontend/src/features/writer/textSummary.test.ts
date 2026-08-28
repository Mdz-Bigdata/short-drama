import { describe, expect, it } from 'vitest';

import { stripMarkdown, summarizeEpisodeTitle, summarizeSceneDetail, summarizeSceneEvent } from './textSummary';

describe('stripMarkdown', () => {
  it('removes markdown control characters while keeping prose', () => {
    expect(stripMarkdown('*** ### 一、输入来源 **输入来源** - 导演策划大纲：《标题》'))
      .toBe('一、输入来源 输入来源 - 导演策划大纲：《标题》');
  });
});

describe('summarizeSceneEvent', () => {
  it('prefers the scene heading as the key-event label', () => {
    const raw = '**【场景1：建康城外乱葬岗 / 夜 / 暴雨初歇，泥水横流】** **前3秒钩子/视觉：** 一只沾满腐叶的手，猛地从乱葬坑的泥浆中伸出来。';
    expect(summarizeSceneEvent(raw)).toBe('场景1：建康城外乱葬岗');
  });

  it('falls back to the first meaningful sentence', () => {
    expect(summarizeSceneEvent('萧遥一个翻身从尸堆上滚落，用手肘砸碎脚边一块松动的腐木。乌鸦惊飞。', 20))
      .toBe('萧遥一个翻身从尸堆上滚落，用手肘砸碎脚…');
  });

  it('returns an empty label for empty content', () => {
    expect(summarizeSceneEvent('')).toBe('');
    expect(summarizeSceneEvent(undefined)).toBe('');
  });
});

describe('summarizeSceneDetail', () => {
  it('drops structural markers and clips the remaining prose', () => {
    const raw = '**【场景1：建康城外乱葬岗】** **前3秒钩子/视觉：** 一只手从泥浆中伸出来。五指抓进泥里。';
    const detail = summarizeSceneDetail(raw, 30);
    expect(detail).not.toContain('【');
    expect(detail).not.toContain('钩子');
    expect(detail).toContain('一只手从泥浆中伸出来');
  });
});

describe('summarizeEpisodeTitle', () => {
  it('drops the episode prefix and keeps the core title', () => {
    expect(summarizeEpisodeTitle('第1集 乱葬坑里有人醒')).toBe('乱葬坑里有人醒');
  });

  it('condenses a raw scene body into a short overview', () => {
    const raw = '**【场景3：建康城外竹林精舍 / 午】** 王衍盘坐于台，指尖轻点萧遥写字的破纸。';
    expect(summarizeEpisodeTitle(raw)).toBe('场景3：建康城外竹林精舍');
  });
});
