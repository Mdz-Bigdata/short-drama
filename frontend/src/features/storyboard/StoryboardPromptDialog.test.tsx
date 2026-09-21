// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardPromptDialog } from './StoryboardPromptDialog';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';


const detail: StoryboardPromptDetail = {
  project_name: '测试项目',
  episode: '第1集',
  scene_number: 1,
  shot_number: 'E1S01',
  duration_seconds: 3,
  aspect_ratio: '9:16',
  fps: 24,
  grid_spec: '3x3',
  foundation: {
    script_text: '完整剧本文本',
    narrative_goal: '主角发现线索',
  },
  beats: [],
  still_prompts: [],
  video_segments: [],
  grid_pages: [],
  continuity_checks: [{ code: 'camera_axis', passed: false, detail: '摄影机轴线发生跳变' }],
  submission_ready: false,
  warnings: ['请先修正轴线再提交'],
};

describe('StoryboardPromptDialog', () => {
  afterEach(cleanup);

  it('uses separate sibling keys for the current script and character sections', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      render(<StoryboardPromptDialog detail={detail} onClose={vi.fn()} />);
      expect(errors).not.toHaveBeenCalled();
    } finally {
      errors.mockRestore();
    }
  });

  it('lets keyboard users reach the collapsed detail controls from the close button', async () => {
    const user = userEvent.setup();
    render(<StoryboardPromptDialog detail={detail} onClose={vi.fn()} />);

    expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭宫格提示词' }));

    await user.tab();
    expect(document.activeElement).toBe(screen.getByText('详细视觉、连续性与摄影参数').closest('summary'));

    await user.tab();
    expect(document.activeElement).toBe(screen.getByText('拍点规划与宫格合成').closest('summary'));
  });

  it('keeps continuity failures available in a concise collapsed summary', () => {
    render(<StoryboardPromptDialog detail={detail} onClose={vi.fn()} />);

    const summary = screen.getByText('连续性检查 · 需修正').closest('summary');
    expect(summary?.parentElement?.getAttribute('open')).toBeNull();
    expect(screen.getByText('摄影机轴线发生跳变')).toBeTruthy();
    expect(screen.getByText('请先修正轴线再提交')).toBeTruthy();
  });

  it('shows non-blocking warnings once without marking the prompt as needing correction', () => {
    const warning = '单拍点无需生成连接视频';
    render(
      <StoryboardPromptDialog
        detail={{
          ...detail,
          continuity_checks: [{ code: 'single_beat_no_connector', passed: false, severity: 'warning', detail: warning }],
          submission_ready: true,
          warnings: [warning],
        }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('连续性检查 · 通过（有提示）')).toBeTruthy();
    expect(screen.getAllByText(warning)).toHaveLength(1);
  });

  it('escapes a clipped workbench through a portal and restores focus and scrolling after close', async () => {
    const user = userEvent.setup();
    const trigger = document.createElement('button');
    trigger.textContent = '查看提示词';
    document.body.append(trigger);
    trigger.focus();
    const onClose = vi.fn();
    const { container, unmount } = render(
      <div style={{ transform: 'translateZ(0)', overflow: 'hidden' }}>
        <StoryboardPromptDialog detail={detail} onClose={onClose} />
      </div>,
    );

    const dialog = screen.getByRole('dialog', { name: 'E1S01 · 宫格提示词' });
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement?.parentElement).toBe(document.body);
    expect(document.body.style.overflow).toBe('hidden');

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe('');
    trigger.remove();
  });

  it('wraps keyboard focus between visible controls without entering closed sections', async () => {
    const user = userEvent.setup();
    render(<StoryboardPromptDialog detail={detail} onClose={vi.fn()} />);
    const download = screen.getByRole('link', { name: '下载 Markdown' });
    download.focus();
    await user.tab({ shift: true });
    const lastSummary = screen.getByText('连续性检查 · 需修正').closest('summary');
    expect(document.activeElement).toBe(lastSummary);
    await user.tab();
    expect(document.activeElement).toBe(download);
  });
});
