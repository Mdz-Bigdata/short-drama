// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ShotAssetChips } from './ShotAssetChips';

function chipNames(container: HTMLElement): string[] {
  return [...container.querySelectorAll('.shot-assets__name')].map(node => node.textContent || '');
}

describe('ShotAssetChips', () => {
  afterEach(cleanup);

  it('merges every input into one list without repeats, grouped 人物/场景/道具/特效/其他', () => {
    const { container } = render(
      <ShotAssetChips
        assets={[
          { kind: 'effect', name: '血雾', image_number: null, in_storyboard: true, in_video: true, stale: false },
          { kind: 'prop', name: '青铜剑', image_number: 3, in_storyboard: true, in_video: true, stale: false },
          { kind: 'actor', name: '沈砚', image_number: 1, in_storyboard: true, in_video: true, stale: false },
          { kind: 'vehicle', name: '马车', image_number: null, in_storyboard: true, in_video: true, stale: false },
          { kind: 'scene', name: '太常寺', image_number: 2, in_storyboard: true, in_video: true, stale: false },
          { kind: 'flag', name: '旗子', image_number: null, in_storyboard: true, in_video: true, stale: false },
        ]}
        characters={['沈砚', '贺兰霆']}
        props={['青铜剑']}
      />,
    );
    expect(chipNames(container)).toEqual(['沈砚', '贺兰霆', '太常寺', '青铜剑', '马车', '血雾', '旗子']);
    const groupLabels = [...container.querySelectorAll('.shot-assets__group-label')].map(node => node.textContent);
    expect(groupLabels).toEqual(['人物', '场景', '道具', '特效', '其他']);
    expect(screen.getByRole('group', { name: '本镜用到的资产' })).toBeTruthy();
  });

  it('uses the legacy kinds and reference numbers only when there are no assets', () => {
    const { container, rerender } = render(
      <ShotAssetChips kinds={{ 沈砚: 'actor', 青铜剑: 'prop' }} referenceNumbers={{ 沈砚: 1, 青铜剑: 2 }} />,
    );
    expect(chipNames(container)).toEqual(['沈砚', '青铜剑']);
    expect(screen.getByText('图1')).toBeTruthy();
    expect(screen.getByText('图2')).toBeTruthy();
    expect(screen.getByText('沈砚').closest('.shot-assets__chip')?.getAttribute('title')).toContain('数字演员');

    rerender(<ShotAssetChips assets={[{ kind: 'scene', name: '乱葬坑' }]} kinds={{ 沈砚: 'actor' }} />);
    expect(chipNames(container)).toEqual(['乱葬坑']);
  });

  it('marks an asset used only in the video or only in the storyboard, and warns when it changed', () => {
    render(
      <ShotAssetChips
        assets={[
          { kind: 'actor', name: '沈砚', in_storyboard: false, in_video: true },
          { kind: 'prop', name: '青铜剑', in_storyboard: true, in_video: false, stale: true },
          { kind: 'scene', name: '太常寺', in_storyboard: true, in_video: true },
        ]}
      />,
    );
    expect(within(screen.getByText('沈砚').closest('.shot-assets__chip') as HTMLElement).getByText('视频')).toBeTruthy();
    const sword = screen.getByText('青铜剑').closest('.shot-assets__chip') as HTMLElement;
    expect(within(sword).getByText('分镜')).toBeTruthy();
    expect(sword.className).toContain('is-stale');
    expect(sword.getAttribute('title')).toContain('资产已改，需重画或重跑');
    const hall = screen.getByText('太常寺').closest('.shot-assets__chip') as HTMLElement;
    expect(hall.querySelector('.shot-assets__marker')).toBeNull();
    expect(hall.className).not.toContain('is-stale');
  });

  it('shows four chips and +N in compact mode, and a shot-wide stale badge', () => {
    const { container } = render(
      <ShotAssetChips compact stale characters={['甲', '乙', '丙']} props={['剑', '灯']} effects={['雾']} />,
    );
    expect(chipNames(container)).toEqual(['甲', '乙', '丙', '剑']);
    const more = screen.getByText('+2');
    expect(more.getAttribute('title')).toBe('灯、雾');
    expect(screen.getByText('资产已改').getAttribute('title')).toBe('资产已改，需重画或重跑');
    expect(container.querySelector('.shot-assets__group-label')).toBeNull();
  });

  it('renders no buttons or links and nothing at all when there is nothing to show', () => {
    const { container, unmount } = render(
      <ShotAssetChips assets={[{ kind: 'actor', name: '沈砚', image_number: 1 }]} scene="太常寺" />,
    );
    expect(container.querySelectorAll('button, a, [role="button"]')).toHaveLength(0);
    unmount();
    const empty = render(<ShotAssetChips assets={[]} characters={[]} />);
    expect(empty.container.innerHTML).toBe('');
  });

  it('drops storyboard placeholders such as 本格无额外道具', () => {
    render(<ShotAssetChips characters={['林夏']} props={['本格无额外道具']} effects={['本格无额外特效']} scene="办公室" />);
    expect(screen.getByText('林夏')).toBeTruthy();
    expect(screen.queryByText('本格无额外道具')).toBeNull();
    expect(screen.queryByText('本格无额外特效')).toBeNull();
  });
});
