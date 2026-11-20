// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterStudio } from './CharacterStudio';

const catalog = {
  layers: [
    { key: 'bone', label: '骨相' }, { key: 'features', label: '五官' }, { key: 'skin', label: '皮肤' },
    { key: 'hair', label: '毛发' }, { key: 'physique', label: '体态' },
  ],
  controls: [
    { key: 'face_shape', layer: 'bone', label: '脸型', type: 'choice', options: [{ value: 'melon', label: '瓜子脸' }, { value: 'oval', label: '鹅蛋脸' }] },
    { key: 'eye_size', layer: 'features', label: '眼睛大小', type: 'scale', steps: ['眼睛偏小', '眼睛略小', '', '眼睛略大', '眼睛大而明亮'] },
    { key: 'skin_tone', layer: 'skin', label: '肤色', type: 'choice', options: [{ value: 'wheat', label: '小麦' }] },
    { key: 'skin_smooth', layer: 'skin', label: '质感磨皮', type: 'level', steps: ['', '轻度磨皮', '磨皮柔滑', '光洁如瓷'] },
    { key: 'skin_clear', layer: 'skin', label: '祛斑祛痘', type: 'level', steps: ['', '无斑无痘'] },
    {
      key: 'hairstyle', layer: 'hair', label: '发型', type: 'choice', options: [
        { value: 'buzz', label: '寸头', group: '现代' }, { value: 'bob', label: '波波头', group: '现代' },
        { value: 'forehead_band', label: '抹额长发', group: '仙侠' },
      ],
    },
    { key: 'hair_color', layer: 'hair', label: '发色', type: 'choice', options: [{ value: 'black', label: '乌黑', swatch: '#000' }, { value: 'wine', label: '酒红', swatch: '#6a1b2b' }] },
    { key: 'slim', layer: 'physique', label: '胖瘦', type: 'scale', steps: ['偏胖', '略丰', '', '略瘦', '纤瘦'] },
  ],
  presets: [
    { key: 'heroine_cool', label: '古装女主·清冷', values: { face_shape: 'melon', eye_size: 1 } },
    { key: 'look_soft', label: '五官·柔和杏眼', values: { face_shape: 'oval', eye_size: 1 }, scope: ['bone', 'features'], focus: 'eye_size' },
  ],
  focus_layers: ['bone', 'features'],
  expression_controls: [{ key: 'eyes', label: '眼', options: [{ value: 'crescent', label: '弯成月牙' }] }],
  expressions: [{ key: 'smile', label: '笑', words: ['笑'] }, { key: 'cry', label: '哭', words: ['哭'] }],
  limits: { note_chars: 60, tell_chars: 40, habit_chars: 40 },
  marks: {
    limit: 8, text_chars: 20,
    kinds: [
      { key: 'mole', label: '痣', region: true, text: false },
      { key: 'freckles_full', label: '全脸雀斑', region: false, text: false },
      { key: 'tattoo', label: '纹身', region: true, text: true },
    ],
    regions: [
      { key: 'left_cheek', label: '左颊', area: 'face', x: 0.7, y: 0.6 },
      { key: 'right_arm', label: '右臂', area: 'body', x: 0.3, y: 0.4 },
    ],
  },
  studio: {
    panels: [
      { key: 'retouch', label: '脸部精修', sections: [
        { key: 'skin', label: '皮肤', controls: ['skin_smooth', 'skin_clear', 'skin_tone'] },
        { key: 'shape', label: '脸型', presets: true, controls: ['face_shape', 'eye_size'] },
      ] },
      { key: 'marks', label: '脸部 & 身体特征', marks: true },
      { key: 'body', label: '身材塑形', sections: [{ key: 'body', label: '身材', controls: ['slim'] }] },
      { key: 'style', label: '服装造型', sections: [{ key: 'hair', label: '造型', controls: ['hairstyle', 'hair_color'] }] },
      { key: 'voice', label: '音色音调', voice: true },
      { key: 'expression', label: '表情习惯', expression: true },
    ],
  },
};

const emptyPreview = {
  description: '女主角；鹅蛋脸', face_text: '骨相：鹅蛋脸', layers: {}, issues: [], expressions: {}, sheet_stale: false, stale_note: '',
};
const blank = { face: {}, notes: {}, expressions: {}, preset: '', focus: '', marks: [] };
const now = () => Date.now() / 1000;

