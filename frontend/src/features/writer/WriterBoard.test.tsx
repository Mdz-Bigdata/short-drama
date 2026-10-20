// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterRelationshipGraph } from './CharacterRelationshipGraph';
import { ScriptVersionMenu } from './ScriptVersionMenu';
import { ShotTable } from './ShotTable';
import { StoryEventTimeline } from './StoryEventTimeline';
import { WriterAgentPage } from './WriterAgentPage';
import { WriterAgentPageContainer } from './WriterAgentPageContainer';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ShotTable', () => {
  it('lists every shot with its tag, frame, length, picture text and verbatim lines', () => {
    render(<ShotTable scenes={[
      { sceneId: 'E1S01', episodeIndex: 1, sceneIndex: 1, durationSeconds: 4, label: '清晨群山雾起', description: '河谷白雾贴着林坡漫上。', content: 'x', imageUrl: 'https://img.example/e1s01.jpg', dialogue: [{ kind: 'voiceover', text: '清晨的雾，从四川南部的山谷里慢慢升起来。', verbatim: true }] },
      { sceneId: 'E1S02', episodeIndex: 1, sceneIndex: 2, durationSeconds: 11, description: '江水沿石岸流过。', dialogue: [{ kind: 'dialogue', speaker: '哈大王', text: '走。' }] },
      { sceneId: 'E2S01', episodeIndex: 2, sceneIndex: 1, durationSeconds: 8, description: '绝壁。', dialogue: [] },
    ]} />);
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText('E1S01')).toBeTruthy();
    expect(within(rows[0]).getByText('第 1 集第 1 镜')).toBeTruthy();
    expect(within(rows[0]).getByText('清晨群山雾起')).toBeTruthy();
    expect(within(rows[0]).getByRole('img').getAttribute('src')).toBe('https://img.example/e1s01.jpg');
    expect(within(rows[0]).getByText('4s')).toBeTruthy();
    expect(within(rows[0]).getByText('原文')).toBeTruthy();
    expect(within(rows[0]).getByText(/说书旁白为原文逐字/)).toBeTruthy();
    expect(within(rows[1]).queryByRole('img')).toBeNull();
    expect(within(rows[1]).getByText('哈大王：')).toBeTruthy();
    expect(within(rows[1]).queryByText('原文')).toBeNull();
    expect(within(rows[2]).getByText('第 2 集第 1 镜')).toBeTruthy();
    expect(within(rows[2]).getByText('无口播')).toBeTruthy();
  });
});

