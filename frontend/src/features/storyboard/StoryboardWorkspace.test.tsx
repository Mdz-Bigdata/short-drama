// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';
import { storyboardPromptMarkdown } from './storyboardPromptMarkdown';


const shots: StoryboardShot[] = Array.from({ length: 9 }, (_, index) => ({
  shot_id: index + 1,
  image_url: `https://example.com/shot-${index + 1}.png`,
  size: index === 0 ? '全景' : '近景',
  motion: index === 0 ? '固定' : '缓慢推镜',
  desc: `连续动作 ${index + 1}`,
  scene_id: 'E1S01',
  scene: '北京西站广场',
}));

const promptDetail = {
  project_name: '初到北京被骗',
  episode: '第1集',
  scene_number: 1,
  shot_number: 'E1S01',
  duration_seconds: 8,
  aspect_ratio: '9:16',
  fps: 24,
  grid_spec: '3x3',
  foundation: {
    shot_information: { project_name: '初到北京被骗', episode: '第1集', shot_number: 'E1S01', duration_seconds: 8, aspect_ratio: '9:16', fps: 24, grid_spec: '3x3' },
    narrative_goal: '观众理解角色第一次来到北京。',
    script_text: '林夏抬头望向北京西站。',
    characters: [{ name: '林夏', identity: '初到北京的年轻女孩', appearance: '黑色马尾', costume: '蓝色牛仔外套', accessories: '灰色双肩包', physical_state: '旅途疲惫', psychological_state: '期待又警惕' }],
    scene_and_props: { time: '傍晚', location: '北京西站广场', weather: '晴', spatial_structure: '站房位于北侧，出站口位于东侧', props: [{ name: '编织袋', initial_state: '由林夏右手提着', initial_position: '身体右侧', allowed_motion: '随步伐自然摆动' }], environmental_sound: '人群脚步与广播声' },
    verbatim_dialogue: [{ kind: 'narration', speaker: '旁白', exact_text: '她终于来到北京。', start_seconds: 0, end_seconds: 2 }],
    global_visual_rules: { visual_style: '真人电视剧风格', era_and_region: '当代北京', art_direction: '写实站前广场', rendering_texture: '电影摄影质感', authenticity: '原创虚拟角色', overall_atmosphere: '期待', exclusions: ['字幕', '水印'] },
    continuity_locks: { face_anchor: '脸型与五官固定', body_anchor: '身高体型固定', costume_anchor: '牛仔外套固定', accessory_anchor: '双肩包固定', wound_and_stain_anchor: '无伤痕', scene_structure: '站房位置固定', prop_positions: '编织袋始终在右手', key_light_direction: '右后方夕阳', camera_axis: '不越过人物行进轴线', screen_direction: '由左向右', spatial_orientation: '人物在站房南侧' },
    shot_visual_design: { base_content: '林夏与北京西站', composition: '三分法', shot_size: '中景', lens: '50mm', camera_angle: '平视', camera_height: '胸部高度', depth_of_field: '中等景深', spatial_layers: '前景人群，中景林夏，背景站房' },
    color_design: { primary_color: '暖金', secondary_color: '冷灰', accent_color: '蓝色', color_temperature: '5200K', saturation: '中', brightness: '中间调', contrast: '中', blacks_and_highlights: '高光柔和', skin_tone_strategy: '自然', grading_reference: '写实电影调色', start_state: '暖金夕阳', change_reason: '人物移动', peak_state: '面部受光', end_state: '暖色稳定' },
    dynamics_design: { subject_direction: '左到右', subject_trajectory: '直线', force_source: '步行', speed_curve: '匀速', center_of_gravity: '平稳', visual_flow: '人物到站房', secondary_motion: '发丝与衣摆', inertia_and_follow_through: '自然摆动', motion_blur: '背景轻微', stable_regions: '人物面部' },
    camera_design: { movement_type: '缓慢跟拍', start_position: '人物左前方', end_position: '人物正前方', path: '直线', direction: '后退', speed_curve: '匀速', subject_following: '锁定人物', composition_change: '全景到中景', focus_change: '持续跟焦', stability: '稳定器', forbidden_behaviors: '禁止越轴' },
    transition_design: { entry: { adjacent_shot: '无', transition_type: '硬切', visual_handoff: '站房轮廓', audio_handoff: '广播先入', duration_seconds: 0, included_in_shot_duration: false }, internal_linkage: '动作连续', exit: { adjacent_shot: 'E1S02', transition_type: '视线匹配', visual_handoff: '仰望视线', audio_handoff: '保留环境声', duration_seconds: 0, included_in_shot_duration: false } },
  },
  beats: [{ index: 1, page_number: 1, page_slot: 1, start_seconds: 0, keyframe_seconds: 0.8, end_seconds: 1.6, duration_seconds: 1.6, action_phase: '开始', core_event: '林夏停步抬头', start_state: '低头前行', keyframe_state: '停步抬头', end_state: '视线落向站房', character_pose: '肩背轻抬', subject_dynamics: '由行走到停止', secondary_dynamics: '发丝回落', camera_state: '固定中景', color_state: '暖金夕阳', change_from_previous: '建立空间', verbatim_line: '旁白：她终于来到北京。', environmental_sound: '脚步与广播', linkage: '视线延续' }],
  still_prompts: [{ beat_index: 1, keyframe_seconds: 0.8, action_phase: '开始', prompt: '【当前帧核心画面】林夏停步抬头。', exclusions: ['字幕', '水印'] }],
  video_segments: [{ segment_index: 1, from_beat: 1, to_beat: 2, start_seconds: 0.8, end_seconds: 2.4, duration_seconds: 1.6, start_keyframe: 1, end_keyframe: 2, prompt: '【摄影机运动】缓慢跟拍。', exclusions: ['镜头漂移'] }],
  grid_pages: [{ page_number: 1, rows: 3, columns: 3, reading_order: 'left_to_right_top_to_bottom', cells: [], used_slots: 1, empty_slots: 8, composite_prompt: '生成单张3×3九宫格分镜展示图。' }],
  continuity_checks: [{ code: 'timeline_full_coverage', passed: true, severity: 'error', detail: '时间轴完整。' }],
  submission_ready: true,
  warnings: [],
};


