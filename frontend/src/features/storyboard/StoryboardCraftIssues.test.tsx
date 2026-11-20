// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';

const shots: StoryboardShot[] = [{ shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/shot-1.png', size: 'MS', motion: 'Static' }];

function show(craft_issues?: string[]) {
  return render(
    <StoryboardWorkspace title="雪夜" shots={shots} breakdownScenes={[{ scene_id: 'E1S01' }]}
      sceneBoards={{ E1S01: { status: 'done', craft_issues } }} onRefresh={vi.fn()} onRegenerate={vi.fn()} />,
  );
}

describe('storyboard craft review', () => {
  afterEach(cleanup);

  it('lists what still fails after the automatic revision', () => {
    show(['镜2 多人排排站：沈砚、苏晚、李三 都在中景', '镜3 招式没写清：U2 缺：打在谁身上哪里']);
    expect(screen.getByText('分镜复核还有 2 条没过（已自动改过一版）')).toBeTruthy();
    expect(screen.getByText(/镜2 多人排排站/)).toBeTruthy();
    expect(screen.getByText(/重画这一场/)).toBeTruthy();
  });

  it('says nothing when the scene passed', () => {
    show([]);
    expect(screen.queryByText(/分镜复核还有/)).toBeNull();
    cleanup();
    show(undefined);
    expect(screen.queryByText(/分镜复核还有/)).toBeNull();
  });
});
