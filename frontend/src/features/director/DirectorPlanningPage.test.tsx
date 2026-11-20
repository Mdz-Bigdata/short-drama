// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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

  it('shows the plan the model wrote in full right under the hero, ahead of the general guidance', () => {
    const { container } = render(
      <DirectorPlanningPage title="雾港追凶" asset={'## 核心主题\n真相比凶手更难面对。\n\n- 每集结尾留一个钩子'} />,
    );

    const plan = container.querySelector('.plan-markdown') as HTMLElement;
    expect(plan.closest('details')).toBeNull();
    expect(screen.getByRole('heading', { name: '核心主题' })).toBeTruthy();
    expect(screen.getByText('每集结尾留一个钩子')).toBeTruthy();

    const general = screen.getByText('通用导演准则');
    const compass = screen.getByRole('heading', { name: '创作罗盘' });
    expect(plan.compareDocumentPosition(general) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(general.compareDocumentPosition(compass) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText(/均以总导演 Agent 的原始策划为准/)).toBeNull();
  });

  it('marks a plan that is still on its way as waiting, not as done', () => {
    const { container } = render(<DirectorPlanningPage title="雾港追凶" />);

    const status = screen.getByText('等待策划生成');
    expect(status.classList.contains('is-waiting')).toBe(true);
    expect(status.querySelector('.lucide-check')).toBeNull();
    expect(screen.getByText('策划生成后，完整导演手记将在这里自动归档。')).toBeTruthy();
    expect(container.querySelector('.plan-markdown')).toBeNull();
  });

  it('keeps the hero copy and drops the photo frame when the set photo cannot load', () => {
    const { container } = render(<DirectorPlanningPage title="雾港追凶" asset="导演执行方案" />);

    fireEvent.error(screen.getByAltText('导演在片场监看拍摄画面'));

    expect(container.querySelector('.director-hero__visual')).toBeNull();
    expect(container.querySelector('.director-hero')?.classList.contains('is-plain')).toBe(true);
    expect(screen.getByRole('heading', { name: '总导演策划' })).toBeTruthy();
  });
});
