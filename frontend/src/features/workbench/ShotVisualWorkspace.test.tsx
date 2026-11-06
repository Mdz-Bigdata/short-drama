// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ShotVisualWorkspace } from './ShotVisualWorkspace';
import { describeShots, durationWarning, shotStatus, splitQueueItems, useSliderForDurations } from './shotVisual';
import type { BatchAdmission, ShotVideoFailure, ShotVisualWorkspace as Workspace } from './shotVisual';


function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    task_id: 'visual-task',
    current_stage: 5,
    running: false,
    video_model: 'MiniMax-H3',
    provider_family: 'minimax_h3',
    duration_options: [4, 5, 6, 7, 8, 9, 10],
    camera_motions: [
      { value: 'Static', label: '固定' }, { value: 'Push In', label: '推镜' }, { value: 'Orbit', label: '环绕' },
    ],
    shot_types: [{ value: 'Medium Shot', label: '中景' }, { value: 'Close-up', label: '特写' }],
    recipe_categories: [{ value: 'psychology', label: '心理放大', purpose: '情绪进入脸与眼睛' }],
    shots: [
      {
        shot_id: 1, scene_id: 'E1S01', desc: '沈砚推门而入', dialogue: '', sound: '铁链轻响',
        settings: { camera_motion: 'Push In', shot_type: 'Medium Shot', duration_seconds: 6, action: '', ambiance_audio: '', lighting: '', ambiance: '' },
        settings_source: 'derived', derived_notes: [], image_url: '/media/p1.png', video_url: '/media/c1.mp4',
        candidate_urls: ['/media/c1.mp4', '/media/c1-b.mp4'],
        image_prompt: '分镜图提示词', video_prompt: '【批次 1】视频提示词', contract_fingerprint: 'abcdef1234567890',
        route: { mode: 'first_last_frame', provider_family: 'minimax_h3', reasons: ['首帧和尾帧齐全'] }, stale: false, stale_reason: '',
      },
      {
        shot_id: 2, scene_id: 'E1S01', desc: '贺兰霆回头', dialogue: '贺兰霆：你来了。', sound: '风声',
        settings: { camera_motion: 'Static', shot_type: 'Close-up', duration_seconds: 5, action: '', ambiance_audio: '', lighting: '', ambiance: '' },
        settings_source: 'edited', derived_notes: [], image_url: null, video_url: null,
        image_prompt: '', video_prompt: '', contract_fingerprint: '', route: null, stale: true, stale_reason: '运镜、景别或时长已修改，需重跑第 5 阶段后生效',
      },
    ],
    ...overrides,
  };
}


function admission(decision: BatchAdmission['decision']): BatchAdmission {
  const base: BatchAdmission = {
    decision, video_model: 'MiniMax-H3', provider_family: 'minimax_h3',
    counts: { generate: 1, reuse: 1, blocked: 0, withheld: 0 },
    shots: [
      { shot_id: 1, scene_id: 'E1S01', quote: 'reuse', scripted_seconds: 6, requested_seconds: 6, tier_adjustment: 'exact', candidates: 1, problems: [], withheld_by: [], estimate: { priced: true, cost: 0, currency: null } },
      { shot_id: 2, scene_id: 'E1S01', quote: 'generate', scripted_seconds: 5, requested_seconds: 5, tier_adjustment: 'exact', candidates: 1, problems: [], withheld_by: [], estimate: { priced: true, cost: 2.5, currency: 'CNY' } },
    ],
    confirmations: [],
    estimate: { shots_to_generate: 1, requested_seconds: 5, priced: true, cost: 2.5, currency: 'CNY' },
  };
  if (decision === 'blocked') {
    base.counts = { generate: 0, reuse: 1, blocked: 1, withheld: 1 };
    base.shots[1] = { ...base.shots[1], quote: 'blocked', problems: [{ code: 'missing_assets', message: '出场角色尚无身份视图：沈知微', blocking: true }] };
    base.shots[0] = { ...base.shots[0], withheld_by: [2], problems: [{ code: 'generation_batch_admission_withheld', message: '本镜本可生成，但同批有镜头受阻，整批未提交', blocking: false }] };
  }
  if (decision === 'confirmation_required') {
    base.shots[1] = { ...base.shots[1], scripted_seconds: 8, requested_seconds: 10, tier_adjustment: 'up', problems: [{ code: 'duration_confirmation_required', message: '剧本时长 8 秒不在模型档位内，将按 10 秒请求（不裁剪）', blocking: false }] };
    base.confirmations = [{ scripted_seconds: 8, requested_seconds: 10, adjustment: 'up', shot_ids: [2], shot_count: 1, cost: 5, currency: 'CNY', priced: true }];
  }
  return base;
}

