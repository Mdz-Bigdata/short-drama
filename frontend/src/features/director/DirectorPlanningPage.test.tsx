// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { DirectorPlanningPage } from './DirectorPlanningPage';

describe('DirectorPlanningPage', () => {
  afterEach(cleanup);

  it('turns the stage asset into a director-focused planning board', () => {
    render(
      <DirectorPlanningPage
        title="雾港追凶"
        directorStyle="cyberpunk"
        shotStyle="cinematic"
        asset={'总导演策划\n本片以失踪案为引线，通过强冲突与连续反转，让主角在十二小时内完成自我救赎。'}
      />,
    );

    expect(screen.getByRole('heading', { name: '总导演策划' })).toBeTruthy();
    expect(screen.getByText('《雾港追凶》')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '创作罗盘' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '情绪节奏曲线' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '视听基调' })).toBeTruthy();
    expect(screen.getAllByText('赛博霓虹')).toHaveLength(2);
    expect(screen.getByAltText('导演在片场监看拍摄画面')).toBeTruthy();
    expect(screen.getAllByText(/本片以失踪案为引线/).length).toBeGreaterThanOrEqual(2);
  });

  it('uses a responsive title lockup without a forced line break', () => {
    render(<DirectorPlanningPage title="雾港追凶" asset="导演执行方案" />);

    const heading = screen.getByRole('heading', { name: '总导演策划' });
    expect(heading.classList.contains('director-hero__title')).toBe(true);
    expect(heading.querySelector('br')).toBeNull();
    expect(heading.querySelectorAll('span')).toHaveLength(2);
  });
});