describe('StoryEventTimeline', () => {
  it('adds, edits and removes nodes and hands the whole arrangement back', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<StoryEventTimeline events={[{ eventId: 'e1', phase: '故事开始', title: '僰人受封', desc: '商末牧野之战', points: ['牧野战场'] }]} onSave={onSave} />);
    expect(screen.getByText('僰人受封')).toBeTruthy();
    expect(screen.getByText('牧野战场')).toBeTruthy();
    expect(screen.getByText(/由分集账本生成/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '添加节点' }));
    await user.selectOptions(screen.getByLabelText('阶段'), '进展纠葛');
    await user.type(screen.getByLabelText('标题'), '悬棺葬俗');
    await user.type(screen.getByLabelText('要点（每行一条）'), '楠木凿船棺\n绞盘吊棺上绝壁');
    await user.click(screen.getByRole('button', { name: '添加' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual([
      { phase: '故事开始', title: '僰人受封', desc: '商末牧野之战', points: ['牧野战场'] },
      { phase: '进展纠葛', title: '悬棺葬俗', desc: '', points: ['楠木凿船棺', '绞盘吊棺上绝壁'] },
    ]);

    await user.click(screen.getByRole('button', { name: '删除节点 僰人受封' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0]).toEqual([]);
  });

  it('refuses an empty title and says when the arrangement is hand made', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<StoryEventTimeline events={[]} authored onSave={onSave} />);
    expect(screen.getByText(/已手动编排/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '添加节点' }));
    await user.click(screen.getByRole('button', { name: '添加' }));
    expect(screen.getByRole('alert').textContent).toContain('请填写节点标题');
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe('ScriptVersionMenu', () => {
  it('saves the current version under a name and restores an earlier one', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onRestore = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ScriptVersionMenu versions={[{ versionId: 'v2', label: '第二稿', createdAt: '2026-10-15T08:00:00+00:00', sourceHash: 'b'.repeat(64), episodeCount: 6, sceneCount: 120 }]} onSave={onSave} onRestore={onRestore} />);
    await user.click(screen.getByRole('button', { name: /版本 \(1\)/ }));
    expect(screen.getByText('第二稿')).toBeTruthy();
    expect(screen.getByText(/6 集 · 120 镜/)).toBeTruthy();
    await user.type(screen.getByLabelText('版本名称'), '初稿');
    await user.click(screen.getByRole('button', { name: '保存当前版本' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('初稿'));
    await user.click(screen.getByRole('button', { name: '恢复' }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledWith('v2'));
  });
});

describe('WriterAgentPage board', () => {
  it('shows the creation mode, edits the overview and keeps the new sections on the board', async () => {
    const onSaveOverview = vi.fn().mockResolvedValue(undefined);
    const onRegenerateOverview = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<WriterAgentPage
      title="僰人悬棺"
      creationMode="narration"
      breakdown={{
        overview: { synopsis: '在四川珙县的群山中，高崖悬棺静默停泊。', genre: '历史传奇', theme: '文明传承', world_setting: '四川南部珙县' },
        scenes: [{ scene_id: 'E1S01', content: '清晨的雾', duration: '4s', characters: ['哈大王'] }],
        timeline: [{ phase: '故事开始', title: '僰人受封', desc: '', points: [] }],
        roles: [{ name: '哈大王', position: '男主角' }],
        relationships: [],
      }}
      script="第1集 开端\n清晨的雾"
      onSaveOverview={onSaveOverview}
      onRegenerateOverview={onRegenerateOverview}
      onSaveTimeline={vi.fn()}
    />);
    expect(screen.getByText('旁白模式')).toBeTruthy();
    expect(screen.getByRole('heading', { name: /剧情事件与爽点节奏 \(1\)/ })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /剧本明细/ })).toBeNull();
    expect(screen.queryByRole('heading', { name: /人物关系星图/ })).toBeNull();

    await user.click(screen.getByRole('button', { name: '编辑' }));
    const form = screen.getByRole('form', { name: '编辑项目概述' });
    const genre = within(form).getByLabelText('题材') as HTMLInputElement;
    expect(genre.value).toBe('历史传奇');
    await user.clear(genre);
    await user.type(genre, '民族史诗');
    await user.click(within(form).getByRole('button', { name: '保存概述' }));
    await waitFor(() => expect(onSaveOverview).toHaveBeenCalledTimes(1));
    expect(onSaveOverview.mock.calls[0][0]).toMatchObject({ genre: '民族史诗', synopsis: '在四川珙县的群山中，高崖悬棺静默停泊。', world_setting: '四川南部珙县' });

    await user.click(screen.getByRole('button', { name: '重新创作' }));
    await waitFor(() => expect(onRegenerateOverview).toHaveBeenCalledTimes(1));
  });

  it('opens the character network as its own page under the 人物关系 tab', async () => {
    const user = userEvent.setup();
    render(<WriterAgentPage
      title="僰人悬棺"
      breakdown={{ scenes: [], timeline: [], roles: [{ name: '哈大王', position: '男主角' }, { name: '哈公妹', position: '女主角' }], relationships: [{ from: '哈大王', to: '哈公妹', relation: '兄妹' }] }}
      script="第1集 开端"
    />);
    await user.click(screen.getByRole('button', { name: '人物关系' }));
    expect(screen.getByRole('button', { name: '人物关系' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('heading', { name: /人物关系星图/ }).textContent).toContain('2 角色 · 1 关系');
    expect(screen.queryByRole('heading', { name: '角色与视角设定' })).toBeNull();
    expect(screen.queryByRole('region', { name: '资产改名与合并' })).toBeNull();
    expect(screen.getByRole('group', { name: '星图缩放' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /剧本明细/ })).toBeNull();
    expect(screen.queryByRole('heading', { name: /剧情事件与爽点节奏/ })).toBeNull();
  });
});

describe('CharacterRelationshipGraph labels', () => {
  it('names every relation on its line and leaves out a same-scene count', () => {
    const { container } = render(<CharacterRelationshipGraph
      roles={[{ name: '陆昭', position: '男主角' }, { name: '殷无咎', position: '反派' }, { name: '苏挽', position: '女主角' }, { name: '白小七', position: '女配角' }]}
      relationships={[
        { from: '殷无咎', to: '陆昭', relation: '敌对', bidirectional: true },
        { from: '陆昭', to: '苏挽', relation: '惺惺相惜', bidirectional: true },
        { from: '白小七', to: '陆昭', relation: '同场互动 · 8 场', bidirectional: true },
      ]}
    />);
    const labels = [...container.querySelectorAll('[data-relation-label="true"]')];
    expect(labels.map(label => label.textContent)).toEqual(['敌对', '惺惺相惜']);
    expect(container.textContent).not.toMatch(/同场/);
  });
});

describe('CharacterRelationshipGraph full screen', () => {
  it('opens full screen on a double click and leaves it on Esc or the exit button', () => {
    render(<CharacterRelationshipGraph
      roles={[{ name: '陆昭', position: '男主角' }, { name: '殷无咎', position: '反派' }]}
      relationships={[{ from: '殷无咎', to: '陆昭', relation: '宿敌', bidirectional: true }]}
    />);
    const field = () => document.querySelector('.writer-relationship-canvas') as HTMLElement;
    // jsdom has no Fullscreen API: the field fills the window, rendered straight under <body>.
    fireEvent.doubleClick(field());
    expect(field().classList.contains('is-fullscreen')).toBe(true);
    expect(field().parentElement).toBe(document.body);
    expect(document.querySelectorAll('[data-relation-label="true"]')).toHaveLength(1);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(field().classList.contains('is-fullscreen')).toBe(false);
    expect(field().parentElement).not.toBe(document.body);
    fireEvent.doubleClick(field());
    fireEvent.click(screen.getByRole('button', { name: '退出全屏' }));
    expect(field().classList.contains('is-fullscreen')).toBe(false);
    // A quick double click on the zoom buttons zooms; it does not open full screen.
    fireEvent.doubleClick(screen.getByRole('button', { name: '放大' }));
    expect(field().classList.contains('is-fullscreen')).toBe(false);
  });

  it('asks the browser for real full screen when it can', () => {
    const request = vi.fn().mockResolvedValue(undefined);
    const original = (HTMLElement.prototype as unknown as { requestFullscreen?: unknown }).requestFullscreen;
    (HTMLElement.prototype as unknown as { requestFullscreen: unknown }).requestFullscreen = request;
    try {
      render(<CharacterRelationshipGraph roles={[{ name: '陆昭', position: '男主角' }]} relationships={[]} />);
      fireEvent.doubleClick(document.querySelector('.writer-relationship-canvas') as HTMLElement);
      expect(request).toHaveBeenCalledTimes(1);
      // The field fills the window at once, whether or not the browser grants real full screen.
      expect(document.querySelector('.writer-relationship-canvas')?.classList.contains('is-fullscreen')).toBe(true);
    } finally {
      (HTMLElement.prototype as unknown as { requestFullscreen?: unknown }).requestFullscreen = original;
    }
  });
});

describe('WriterAgentPage ledger links', () => {
  it('opens the episode screenplay dialog when the ledger asks for an episode', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/screenwriting/ledger')) return { ok: true, status: 200, json: async () => ({
        task_id: 't1', source_length: 0, layout_revision: 'r', candidate: null, unsplit: [],
        entries: [{ episode: 2, title: '杂役判仙案', hook: '', origin: 'none', source_range: null, units: 0, units_noun: '字', opening: '', closing: '', written: true, ledger_status: 'written' }],
      }) } as Response;
      if (url.endsWith('/screenwriting')) return { ok: true, status: 200, json: async () => ({
        taskId: 't1', available: true, sourceKind: 'outline', stale: false, title: '九霄殿', episodeCount: 2,
        durations: { supported: [4, 8], default: null, episodeTargetSeconds: null, videoModel: '' },
        overview: {}, inventory: {}, ledger: [], episodes: [], warnings: [], reviewSummary: null,
      }) } as Response;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    const user = userEvent.setup();
    render(<WriterAgentPage
      title="九霄殿"
      taskId="t1"
      breakdown={{ scenes: [], timeline: [], roles: [], relationships: [] }}
      script={'第1集 布鞋踩上玉阶\n殿内编钟齐鸣。\n\n第2集 杂役判仙案\n陆昭被按上帝座。'}
    />);
    await user.click(screen.getByRole('button', { name: '分集规划' }));
    await user.click(await screen.findByRole('button', { name: '查看第 2 集完整剧本' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('陆昭被按上帝座。');
    expect(dialog.textContent).not.toContain('殿内编钟齐鸣。');
  });
});

describe('WriterAgentPageContainer board callbacks', () => {
  function dashboard(extra: Record<string, unknown> = {}) {
    return {
      schemaVersion: 'writer-dashboard.v1', taskId: 'task-9', sourceHash: 'a'.repeat(64), title: '僰人悬棺', state: 'READY',
      overview: { title: '僰人悬棺', synopsis: '梗概。', genre: '历史', theme: '传承', worldSetting: '珙县' },
      stats: { totalEpisodes: 1, scriptedEpisodes: 1, missingEpisodes: [], sceneCount: 1, characterCount: 1, mainEventCount: 1, relationshipCount: 0, totalDurationSeconds: 4, tone: '历史' },
      scenes: [{ sceneId: 'E1S01', episodeIndex: 1, sceneIndex: 1, startSeconds: 0, durationSeconds: 4, durationLabel: '4s', durationEstimated: false, content: '雾', label: '清晨群山', description: '雾', dialogue: [], imageUrl: null, characters: ['哈大王'], keyEventIndex: null }],
      timeline: [{ eventId: 'event-001', order: 1, phase: '故事开始', title: '受封', desc: '', points: [], sceneId: 'E1S01', startSeconds: 0 }],
      roles: [{ name: '哈大王', position: '男主角' }], relationships: [], relationshipsInferred: true, timelineAuthored: false, creationMode: 'narration',
      versions: [], portraits: { 哈大王: 'https://img.example/king.jpg' }, episodes: [{ index: 1, title: '第 1 集', sceneCount: 1, durationSeconds: 4, issues: [], status: 'idle', videoUrl: null }],
      script: '第1集 开端\n雾', scriptFileName: null, ...extra,
    };
  }

  it('sends timeline, overview and version edits to the writer API and shows the portraits the dashboard carries', async () => {
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method || 'GET';
      if (method !== 'GET') calls.push({ url: url.split('/api/drama/task-9')[1], method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith('/writer-dashboard')) return { ok: true, status: 200, json: async () => dashboard() } as Response;
      if (url.endsWith('/timeline')) return { ok: true, status: 200, json: async () => dashboard({ timelineAuthored: true, timeline: [{ eventId: 'event-001', order: 1, phase: '进展纠葛', title: '悬棺', desc: '', points: [], sceneId: null, startSeconds: 0 }] }) } as Response;
      if (url.endsWith('/roles') || url.endsWith('/overview') || url.endsWith('/script/versions')) return { ok: true, status: 200, json: async () => dashboard({ versions: [{ versionId: 'v1', label: '初稿', createdAt: '2026-10-15T08:00:00+00:00', sourceHash: 'a'.repeat(64), episodeCount: 1, sceneCount: 1 }] }) } as Response;
      if (url.includes('/script-documents')) return { ok: true, status: 200, json: async () => ({ documents: [] }) } as Response;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    const user = userEvent.setup();
    render(<WriterAgentPageContainer taskId="task-9" episodes={[]} episodesBusy={false} onPlanEpisodes={() => undefined} onProduceEpisode={() => undefined} />);

    expect(await screen.findByText('旁白模式')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '删除节点 受封' }));
    await waitFor(() => expect(calls.some(call => call.url === '/timeline' && call.method === 'PUT')).toBe(true));
    expect(calls.find(call => call.url === '/timeline')?.body).toEqual({ events: [] });
    expect(await screen.findByText(/已手动编排/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '人物关系' }));
    await waitFor(() => expect(document.querySelector('[data-node-name="哈大王"] image')?.getAttribute('href')).toBe('https://img.example/king.jpg'));

    await user.click(screen.getByRole('button', { name: '创作看板' }));
    await user.click(screen.getByRole('button', { name: /^版本/ }));
    await user.click(screen.getByRole('button', { name: '保存当前版本' }));
    await waitFor(() => expect(calls.some(call => call.url === '/script/versions' && call.method === 'POST')).toBe(true));
    expect(await screen.findByText('初稿')).toBeTruthy();
  });
});