describe('ShotVisualWorkspace per-shot regeneration', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('marks one shot for regeneration and says the others are reused', async () => {
    const posts: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/shots/1/regenerate?scene_id=E1S01') && init?.method === 'POST') {
        posts.push(url);
        const next = workspace();
        next.shots[0] = { ...next.shots[0], stale: true, stale_reason: '人工要求重新生成，重跑第 5 阶段时只重做本镜，其余镜头沿用' };
        return { ok: true, json: async () => next } as Response;
      }
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => workspace() } as Response;
    });
    const user = userEvent.setup();

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    await screen.findByRole('list', { name: '分镜' });
    await user.click(screen.getByRole('button', { name: '重做本镜' }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(await screen.findByText(/只重新生成本镜所在的片段/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '重做本镜' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('lists one card per episode and shows only the chosen episode\'s shots', async () => {
    const base = workspace();
    const twoEpisodes = workspace({
      shots: [
        base.shots[0],
        { ...base.shots[0], scene_id: 'E2S01', shot_uid: 200101, desc: '苏问剑提灯走进剑冢', video_url: null, candidate_urls: [] },
        { ...base.shots[0], scene_id: 'E2S02', shot_uid: 200201, shot_id: 1, desc: '裴仲玄负手立在阶下', video_url: '/media/e2s02.mp4', candidate_urls: [] },
      ],
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => twoEpisodes } as Response;
    });
    const user = userEvent.setup();

    render(<ShotVisualWorkspace
      taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream"
      episodes={[{ number: 1, title: '贱籍碰剑，断手', filmDone: true }, { number: 2, title: '你这双手，不是擦剑的' }]}
    />);
    const rail = await screen.findByRole('list', { name: '分集列表' });
    const cards = within(rail).getAllByRole('button');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('贱籍碰剑，断手');
    expect(cards[0].textContent).toContain('制作完成');
    expect(cards[1].textContent).toContain('1/2');
    expect(cards[1].textContent).toContain('50%');
    expect(within(screen.getByRole('list', { name: '分镜' })).getAllByRole('button')).toHaveLength(1);

    await user.click(cards[1]);
    const shots = within(screen.getByRole('list', { name: '分镜' })).getAllByRole('button');
    expect(shots.map(button => button.getAttribute('aria-label'))).toEqual(['E2S01 镜头 1', 'E2S02 镜头 1']);
    expect(within(screen.getByRole('navigation', { name: '场次' })).getAllByRole('button').map(button => button.textContent)).toEqual(['E2S01', 'E2S02']);
    expect(cards[1].getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps two scenes\' shot 1 apart and sends the scene with every shot action', async () => {
    // Every scene numbers its shots from 1: the second scene's shot 1 is a different shot with its own board clip.
    const twoScenes = () => {
      const base = workspace();
      return workspace({
        shots: [
          base.shots[0],
          { ...base.shots[0], scene_id: 'E1S02', shot_uid: 100201, desc: '苏晚在雨中回头', video_url: '/media/s02.mp4', candidate_urls: ['/media/s02.mp4', '/media/s02-b.mp4'] },
        ],
      });
    };
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      if (init?.method === 'POST' || init?.method === 'PUT') {
        calls.push({ url: url.split('/api/drama/visual-task')[1], body: init.body ? JSON.parse(String(init.body)) : undefined });
      }
      return { ok: true, json: async () => twoScenes() } as Response;
    });
    const user = userEvent.setup();

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    const list = await screen.findByRole('list', { name: '分镜' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    // Each scene is marked once above its first shot, since both scenes have a "shot 1".
    expect(within(list).getByText('E1S01')).toBeTruthy();
    expect(within(list).getByText('E1S02')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'E1S02 镜头 1' }));
    expect(screen.getByRole('button', { name: 'E1S02 镜头 1' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'E1S01 镜头 1' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('region', { name: 'E1S02 镜头 1 详情' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '重做本镜' }));
    await waitFor(() => expect(calls).toHaveLength(1));
    await user.click(within(screen.getByRole('list', { name: '候选版本' })).getAllByRole('button', { name: '选用此版' })[1]);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map(call => call.url)).toEqual(['/shots/1/regenerate?scene_id=E1S02', '/shots/1/visual/select?scene_id=E1S02']);
    expect(calls[1].body).toEqual({ video_url: '/media/s02-b.mp4' });
    // The selection stays on the second scene after the workspace comes back.
    expect(screen.getByRole('button', { name: 'E1S02 镜头 1' }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('ShotVisualWorkspace project video model', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('says when the model centre model replaces the project\'s stale one', async () => {
    const note = '项目原选的视频模型 doubao-seedance-2-5-260628 未在模型配置中心启用，将使用配置中心的 MiniMax-H3';
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => workspace({ video_model: 'MiniMax-H3', enabled_video_models: ['MiniMax-H3'], video_model_issue: '', video_model_note: note }) } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    expect(await screen.findByText(note)).toBeTruthy();
    expect(screen.queryByRole('alert', { name: '视频模型不可用' })).toBeNull();
  });

  it('names a model the configuration centre does not enable and switches to an enabled one', async () => {
    const issue = '项目视频模型 doubao-seedance-2-5-260628 未在模型配置中心启用；已启用的视频模型：MiniMax-H3。请在视觉工作区改用已启用的模型';
    const puts: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/video-model') && init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) });
        return { ok: true, json: async () => workspace({ video_model: 'MiniMax-H3', enabled_video_models: ['MiniMax-H3'], video_model_issue: '' }) } as Response;
      }
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => workspace({ video_model: 'doubao-seedance-2-5-260628', enabled_video_models: ['MiniMax-H3'], video_model_issue: issue }) } as Response;
    });
    const onVideoModelChange = vi.fn();
    const user = userEvent.setup();

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onVideoModelChange={onVideoModelChange} />);

    const alert = await screen.findByRole('alert', { name: '视频模型不可用' });
    expect(alert.textContent).toContain('未在模型配置中心启用');
    await user.click(within(alert).getByRole('button', { name: '改用 MiniMax-H3' }));

    await waitFor(() => expect(onVideoModelChange).toHaveBeenCalledWith('MiniMax-H3'));
    expect(puts).toEqual([{ url: 'http://localhost:8000/api/drama/visual-task/video-model', body: { video_model: 'MiniMax-H3' } }]);
    expect(screen.queryByRole('alert', { name: '视频模型不可用' })).toBeNull();
    expect(screen.getByText(/视频模型 MiniMax-H3 · 可用时长/)).toBeTruthy();
  });
});

describe('ShotVisualWorkspace generation queue', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function queue(running: boolean) {
    return {
      task_id: 'visual-task', running, run_id: 'r1',
      counts: { queued: 1, running: 1, done: 1 },
      buckets: { 'seedance/video': { limit: 2, running: 1 }, 'elevenlabs/audio': { limit: 2, running: 0 } },
      items: [
        { key: 'video:1', label: '镜头 1 · 视频 ×1', family: 'seedance', medium: 'video', bucket: 'seedance/video', depends_on: [], status: 'done', meta: {} },
        { key: 'video:2', label: '镜头 2 · 视频 ×1', family: 'seedance', medium: 'video', bucket: 'seedance/video', depends_on: [], status: 'running', meta: {} },
        { key: 'assemble:2', label: '镜头 2 · 配音与入片', family: 'elevenlabs', medium: 'audio', bucket: 'elevenlabs/audio', depends_on: ['video:2'], status: 'queued', meta: {} },
      ],
      withdraw: [] as string[],
    };
  }

  it('shows the items with their buckets and withdraws only a queued one', async () => {
    const posts: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/queue')) return { ok: true, json: async () => queue(true) } as Response;
      if (url.includes('/queue/') && init?.method === 'POST') {
        posts.push(url.split('/api/drama/visual-task')[1]);
        return { ok: true, json: async () => ({ ...queue(true), withdraw: ['assemble:2'] }) } as Response;
      }
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      return { ok: true, json: async () => workspace() } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="seedance2.0" imageModel="seedream" />);

    // The queue is not part of the shot panel: a status chip in the header opens it as a drawer.
    const chip = await screen.findByRole('button', { name: /生成队列/ });
    expect(chip.textContent).toContain('运行中 1');
    expect(screen.queryByRole('dialog', { name: '生成队列' })).toBeNull();
    await userEvent.click(chip);
    const panel = await screen.findByRole('dialog', { name: '生成队列' });
    expect(within(panel).getByText(/排队中 1 · 运行中 1 · 完成 1/)).toBeTruthy();
    expect(within(panel).getByText(/seedance\/video 1\/2/)).toBeTruthy();
    expect(within(panel).getByText('依赖 video:2', { exact: false })).toBeTruthy();
    expect(within(panel).queryByRole('button', { name: '取消 镜头 2 · 视频 ×1' })).toBeNull();

    await userEvent.click(within(panel).getByRole('button', { name: '取消 镜头 2 · 配音与入片' }));

    expect(await within(panel).findByText('取消待生效')).toBeTruthy();
    expect(posts).toEqual(['/queue/assemble%3A2/cancel']);
    await userEvent.click(within(panel).getByRole('button', { name: '取消全部排队' }));
    expect(posts[1]).toBe('/queue/cancel-queued');
    await userEvent.click(within(panel).getByRole('button', { name: '关闭队列' }));
    expect(screen.queryByRole('dialog', { name: '生成队列' })).toBeNull();
  });

  it('folds the finished items away until they are asked for', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/queue')) return { ok: true, json: async () => queue(true) } as Response;
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      return { ok: true, json: async () => workspace() } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="seedance2.0" imageModel="seedream" />);

    await userEvent.click(await screen.findByRole('button', { name: /生成队列/ }));
    const panel = await screen.findByRole('dialog', { name: '生成队列' });
    expect(within(panel).getByText('镜头 2 · 视频 ×1')).toBeTruthy();
    expect(within(panel).queryByText('镜头 1 · 视频 ×1')).toBeNull();
    const fold = within(panel).getByRole('button', { name: /已结束 1 项（完成 1）/ });
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    await userEvent.click(fold);
    expect(within(panel).getByText('镜头 1 · 视频 ×1')).toBeTruthy();
    expect(within(panel).getAllByRole('listitem')).toHaveLength(3);
  });

  it('stays out of the way when the project has no queue yet', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/queue')) return { ok: true, json: async () => ({ task_id: 'visual-task', running: false, items: [], counts: {}, buckets: {} }) } as Response;
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      return { ok: true, json: async () => workspace() } as Response;
    });
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="seedance2.0" imageModel="seedream" />);
    await screen.findByRole('list', { name: '分镜' });
    expect(screen.queryByRole('button', { name: /生成队列/ })).toBeNull();
    expect(screen.queryByRole('dialog', { name: '生成队列' })).toBeNull();
  });
});

