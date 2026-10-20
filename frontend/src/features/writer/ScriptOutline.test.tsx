// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ScriptOutline } from './ScriptOutline';
import type { WriterScene } from './types';

const scenes: WriterScene[] = [
  {
    scene_id: 'E1S01',
    duration: '8s',
    content: '谢云谣：住手。\n旁白：夜色渐深。\n谢云谣（内心独白）：不能退。',
    characters: ['谢云谣'],
  },
];

describe('ScriptOutline dialogue tag variants', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders each dialogue kind with its own variant class', () => {
    const { container } = render(<ScriptOutline scenes={scenes} />);
    const tags = [...container.querySelectorAll('.writer-outline__tag')];
    const byKind = new Map(tags.map(tag => [tag.textContent, tag]));

    const spoken = byKind.get('台词');
    const narration = byKind.get('旁白');
    const monologue = byKind.get('内心独白');
    expect(spoken).toBeTruthy();
    expect(narration).toBeTruthy();
    expect(monologue).toBeTruthy();

    // 台词是基础样式，不带任何 is-* 变体类。
    expect(spoken!.className).toBe('writer-outline__tag');
    // 旁白 / 内心独白 各自带专属变体类，且互不串位。
    expect(narration!.classList.contains('is-narration')).toBe(true);
    expect(narration!.classList.contains('is-monologue')).toBe(false);
    expect(monologue!.classList.contains('is-monologue')).toBe(true);
    expect(monologue!.classList.contains('is-narration')).toBe(false);
  });

  it('marks a jump in scene numbering even before the server stats arrive', () => {
    // 看板首屏用 fallback 渲染时 serverStats 还没到；E15S06 直接跳到 E25S01
    // 不能就这么划过去，中间缺的集必须自己看得出来。
    const jumped: WriterScene[] = [
      { scene_id: 'E15S06', duration: '15s', content: '沈砚出手', characters: [] },
      { scene_id: 'E25S01', duration: '5s', content: '雨夜', characters: [] },
    ];
    render(<ScriptOutline scenes={jumped} />);
    const table = screen.getByRole('table');
    expect(within(table).getByText('第 16–24 集正文缺失')).toBeTruthy();
    const rows = within(table).getAllByRole('row');
    // 表头 + E15S06 + 断层行 + E25S01，断层行紧挨在跳号之前。
    expect(rows).toHaveLength(4);
    expect(rows[2].textContent).toContain('第 16–24 集正文缺失');
    expect(screen.getByText('2 条')).toBeTruthy();
  });

  it('does not repeat a gap the server already reported', () => {
    const jumped: WriterScene[] = [
      { scene_id: 'E1S01', duration: '5s', content: '开场', characters: [] },
      { scene_id: 'E3S01', duration: '5s', content: '再会', characters: [] },
    ];
    render(<ScriptOutline scenes={jumped} missingEpisodes={[2, 4]} />);
    const table = screen.getByRole('table');
    expect(within(table).getAllByText('第 2 集正文缺失')).toHaveLength(1);
    expect(within(table).getByText('第 4 集正文缺失')).toBeTruthy();
  });

  it('renders missing-only outlines without inventing scene rows', () => {
    render(<ScriptOutline scenes={[]} missingEpisodes={[1, 2, 4]} />);
    const table = screen.getByRole('table');
    expect(within(table).getByText('第 1–2 集正文缺失')).toBeTruthy();
    expect(within(table).getByText('第 4 集正文缺失')).toBeTruthy();
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('0 条')).toBeTruthy();
  });
});
