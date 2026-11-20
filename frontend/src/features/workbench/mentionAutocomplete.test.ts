import { describe, expect, it } from 'vitest';

import { activeMentionQuery, insertMention, rankMentionCandidates, type MentionCandidate } from './mentionAutocomplete';

describe('activeMentionQuery', () => {
  it('opens right after @ and while a name is being typed', () => {
    expect(activeMentionQuery('@', 1)).toEqual({ start: 0, end: 1, query: '' });
    expect(activeMentionQuery('看@林', 3)).toEqual({ start: 1, end: 3, query: '林' });
    expect(activeMentionQuery('a @林夏 走', 5)).toEqual({ start: 2, end: 5, query: '林夏' });
  });

  it('covers the rest of the word when the caret sits inside it', () => {
    expect(activeMentionQuery('@林夏 走', 2)).toEqual({ start: 0, end: 3, query: '林' });
  });

  it('handles a half-typed @[', () => {
    expect(activeMentionQuery('镜头里@[林', 6)).toEqual({ start: 3, end: 6, query: '林' });
    expect(activeMentionQuery('@[林 夏', 5)).toEqual({ start: 0, end: 5, query: '林 夏' });
  });

  it('stays closed for emails, finished mentions and long or broken runs', () => {
    expect(activeMentionQuery('mail me at a@b', 14)).toBeNull();
    expect(activeMentionQuery('@[林夏]', 5)).toBeNull();
    expect(activeMentionQuery('@[林夏] 走', 7)).toBeNull();
    expect(activeMentionQuery('@[林夏]', 3)).toBeNull();
    expect(activeMentionQuery('@[林夏]', 2)).toBeNull();
    expect(activeMentionQuery('@[林夏]', 1)).toBeNull();
    expect(activeMentionQuery('@林夏 走', 6)).toBeNull();
    expect(activeMentionQuery('@林夏，走', 4)).toBeNull();
    expect(activeMentionQuery(`@${'x'.repeat(41)}`, 42)).toBeNull();
    expect(activeMentionQuery('@[林\n夏', 5)).toBeNull();
    expect(activeMentionQuery('没有引用', 4)).toBeNull();
  });
});

describe('insertMention', () => {
  it('writes @[name] and a following space', () => {
    expect(insertMention('看@林', { start: 1, end: 3 }, '林夏')).toEqual({ text: '看@[林夏] ', caret: 7 });
  });

  it('does not add a space before whitespace or punctuation', () => {
    expect(insertMention('@林 走', { start: 0, end: 2 }, '林夏')).toEqual({ text: '@[林夏] 走', caret: 5 });
    expect(insertMention('@林，走', { start: 0, end: 2 }, '林夏')).toEqual({ text: '@[林夏]，走', caret: 5 });
  });

  it('replaces a half-typed @[ and strips brackets from the name', () => {
    expect(insertMention('@[林', { start: 0, end: 3 }, '林[夏]').text).toBe('@[林夏] ');
  });
});

describe('rankMentionCandidates', () => {
  const items: MentionCandidate[] = [
    { name: '旧林场', kind: 'scene' },
    { name: '林家祠堂', kind: 'scene' },
    { name: '竹林剑', kind: 'prop' },
    { name: '林夏', kind: 'actor' },
    { name: '阿秋', kind: 'actor', aliases: ['林秋'] },
    { name: '林夏', kind: 'costume' },
    { name: '路人甲', kind: 'extra' },
  ];

  it('orders prefix, then substring, then alias; actors before scenes before props', () => {
    expect(rankMentionCandidates(items, '林').map(item => item.name)).toEqual(['林夏', '林家祠堂', '旧林场', '竹林剑', '阿秋']);
  });

  it('lists everything by kind when nothing is typed, and honours the limit', () => {
    expect(rankMentionCandidates(items, '').map(item => `${item.kind}:${item.name}`))
      .toEqual(['actor:林夏', 'actor:阿秋', 'scene:旧林场', 'scene:林家祠堂', 'prop:竹林剑', 'extra:路人甲']);
    expect(rankMentionCandidates(items, '', 2)).toHaveLength(2);
  });

  it('matches case-insensitively and drops misses', () => {
    expect(rankMentionCandidates([{ name: 'Neon Bar', kind: 'scene' }], 'neon')).toHaveLength(1);
    expect(rankMentionCandidates(items, '无此人')).toEqual([]);
  });
});