describe('ShotVisualWorkspace batch admission', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function mockApi(verdict: ReturnType<typeof admission>, posts: Array<unknown>) {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/shots/admission') && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        const confirmed = (posts[posts.length - 1] as { persist?: boolean }).persist;
        return { ok: true, json: async () => (confirmed ? admission('admitted') : verdict) } as Response;
      }
      if (url.includes('/usage')) {
        return { ok: true, json: async () => ({ summary: { calls: 3, succeeded: 2, failed: 1, cost_by_currency: { CNY: 12.5 }, primary_currency: 'CNY', unpriced_calls: 1, unpriced_models: ['x'] } }) } as Response;
      }
      return { ok: true, json: async () => workspace() } as Response;
    });
  }

  it('shows the verdict, the estimate and what the project has spent', async () => {
    mockApi(admission('admitted'), []);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    const panel = await screen.findByRole('region', { name: '批量视频准入' });
    expect(panel.textContent).toContain('准入通过');
    expect(panel.textContent).toContain('生成 1 · 复用 1 · 受阻 0');
    expect(panel.textContent).toContain('预估 2.50 CNY（5 秒）');
    expect(panel.textContent).toContain('已花费 12.50 CNY（1 次调用未定价）');
  });

  it('lists every blocked shot and says the batch was withheld', async () => {
    mockApi(admission('blocked'), []);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    const panel = await screen.findByRole('region', { name: '批量视频准入' });
    expect(panel.textContent).toContain('受阻：整批未提交');
    expect(panel.textContent).toContain('镜头 2');
    expect(panel.textContent).toContain('出场角色尚无身份视图：沈知微');
    expect(panel.textContent).toContain('其余 1 镜');
  });

  it('says a reason shared by every shot once, not once per shot', async () => {
    const running = admission('blocked');
    running.counts = { generate: 0, reuse: 0, blocked: 2, withheld: 0 };
    running.shots = running.shots.map(shot => ({
      ...shot, quote: 'blocked', withheld_by: [],
      problems: [{ code: 'active_task', message: '第 5 阶段正在运行，等它结束再提交', blocking: true }],
    }));
    mockApi(running, []);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    const panel = await screen.findByRole('region', { name: '批量视频准入' });
    const lines = within(panel).getAllByRole('listitem');
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toContain('第 5 阶段正在运行，等它结束再提交');
    expect(lines[0].textContent).toContain('全部 2 镜');
  });

  it('confirms the duration tiers for the whole batch and shows the cleared verdict', async () => {
    const posts: Array<unknown> = [];
    mockApi(admission('confirmation_required'), posts);
    const user = userEvent.setup();

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    const panel = await screen.findByRole('region', { name: '批量视频准入' });
    expect(panel.textContent).toContain('剧本 8 秒 → 请求 10 秒 × 1 镜');
    expect(panel.textContent).toContain('5.00 CNY');
    await user.click(within(panel).getByRole('button', { name: '确认这些档位' }));

    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual({ confirmed_request_durations: [{ scripted_seconds: 8, requested_seconds: 10 }], persist: true });
    await waitFor(() => expect(screen.getByRole('region', { name: '批量视频准入' }).textContent).toContain('准入通过'));
  });
});