type Call = { url: string; method: string; body?: Record<string, unknown> };

function mockApi(overrides: { history?: unknown[]; put?: Record<string, unknown>; canvas?: { status: number; body: unknown } } = {}) {
  const calls: Call[] = [];
  const history = overrides.history ?? [
    { id: 'snap0001', label: '手动保存', at: now() - 180, revision: 2 },
    { id: 'snap0000', label: '第一次捏脸之前', at: now() - 7200, revision: 0 },
  ];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const reply = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) }) as Response;
    if (url.endsWith('/api/face-sculpt/catalog')) return reply(catalog);
    if (url.endsWith('/preview')) {
      return reply({
        ...emptyPreview,
        face_text: '骨相：瓜子脸；五官：眼睛略大',
        layers: body?.face?.face_shape ? { bone: '瓜子脸' } : {},
        expressions: body?.expressions?.smile ? { smile: '林婉笑时：眼睛弯成月牙' } : {},
      });
    }
    if (url.endsWith('/instruct')) {
      return reply({ reply: '脸型改成瓜子脸', patch: {}, unknown: [], sculpt: { ...blank, face: { face_shape: 'melon' } }, preview: emptyPreview, saved: false, current: null });
    }
    if (url.endsWith('/revert')) {
      return reply({
        name: '林婉', sculpt: { ...blank, face: { face_shape: 'oval' } }, revision: 3, preview: emptyPreview,
        history: [{ id: 'snap0002', label: '回到之前', at: now() - 5, revision: 3 }, ...history],
      });
    }
    if (url.includes('/canvas/character')) return reply(overrides.canvas?.body ?? { added: true, node_id: 'n1' }, overrides.canvas?.status ?? 200);
    if (url.includes('/face-sculpt') && method === 'PUT') {
      return reply({
        name: '林婉', sculpt: body, revision: 4, history,
        preview: { ...emptyPreview, sheet_stale: true, stale_note: '脸已经改过，现有设定集和定妆图还是旧脸' },
        ...overrides.put,
      });
    }
    if (url.includes('/face-sculpt')) return reply({ name: '林婉', sculpt: blank, revision: 2, preview: emptyPreview, history });
    if (url.endsWith('/voices')) {
      return reply({ characters: [{ name: '林婉', voice_id: 'v-old', voice_prompt: '清冷女声', voice_desc: '', take: null, rounds: [] }] });
    }
    if (url.includes('/api/production/audio/voices')) {
      return reply({ voices: [
        { voice_id: 'v-old', name: '御姐音色', labels: { gender: 'female' }, preview_url: 'https://cdn.test/a.mp3' },
        { voice_id: 'v-new', name: '少女音色', labels: { gender: 'female', age: 'young' }, preview_url: 'https://cdn.test/b.mp3' },
        { voice_id: 'v-man', name: '霸道青年音色', labels: { gender: 'male' } },
      ] });
    }
    if (url.includes('/voice-relink-preview')) {
      return reply({ name: '林婉', lines: 0, episodes: [], native_shots: 0, billed: false, provider: '', films_to_rerender: [] });
    }
    if (url.includes('/voices/characters/')) return reply({ characters: [] });
    return reply({});
  });
  return calls;
}

