import { describe, expect, it } from 'vitest';

import { displayStep, isEditorStage, nextStageTab, previousStageTab, sameStageTab, stageLog } from './editorStage';

describe('剪辑合成师 tab', () => {
  it('treats stages 6 and 7 as one page', () => {
    expect([5, 6, 7, 8].map(isEditorStage)).toEqual([false, true, true, false]);
    expect(sameStageTab(6, 7)).toBe(true);
    expect(sameStageTab(5, 6)).toBe(false);
  });

  it('steps over the pair as one tab', () => {
    expect([previousStageTab(6), previousStageTab(7), previousStageTab(8)]).toEqual([5, 5, 7]);
    expect([nextStageTab(5), nextStageTab(6), nextStageTab(7)]).toEqual([6, 8, 8]);
  });

  it('shows the film QC once there is one, else the sound QC', () => {
    expect(stageLog({ 6: 'sound' }, 7)).toBe('sound');
    expect(stageLog({ 6: 'sound', 7: 'film' }, 6)).toBe('film');
    expect(stageLog({ 5: 'clips' }, 5)).toBe('clips');
    expect(stageLog(null, 6)).toBe('');
  });

  it('counts seven steps for people: the two editor stages are one step', () => {
    expect([1, 5, 6, 7, 8].map(displayStep)).toEqual([1, 5, 6, 6, 7]);
  });

  it('finds the films a voice change left in the old voice', async () => {
    const { filmsNeedingVoiceRender } = await import('./postProduction');
    expect(filmsNeedingVoiceRender({ episode_cycle: { episodes: { 1: { needs_render_for_voice: true }, 2: {}, 3: { needs_render_for_voice: true } } } })).toEqual([1, 3]);
    expect(filmsNeedingVoiceRender({ 7: { needs_render_for_voice: true } })).toEqual([0]);
    expect(filmsNeedingVoiceRender({ 7: { needs_render_for_voice: true, episode: 3 }, episode_cycle: { episodes: { 3: { needs_render_for_voice: true } } } })).toEqual([3]);
    expect(filmsNeedingVoiceRender(null)).toEqual([]);
  });
});