describe('ShotVisualWorkspace', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('lists every shot with its camera settings and edits one through the visual stage API', async () => {
    const puts: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) });
        const next = workspace();
        next.shots[0] = { ...next.shots[0], settings: { ...next.shots[0].settings, camera_motion: 'Orbit', duration_seconds: 8 }, settings_source: 'edited', stale: true, stale_reason: '运镜、景别或时长已修改，需重跑第 5 阶段后生效' };
        return { ok: true, json: async () => next } as Response;
      }
      return { ok: true, json: async () => workspace() } as Response;
    });
    const onRerun = vi.fn();

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={onRerun} />);

    const list = await screen.findByRole('list', { name: '分镜' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('推镜');
    expect(rows[0].textContent).toContain('6 秒');
    expect(rows[0].textContent).toContain('已生成');
    expect(rows[1].textContent).toContain('需重跑');

    const save = screen.getByRole('button', { name: /保存运镜/ });
    expect(save.hasAttribute('disabled')).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('镜头运动'), 'Orbit');
    await userEvent.click(within(screen.getByRole('radiogroup', { name: '时长选择' })).getByRole('radio', { name: '8 秒' }));
    expect(save.hasAttribute('disabled')).toBe(false);
    await userEvent.click(save);

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].url).toBe('http://localhost:8000/api/drama/visual-task/shots/1/visual?scene_id=E1S01');
    expect(puts[0].body).toMatchObject({ camera_motion: 'Orbit', shot_type: 'Medium Shot', duration_seconds: 8 });
    expect(await screen.findByText(/运镜设置已保存，重跑第 5 阶段后生效/)).toBeTruthy();
    expect(within(screen.getByRole('list', { name: '分镜' })).getAllByRole('listitem')[0].textContent).toContain('环绕');

    await userEvent.click(screen.getByRole('button', { name: /重跑第 5 阶段/ }));
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it('shows the stale reason, switches tabs and locks edits while a stage is running', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => workspace({ running: true }) } as Response);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    await userEvent.click(await screen.findByRole('button', { name: 'E1S01 镜头 2' }));
    expect(screen.getByText(/需重跑第 5 阶段后生效/)).toBeTruthy();
    expect(screen.getByText(/任务正在执行阶段，暂不能修改运镜/)).toBeTruthy();
    expect((screen.getByLabelText('镜头运动') as HTMLSelectElement).disabled).toBe(true);

    await userEvent.click(screen.getByRole('tab', { name: '脚本 / 对话' }));
    expect(within(screen.getByRole('tabpanel')).getByText('贺兰霆：你来了。')).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: '提示词' }));
    // 分镜图提示词还没生成；视频提示词编辑器为空，且阶段运行中不可编辑。
    expect(within(screen.getByRole('tabpanel')).getAllByText('待生成')).toHaveLength(1);
    expect((screen.getByLabelText('视频提示词文稿') as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('composes a camera recipe and applies its move and action to the draft', async () => {
    const posts: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/shots/1/visual/recipe?scene_id=E1S01') && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return { ok: true, json: async () => ({
          category: 'psychology', category_label: '心理放大', intensity: 'strong', camera_motion: 'Orbit', camera_motion_label: '环绕',
          angle_label: '平视', rhythm_label: '慢节奏', prompt_zh: '镜头围绕主体环绕（Orbit），平视机位，慢节奏；沈砚推门而入',
          prompt_en: 'orbit camera move', negative: 'static camera', provider_phrase: '镜头围绕主体环绕（Orbit）',
        }) } as Response;
      }
      return { ok: true, json: async () => workspace() } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    await screen.findByRole('list', { name: '分镜' });
    await userEvent.selectOptions(screen.getByLabelText('运镜灵感'), 'psychology');
    await userEvent.click(within(screen.getByRole('radiogroup', { name: '情绪强度' })).getByRole('radio', { name: '强' }));
    await userEvent.click(screen.getByRole('button', { name: '生成配方' }));

    expect(await screen.findByText(/心理放大 · 环绕 · 平视 · 慢节奏/)).toBeTruthy();
    expect(posts[0]).toEqual({ category: 'psychology', intensity: 'strong' });
    await userEvent.click(screen.getByRole('button', { name: '套用到本镜' }));
    expect((screen.getByLabelText('镜头运动') as HTMLSelectElement).value).toBe('Orbit');
    expect((screen.getByLabelText('动作演变') as HTMLTextAreaElement).value).toContain('沈砚推门而入');
    expect(screen.getByRole('button', { name: /保存运镜/ }).hasAttribute('disabled')).toBe(false);
  });

  it('assigns scene seeds and lets the user pick a rendered candidate', async () => {
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'POST' || init?.method === 'PUT') {
        calls.push({ url, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined });
        const next = workspace();
        next.shots[0] = { ...next.shots[0], settings: { ...next.shots[0].settings, seed: 123001 }, video_url: '/media/c1-b.mp4' };
        return { ok: true, json: async () => next } as Response;
      }
      return { ok: true, json: async () => workspace() } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    await screen.findByRole('list', { name: '分镜' });
    await userEvent.click(screen.getByRole('button', { name: '按场分配种子' }));
    expect(await screen.findByText(/已按场景分配固定种子/)).toBeTruthy();
    expect((screen.getByLabelText('种子') as HTMLInputElement).value).toBe('123001');

    const candidates = within(screen.getByRole('list', { name: '候选版本' })).getAllByRole('button', { name: '选用此版' });
    expect(candidates).toHaveLength(2);
    await userEvent.click(candidates[1]);
    expect(await screen.findByText(/已选用该版本/)).toBeTruthy();
    // The workspace also asks for the batch admission when it opens; that call is not part of this flow.
    const flow = calls.filter(call => !call.url.endsWith('/shots/admission'));
    expect(flow.map(call => call.url.split('/api/drama/visual-task')[1])).toEqual(['/shots/seeds/assign', '/shots/1/visual/select?scene_id=E1S01']);
    expect(flow[1].body).toEqual({ video_url: '/media/c1-b.mp4' });
  });

  it('shows what the 3D director desk applied to a shot, and takes it back out', async () => {
    const still = {
      id: 'cap-still', kind: 'still', shot_id: 1, camera_id: 'cam-01', url: '/media/desk_still.png', width: 1080, height: 1920,
      duration_s: 0, fps: 0, plan_revision: 7, shows_limbs: false, monochrome: false, labelled: false, created_at: '2026-09-20T02:00:00Z', stale: false, warning: '',
    };
    const clip = { ...still, id: 'cap-clip', kind: 'clip', url: '/media/desk_clip.mp4', duration_s: 5, fps: 24, shows_limbs: true, stale: true };
    const captures = { captures: [still, clip], applied: { 1: { still: 'cap-still', clip: 'cap-clip' } } };
    const posts: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/director-desk/')) {
        if (init?.method === 'POST') {
          posts.push(url);
          return { ok: true, json: async () => ({ captures: [still, clip], applied: { 1: { still: 'cap-still' } } }) } as Response;
        }
        return { ok: true, json: async () => captures } as Response;
      }
      return { ok: true, json: async () => workspace() } as Response;
    });

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    const panel = await screen.findByRole('region', { name: '镜头 1 的 3D 导演台参考' });
    const rows = await within(panel).findAllByRole('listitem');

    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('导演台静帧');
    expect(within(rows[0]).getByRole('img', { name: '第 1 镜导演台静帧' }).getAttribute('src')).toBe('/media/desk_still.png');
    // The blocking moved after this clip was filmed, so stage 5 will not use it and the card says so.
    expect(rows[1].textContent).toContain('白模视频 · 5 秒 · 24 fps');
    expect(within(rows[1]).getByTitle(/站位已修改/).textContent).toBe('过期');
    expect(within(rows[1]).getByText('带四肢')).toBeTruthy();

    await userEvent.click(within(rows[1]).getByRole('button', { name: /取消应用/ }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toContain('/director-desk/scenes/E1S01/captures/cap-clip/unapply');
    await waitFor(() => expect(within(panel).getAllByRole('listitem')).toHaveLength(1));
    expect((await within(panel).findByRole('status')).textContent).toContain('已从第 1 镜取消应用');

    // The entry opens the desk on this shot's own scene; every entry point opens that same stage.
    expect(within(panel).getByRole('button', { name: '打开第 1 镜的 3D 导演台' }).getAttribute('aria-haspopup')).toBe('dialog');
  });

  it('describes a group of shots by scene, or as the whole batch', () => {
    const shots = [{ shot_id: 1, scene_id: 'E1S01' }, { shot_id: 2, scene_id: 'E1S01' }, { shot_id: 1, scene_id: 'E1S02' }];
    expect(describeShots(shots, 5)).toBe('E1S01 镜头 1、2 · E1S02 镜头 1');
    expect(describeShots(shots, 3)).toBe('全部 3 镜');
    expect(describeShots([{ shot_id: 3, scene_id: '' }], 4)).toBe('镜头 3');
    const many = Array.from({ length: 20 }, (_, index) => ({ shot_id: 1, scene_id: `E1S${String(index + 1).padStart(2, '0')}` }));
    expect(describeShots(many, 30)).toMatch(/E1S12 镜头 1 · 等共 20 镜$/);
    const item = (status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'skipped') =>
      ({ key: status, label: status, family: 'x', medium: 'video' as const, bucket: 'x', depends_on: [], status, meta: {} });
    const split = splitQueueItems([item('done'), item('running'), item('failed'), item('cancelled'), item('queued'), item('skipped')]);
    expect(split.active.map(entry => entry.status)).toEqual(['running', 'failed', 'queued']);
    expect(split.settled.map(entry => entry.status)).toEqual(['done', 'cancelled', 'skipped']);
  });

  it('judges durations against the model range and picks chips or a slider', () => {
    expect(durationWarning(6, [4, 5, 6])).toBe('');
    expect(durationWarning(12, [4, 5, 6])).toBe('当前秒数 12 不在模型支持范围 [4-6] 内');
    expect(durationWarning(6, [])).toBe('当前模型未配置可用时长，无法修改');
    expect(useSliderForDurations([4, 5, 6, 7, 8, 9, 10])).toBe(false);
    expect(useSliderForDurations(Array.from({ length: 27 }, (_, index) => index + 4))).toBe(true);
    expect(useSliderForDurations([4, 6, 8, 10, 12, 14, 16, 18])).toBe(false);
  });
});