const previews = (calls: Call[]) => calls.filter(call => call.url.endsWith('/preview'));
const saveButton = () => screen.getByRole('button', { name: '保存' }) as HTMLButtonElement;
const nav = (name: string) => userEvent.click(screen.getByRole('button', { name }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CharacterStudio', () => {
  it('lays out the panels the catalog names and opens on the first one', async () => {
    mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" role="女主角" />);
    const navigation = await screen.findByRole('navigation', { name: '造型分类' });
    expect(within(navigation).getAllByRole('button').map(button => button.textContent))
      .toEqual(['脸部精修', '脸部 & 身体特征', '身材塑形', '服装造型', '音色音调', '表情习惯']);
    expect(screen.getByText('女主角')).toBeTruthy();
    expect(screen.getByRole('tab', { name: '皮肤' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('slider', { name: '质感磨皮' })).toBeTruthy();
    expect(screen.getByRole('switch', { name: '祛斑祛痘' })).toBeTruthy();
  });

  it('previews a preset, saves it to the character and tells that the sheet is now stale', async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(<CharacterStudio taskId="t1" characterName="林婉" onSaved={onSaved} />);
    await userEvent.click(await screen.findByRole('tab', { name: '脸型' }));
    expect(saveButton().disabled).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: '古装女主·清冷' }));
    await waitFor(() => expect(previews(calls).length).toBe(1));
    expect(previews(calls)[0].url).toContain(`/characters/${encodeURIComponent('林婉')}/face-sculpt/preview`);
    expect(previews(calls)[0].body).toMatchObject({ face: { face_shape: 'melon', eye_size: 1 }, preset: 'heroine_cool' });
    expect(screen.getByText(/画面还是改动前的样子/)).toBeTruthy();

    await userEvent.click(saveButton());
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(calls.some(call => call.method === 'PUT')).toBe(true);
    expect(screen.getByText(/现有设定集和定妆图还是旧脸/)).toBeTruthy();
  });

  it('reports unsaved changes so the dialog around it can ask before closing', async () => {
    mockApi();
    const onDirtyChange = vi.fn();
    render(<CharacterStudio taskId="t1" characterName="林婉" onDirtyChange={onDirtyChange} />);
    await userEvent.click(await screen.findByRole('switch', { name: '祛斑祛痘' }));
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    await userEvent.click(saveButton());
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it('sliders send levels and scales; the middle of a scale and level 0 mean "leave it as written"', async () => {
    const calls = mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    const smooth = await screen.findByRole('slider', { name: '质感磨皮' });
    await userEvent.click(screen.getByRole('switch', { name: '祛斑祛痘' }));
    // jsdom 不会拖滑块：直接改值并发 input 事件。
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.change(smooth, { target: { value: '2' } });
    expect(screen.getByText('磨皮柔滑')).toBeTruthy();
    await nav('身材塑形');
    fireEvent.change(screen.getByRole('slider', { name: '胖瘦' }), { target: { value: '-1' } });
    await waitFor(() => expect(previews(calls).at(-1)?.body).toMatchObject({ face: { skin_smooth: 2, skin_clear: 1, slim: -1 } }));

    fireEvent.change(screen.getByRole('slider', { name: '胖瘦' }), { target: { value: '0' } });
    await nav('脸部精修');
    fireEvent.change(screen.getByRole('slider', { name: '质感磨皮' }), { target: { value: '0' } });
    await userEvent.click(screen.getByRole('switch', { name: '祛斑祛痘' }));
    expect(saveButton().disabled).toBe(true);
  });

  it('hairstyles are grouped by era and colours are swatches', async () => {
    const calls = mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await screen.findByRole('navigation', { name: '造型分类' });
    await nav('服装造型');
    expect(screen.getByRole('button', { name: '寸头' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '抹额长发' })).toBeNull();
    await userEvent.click(screen.getByRole('tab', { name: '仙侠' }));
    await userEvent.click(screen.getByRole('button', { name: '抹额长发' }));
    await userEvent.click(screen.getByRole('button', { name: '发色：酒红' }));
    await waitFor(() => expect(previews(calls).at(-1)?.body).toMatchObject({ face: { hairstyle: 'forehead_band', hair_color: 'wine' } }));
    expect(screen.getByRole('button', { name: '发色：酒红' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('places a mole on the face map, adds freckles with one click, and asks what a tattoo is', async () => {
    const calls = mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await screen.findByRole('navigation', { name: '造型分类' });
    await nav('脸部 & 身体特征');

    await userEvent.click(screen.getByRole('button', { name: '放在左颊' }));
    expect(screen.getByRole('alert').textContent).toContain('先在上面选一种特征');
    await userEvent.click(screen.getByRole('button', { name: '痣' }));
    await userEvent.click(screen.getByRole('button', { name: '放在左颊' }));
    await userEvent.click(screen.getByRole('button', { name: '全脸雀斑' }));

    await userEvent.click(screen.getByRole('tab', { name: '身体' }));
    await userEvent.click(screen.getByRole('button', { name: '纹身' }));
    await userEvent.click(screen.getByRole('button', { name: '放在右臂' }));
    expect(screen.getByRole('alert').textContent).toContain('先写上「纹身」是什么');
    await userEvent.type(screen.getByRole('textbox', { name: '纹身是什么' }), '青龙');
    await userEvent.click(screen.getByRole('button', { name: '放在右臂' }));

    const placed = screen.getByRole('list', { name: '已加的特征' });
    expect(within(placed).getAllByRole('listitem').map(item => item.textContent)).toEqual(['左颊 · 痣', '全脸雀斑', '右臂 · 纹身 · 青龙']);
    await waitFor(() => expect(previews(calls).at(-1)?.body?.marks).toEqual([
      { kind: 'mole', region: 'left_cheek', text: '' },
      { kind: 'freckles_full', region: '', text: '' },
      { kind: 'tattoo', region: 'right_arm', text: '青龙' },
    ]));
    await userEvent.click(screen.getByRole('button', { name: '去掉 全脸雀斑' }));
    expect(within(placed).getAllByRole('listitem')).toHaveLength(2);
  });

  it('undo and redo walk through the changes', async () => {
    mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    const toggle = await screen.findByRole('switch', { name: '祛斑祛痘' });
    const undo = screen.getByRole('button', { name: '撤销' }) as HTMLButtonElement;
    const redo = screen.getByRole('button', { name: '重做' }) as HTMLButtonElement;
    expect(undo.disabled).toBe(true);
    await userEvent.click(toggle);
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await userEvent.click(undo);
    expect(screen.getByRole('switch', { name: '祛斑祛痘' }).getAttribute('aria-checked')).toBe('false');
    expect(redo.disabled).toBe(false);
    await userEvent.click(redo);
    expect(screen.getByRole('switch', { name: '祛斑祛痘' }).getAttribute('aria-checked')).toBe('true');
  });

  it('确认生成 asks first, saves, then redraws the sheet', async () => {
    const calls = mockApi();
    const onGenerate = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<CharacterStudio taskId="t1" characterName="林婉" onGenerate={onGenerate} />);
    await userEvent.click(await screen.findByRole('switch', { name: '祛斑祛痘' }));

    await userEvent.click(screen.getByRole('button', { name: '确认生成' }));
    expect(confirm.mock.calls[0][0]).toContain('按次计费');
    expect(onGenerate).not.toHaveBeenCalled();
    expect(calls.some(call => call.method === 'PUT')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: '确认生成' }));
    await waitFor(() => expect(onGenerate).toHaveBeenCalledWith('林婉'));
    const put = calls.findIndex(call => call.method === 'PUT');
    expect(put).toBeGreaterThanOrEqual(0);
    expect(screen.getByText(/设定集正在后台重画/)).toBeTruthy();
  });

  it('保存并添加到画布 saves and puts the sheet on the canvas; a missing sheet is explained', async () => {
    const calls = mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await userEvent.click(await screen.findByRole('switch', { name: '祛斑祛痘' }));
    await userEvent.click(screen.getByRole('button', { name: '保存并添加到画布' }));
    await waitFor(() => expect(screen.getByText(/已把「林婉」的定妆设定集放到画布上/)).toBeTruthy());
    const canvas = calls.find(call => call.url.includes('/canvas/character'));
    expect(canvas?.url).toContain('/api/studio/tasks/t1/canvas/character');
    expect(canvas?.body).toEqual({ name: '林婉' });

    cleanup();
    vi.restoreAllMocks();
    mockApi({ canvas: { status: 409, body: { detail: '「林婉」还没有定妆设定集，先生成角色资产再添加到画布' } } });
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await screen.findByRole('navigation', { name: '造型分类' });
    await userEvent.click(screen.getByRole('button', { name: '保存并添加到画布' }));
    expect(await screen.findByText(/还没有定妆设定集/)).toBeTruthy();
  });

  it('sculpts one emotion and shows how that character will play it', async () => {
    mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await screen.findByRole('navigation', { name: '造型分类' });
    await nav('表情习惯');
    expect(screen.getByText('这个情绪还用通用写法')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '弯成月牙' }));
    await waitFor(() => expect(screen.getByText('林婉笑时：眼睛弯成月牙')).toBeTruthy());
    expect(screen.getByRole('option', { name: '笑' }).className).toContain('is-sculpted');
  });

  it('a features-only preset keeps the skin and brings its focal feature', async () => {
    const calls = mockApi();
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await screen.findByRole('navigation', { name: '造型分类' });
    // 肤色在皮肤页；预设在脸型页。
    await userEvent.click(screen.getByRole('button', { name: '小麦' }));
    await userEvent.click(screen.getByRole('tab', { name: '脸型' }));
    await userEvent.click(screen.getByRole('button', { name: '五官·柔和杏眼' }));
    const focus = screen.getByRole('combobox', { name: /突出点/ }) as HTMLSelectElement;
    expect(focus.value).toBe('eye_size');
    await waitFor(() => expect(previews(calls).at(-1)?.body).toMatchObject({
      face: { skin_tone: 'wheat', face_shape: 'oval', eye_size: 1 }, preset: 'look_soft', focus: 'eye_size',
    }));
  });

  it('turns a one-sentence instruction into unsaved changes', async () => {
    const calls = mockApi();
    const onDirtyChange = vi.fn();
    render(<CharacterStudio taskId="t1" characterName="林婉" onDirtyChange={onDirtyChange} />);
    await userEvent.click(await screen.findByRole('button', { name: '用一句话捏脸' }));
    await userEvent.type(screen.getByRole('textbox', { name: '用一句话捏' }), '脸改成瓜子脸');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    expect(calls.find(call => call.url.endsWith('/face-sculpt/instruct'))?.body).toEqual({ message: '脸改成瓜子脸', apply: false });
    await userEvent.click(screen.getByRole('tab', { name: '脸型' }));
    expect(screen.getByRole('button', { name: '瓜子脸' }).getAttribute('aria-pressed')).toBe('true');
    expect(calls.some(call => call.method === 'PUT')).toBe(false);
  });

  it('lists the edit history, goes back to a step, and not while there are unsaved changes', async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(<CharacterStudio taskId="t1" characterName="林婉" onSaved={onSaved} />);
    await userEvent.click(await screen.findByRole('button', { name: '修改记录' }));
    const list = screen.getByRole('region', { name: '修改记录' });
    expect(list.textContent).toContain('3 分钟前');
    expect(list.textContent).toContain('2 小时前');
    await userEvent.click(screen.getByRole('button', { name: '回到这一步：手动保存' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(calls.find(call => call.url.endsWith('/face-sculpt/revert'))?.body).toEqual({ snapshot_id: 'snap0001' });

    await userEvent.click(screen.getByRole('switch', { name: '祛斑祛痘' }));
    await userEvent.click(screen.getByRole('button', { name: '修改记录' }));
    const back = screen.getByRole('button', { name: '回到这一步：回到之前' }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
    expect(back.title).toBe('先保存或放弃未保存的改动');
  });

  it('tells what the save marked downstream', async () => {
    mockApi({ put: { downstream: { clips_marked: 3, sheet_stale: true }, library: { updated: true, element_id: 'e1' } } });
    render(<CharacterStudio taskId="t1" characterName="林婉" />);
    await userEvent.click(await screen.findByRole('switch', { name: '祛斑祛痘' }));
    await userEvent.click(saveButton());
    expect(await screen.findByText(/已保存。3 段视频需重跑第 5 阶段才会换上新脸/)).toBeTruthy();
    expect(screen.getByText(/元素库里的演员描述已同步/)).toBeTruthy();
  });

  it('gives the character a library voice after checking what a recast would re-dub', async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(<CharacterStudio taskId="t1" characterName="林婉" onSaved={onSaved} />);
    await screen.findByRole('navigation', { name: '造型分类' });
    await nav('音色音调');
    const list = await screen.findByRole('list', { name: '音色库' });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(3));
    await userEvent.click(screen.getByRole('button', { name: '男' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: '女' }));
    const rows = within(list).getAllByRole('listitem');
    expect(within(rows[0]).getByRole('button', { name: '当前' })).toBeTruthy();

    await userEvent.click(within(rows[1]).getByRole('button', { name: '使用' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(calls.find(call => call.url.includes('/voice-relink-preview'))?.url).toContain('voice=v-new');
    const put = calls.find(call => call.url.includes('/voices/characters/'));
    expect(put?.method).toBe('PUT');
    expect(put?.url).toContain(`/voices/characters/${encodeURIComponent('林婉')}`);
    expect(put?.body).toEqual({ voice_id: 'v-new', sample_url: 'https://cdn.test/b.mp3' });
  });
});