describe('StoryboardWorkspace', () => {
  afterEach(cleanup);

  it('renders the shared dark-cyan agent theme with numbered frames', () => {
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        gridUrl="https://example.com/grid.png"
        prompt="九宫格提示词"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const workspace = screen.getByRole('heading', { name: '分镜故事板' }).closest('.storyboard-workspace');
    expect(workspace?.getAttribute('data-visual-theme')).toBe('agent-dark-cyan');
    expect(screen.getByRole('button', { name: /E1S01/ })).toBeTruthy();
    expect(screen.getByRole('heading', { name: /E1S01 时序分镜/ })).toBeTruthy();
    expect(screen.getByText('3×3')).toBeTruthy();
    for (let index = 1; index <= 9; index += 1) {
      expect(screen.getByRole('button', { name: `选择分镜 ${index}` })).toBeTruthy();
    }
  });

  it('exposes prompt and regeneration controls', () => {
    const onRegenerate = vi.fn();
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        gridUrl="https://example.com/grid.png"
        prompt="九宫格提示词"
        promptDetail={promptDetail}
        onRefresh={vi.fn()}
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '查看提示词' }));
    const promptDialog = screen.getByRole('dialog', { name: '宫格提示词 · 第 1 页' });
    expect(promptDialog.getAttribute('data-visual-theme')).toBe('agent-dark-cyan');
    for (const section of (
      ['剧本信息', '全局视觉规范', '连续性锁定项', '画面设计', '色调设计', '动势设计', '运镜设计', '转场设计', '时间拍点', '逐拍出图提示词', '分段运镜视频提示词', '宫格合成说明', '连续性自检']
    )) {
      expect(screen.getByRole('heading', { name: section })).toBeTruthy();
    }
    expect(screen.getByRole('link', { name: '下载 Markdown' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '通用排除项' })).toBeTruthy();
    expect(screen.getByText('每拍必须设置一个明确的关键帧时间。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重新创作本分镜' }));
    expect(onRegenerate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '关闭宫格提示词' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('replaces an unavailable frame image with a readable fallback', () => {
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        gridUrl="https://example.com/grid.png"
        prompt="九宫格提示词"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    fireEvent.error(screen.getByAltText(/E1S01 分镜 1/));
    expect(screen.getByText('分镜图片暂不可用')).toBeTruthy();
  });

  it('recovers from a failed frame when regeneration supplies a new image URL', () => {
    const { rerender } = render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    fireEvent.error(screen.getByAltText(/E1S01 分镜 1/));
    expect(screen.getByText('分镜图片暂不可用')).toBeTruthy();

    rerender(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={[{ ...shots[0], image_url: 'https://example.com/regenerated-shot.png' }, ...shots.slice(1)]}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByAltText(/E1S01 分镜 1/).getAttribute('src')).toBe('https://example.com/regenerated-shot.png');
    expect(screen.queryByText('分镜图片暂不可用')).toBeNull();
  });

  it('traps focus inside the prompt dialog and restores it to the trigger on close', () => {
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        prompt="九宫格提示词"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const trigger = screen.getByRole('button', { name: '查看提示词' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '宫格提示词 · 第 1 页' });
    const download = within(dialog).getByRole('link', { name: '下载 Markdown' });
    const close = within(dialog).getByRole('button', { name: '关闭宫格提示词' });

    expect(document.activeElement).toBe(close);
    close.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(document.activeElement).toBe(download);
    download.focus();
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(close);

    fireEvent.click(close);
    expect(document.activeElement).toBe(trigger);
  });

  it('restarts frame numbering for each 3×3 scene page', () => {
    const secondSceneShots: StoryboardShot[] = Array.from({ length: 9 }, (_, index) => ({
      ...shots[index],
      shot_id: index + 10,
      scene_id: 'E1S02',
      scene: '候车大厅',
    }));
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={[...shots, ...secondSceneShots]}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /E1S02/ }));
    expect(screen.getByRole('button', { name: '选择分镜 1' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '选择分镜 10' })).toBeNull();
  });

  it('exports the complete universal-template inventory and planning constraints', () => {
    const markdown = storyboardPromptMarkdown(promptDetail);

    expect(markdown).toContain('## 最终输出内容');
    expect(markdown).toContain('分段运镜视频提示词');
    expect(markdown).toContain('## 通用排除项');
    expect(markdown).toContain('禁止角色外貌漂移');
    expect(markdown).toContain('## 时间拍点规划规则');
    expect(markdown).toContain('每拍必须设置一个明确的关键帧时间');
    expect(markdown).toContain('## 连续性自检结果');
  });

  it('uses the shared workbench navigation while keeping selectable frames and the filming handoff', () => {
    const onContinue = vi.fn();
    render(
      <StoryboardWorkspace
        title="初到北京被骗"
        shots={shots}
        gridUrl="https://example.com/grid.png"
        prompt="九宫格提示词"
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={onContinue}
      />,
    );

    expect(screen.queryByRole('navigation', { name: '制作流程' })).toBeNull();

    const firstFrame = screen.getByRole('button', { name: '选择分镜 1' });
    const secondFrame = screen.getByRole('button', { name: '选择分镜 2' });
    expect(firstFrame.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(secondFrame);
    expect(secondFrame.getAttribute('aria-pressed')).toBe('true');

    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText(/个分镜场景已完成/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '确认分镜，继续视觉制作' }));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});