describe('ShotVisualWorkspace provider refusal', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const panels = [
    'http://localhost:8000/media/storyboards/frames/fb2db437_E1S09_1_cf3f5c4559.png',
    'http://localhost:8000/media/storyboards/frames/fb2db437_E1S09_2_38631e12b3.png',
  ];
  const refusal: ShotVideoFailure = {
    kind: 'input_image_sensitive', kind_label: '输入图被判敏感', code: '1026', scene_id: 'E1S09',
    message: 'MiniMax H3 请求失败: RuntimeError: MiniMax H3 task ended with status=failed: 1026 input new_sensitive, input image sensitive',
    hint: '供应商拒收了其中一张输入图。多半是 E1S09 的分镜画面需要重画：在分镜阶段打开「空间调度」，点「按当前站位重画本场」。',
    panels,
  };

  function refusedWorkspace(failure: ShotVideoFailure | null = refusal): Workspace {
    const base = workspace();
    const [first] = base.shots;
    // Shot numbers restart per scene: E1S09 has its own shots 1 and 2.
    const refused = [1, 2].map(number => ({
      ...first, shot_id: number, scene_id: 'E1S09', desc: `E1S09 第 ${number} 镜`, image_url: panels[number - 1],
      video_url: null, candidate_urls: [], route: null, failure,
    }));
    return { ...base, shots: [first, ...refused] };
  }

  it('marks a refused board red in the list, over a stale mark', () => {
    const shot = refusedWorkspace().shots[1];
    expect(shotStatus(shot)).toEqual({ key: 'refused', label: '被拒' });
    expect(shotStatus({ ...shot, stale: true })).toEqual({ key: 'refused', label: '被拒' });
    expect(shotStatus({ ...shot, failure: { ...refusal, kind: 'provider_error' } })).toEqual({ key: 'failed', label: '失败' });
    expect(shotStatus({ ...shot, failure: null })).toEqual({ key: 'partial', label: '仅首帧' });
  });

  it('shows the refused shots and a card with the provider words, the hint and the panels that were sent', async () => {
    let current = refusedWorkspace();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ({ ok: true, json: async () => current }) as Response);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    const list = await screen.findByRole('list', { name: '分镜' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows[0].textContent).toContain('已生成');
    expect(rows[1].querySelector('.shot-workspace__status.is-refused')?.textContent).toBe('被拒');
    expect(rows[2].textContent).toContain('被拒');
    // The first shot rendered: no card for it.
    expect(screen.queryByRole('alert', { name: '出片失败' })).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'E1S09 镜头 1' }));
    const card = screen.getByRole('alert', { name: '出片失败' });
    expect(card.textContent).toContain('输入图被判敏感');
    expect(card.textContent).toContain('1026');
    expect(card.textContent).toContain('1026 input new_sensitive, input image sensitive');
    expect(card.textContent).toContain('按当前站位重画本场');
    const thumbs = within(within(card).getByRole('list', { name: '发出去的分镜画面' })).getAllByRole('img');
    expect(thumbs.map(img => img.getAttribute('src'))).toEqual(panels);

    // Once the board renders the backend drops the failure, and the card goes with it.
    current = refusedWorkspace(null);
    current.shots[1] = { ...current.shots[1], video_url: '/media/e1s09.mp4' };
    cleanup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    const reloaded = await screen.findByRole('list', { name: '分镜' });
    await waitFor(() => expect(within(reloaded).getAllByRole('listitem')[1].textContent).toContain('已生成'));
    await userEvent.click(screen.getByRole('button', { name: 'E1S09 镜头 1' }));
    expect(screen.queryByRole('alert', { name: '出片失败' })).toBeNull();
  });
});

