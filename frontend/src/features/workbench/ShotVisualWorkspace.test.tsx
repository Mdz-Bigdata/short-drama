// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ShotVisualWorkspace } from './ShotVisualWorkspace';
import { durationWarning, useSliderForDurations } from './shotVisual';
import type { BatchAdmission, ShotVisualWorkspace as Workspace } from './shotVisual';


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
      if (url.endsWith('/shots/1/regenerate') && init?.method === 'POST') {
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
    expect(await screen.findByText(/只重新生成本镜/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '重做本镜' }) as HTMLButtonElement).disabled).toBe(true);
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

    const panel = await screen.findByRole('region', { name: '生成队列' });
    expect(within(panel).getByText(/排队中 1 · 运行中 1 · 完成 1/)).toBeTruthy();
    expect(within(panel).getByText(/seedance\/video 1\/2/)).toBeTruthy();
    expect(within(panel).getByText('依赖 video:2', { exact: false })).toBeTruthy();
    expect(within(panel).queryByRole('button', { name: '取消 镜头 2 · 视频 ×1' })).toBeNull();

    await userEvent.click(within(panel).getByRole('button', { name: '取消 镜头 2 · 配音与入片' }));

    expect(await within(panel).findByText('取消待生效')).toBeTruthy();
    expect(posts).toEqual(['/queue/assemble%3A2/cancel']);
    await userEvent.click(within(panel).getByRole('button', { name: '取消全部排队' }));
    expect(posts[1]).toBe('/queue/cancel-queued');
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
    expect(screen.queryByRole('region', { name: '生成队列' })).toBeNull();
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
    expect(puts[0].url).toBe('http://localhost:8000/api/drama/visual-task/shots/1/visual');
    expect(puts[0].body).toMatchObject({ camera_motion: 'Orbit', shot_type: 'Medium Shot', duration_seconds: 8 });
    expect(await screen.findByText(/运镜设置已保存，重跑第 5 阶段后生效/)).toBeTruthy();
    expect(within(screen.getByRole('list', { name: '分镜' })).getAllByRole('listitem')[0].textContent).toContain('环绕');

    await userEvent.click(screen.getByRole('button', { name: /重跑第 5 阶段/ }));
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it('shows the stale reason, switches tabs and locks edits while a stage is running', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => workspace({ running: true }) } as Response);

    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);

    await userEvent.click(await screen.findByRole('button', { name: '镜头 2' }));
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
      if (url.endsWith('/shots/1/visual/recipe') && init?.method === 'POST') {
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
    expect(flow.map(call => call.url.split('/api/drama/visual-task')[1])).toEqual(['/shots/seeds/assign', '/shots/1/visual/select']);
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

  it('judges durations against the model range and picks chips or a slider', () => {
    expect(durationWarning(6, [4, 5, 6])).toBe('');
    expect(durationWarning(12, [4, 5, 6])).toBe('当前秒数 12 不在模型支持范围 [4-6] 内');
    expect(durationWarning(6, [])).toBe('当前模型未配置可用时长，无法修改');
    expect(useSliderForDurations([4, 5, 6, 7, 8, 9, 10])).toBe(false);
    expect(useSliderForDurations(Array.from({ length: 27 }, (_, index) => index + 4))).toBe(true);
    expect(useSliderForDurations([4, 6, 8, 10, 12, 14, 16, 18])).toBe(false);
  });
});