describe('ShotVisualWorkspace pilot shot', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const ready = {
    state: 'ready', shot_id: 1, shot_uid: 100101, label: '镜头 1', reason: '这段 1 个人、1 个动作，变量最少，走样时最容易看出问题',
    video_url: '/media/pilot.mp4', others_left: 2, checks: ['脸', '服装', '人数', '动作', '口型'],
  };

  function mockPilot(pilot: unknown, posts: Array<unknown>) {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/shots/pilot')) {
        posts.push(JSON.parse(String(init?.body)));
        return { ok: true, json: async () => ({ ...workspace(), pilot: { state: 'running', label: '镜头 1' } }) } as Response;
      }
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => ({ ...workspace(), pilot }) } as Response;
    });
  }

  it('offers one clip before the batch and shows it is running', async () => {
    const posts: unknown[] = [];
    mockPilot(null, posts);
    const user = userEvent.setup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: '先试拍一段' }));

    expect(posts).toEqual([{}]);
    expect(await screen.findByText(/正在试拍/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '先试拍一段' })).toBeNull();
  });

  it('lets the batch go when the clip is right', async () => {
    mockPilot(ready, []);
    const onRerun = vi.fn();
    const user = userEvent.setup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={onRerun} />);

    expect((await screen.findByLabelText('试拍片段')).getAttribute('src')).toBe('/media/pilot.mp4');
    await user.click(screen.getByRole('button', { name: '通过，生成其余 2 镜' }));

    expect(onRerun).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: '通过，生成其余 2 镜' })).toBeNull();
  });

  it('holds the batch while a problem is ticked and sends it with the reshoot', async () => {
    const posts: unknown[] = [];
    mockPilot(ready, posts);
    const user = userEvent.setup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={vi.fn()} />);

    await user.click(await screen.findByRole('checkbox', { name: '脸' }));
    expect((screen.getByRole('button', { name: '通过，生成其余 2 镜' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: '不行，重拍这一段' }));

    expect(posts).toEqual([{ redo: true, problems: ['脸'] }]);
  });

  it('starts a new clip with nothing ticked', async () => {
    let current = ready;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/shots/pilot')) {
        current = { ...ready, video_url: '/media/pilot2.mp4' };
        return { ok: true, json: async () => ({ ...workspace(), pilot: current }) } as Response;
      }
      if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
      if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
      return { ok: true, json: async () => ({ ...workspace(), pilot: current }) } as Response;
    });
    const user = userEvent.setup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={vi.fn()} />);

    await user.click(await screen.findByRole('checkbox', { name: '脸' }));
    await user.click(screen.getByRole('button', { name: '不行，重拍这一段' }));

    await waitFor(() => expect((screen.getByLabelText('试拍片段')).getAttribute('src')).toBe('/media/pilot2.mp4'));
    expect((screen.getByRole('checkbox', { name: '脸' }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole('button', { name: '通过，生成其余 2 镜' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows why a pilot failed and can try again', async () => {
    const posts: unknown[] = [];
    mockPilot({ state: 'failed', label: '镜头 1', error: 'HTTP 400 疑似真人' }, posts);
    const user = userEvent.setup();
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" onRerun={vi.fn()} />);

    expect(await screen.findByText('HTTP 400 疑似真人')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '再试一次' }));

    expect(posts).toEqual([{ redo: true }]);
  });
});
