// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ModelConfigurationCenter } from './ModelConfigurationCenter';


const providers = {
  items: [
    { category: 'text', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'image', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'video', providers: [
      { id: 'minimax', label: 'minimax', default_base_url: 'https://api.minimaxi.com' },
      { id: 'kling', label: 'Kling', default_base_url: 'https://api-singapore.klingai.com', key_hint: '填写 ACCESS_KEY:SECRET_KEY（冒号分隔）' },
    ] },
    { category: 'audio', providers: [
      { id: 'elevenlabs', label: 'ElevenLabs', default_base_url: 'https://api.elevenlabs.io' },
      { id: 'minimax', label: 'minimax', default_base_url: 'https://api.minimaxi.com' },
    ] },
  ],
};

const elevenCapabilityLabels = [
  '文本转语音', '语音转文字', '音乐', '语音引擎', '声音库', '文本转对话', '变声器',
  '声音设计', '音效', '语音隔离器', '配音', '强制对齐', '发音词典', 'Audio Native',
];

const elevenCapabilityModels: Record<string, string[]> = {
  变声器: ['eleven_multilingual_sts_v2'],
  声音设计: ['eleven_ttv_v3'],
};

const elevenCapabilities = elevenCapabilityLabels.map((label, index) => ({
  id: `ability-${index}`,
  label,
  label_en: label,
  kind: index < 9 ? 'model_backed' : 'service',
  model_ids: elevenCapabilityModels[label] ?? [],
  provider_endpoints: [`/v1/ability-${index}`],
  project_entrypoints: [`/api/production/audio/ability-${index}`],
  description: `${label}能力`,
}));


describe('ModelConfigurationCenter', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('discovers models dynamically, tests, saves, cancels and toggles a saved model', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      if (url.endsWith('/api/model-configurations') && (!init || init.method === undefined)) {
        return { ok: true, json: async () => ({ items: [], summary: { text: 0, image: 0, video: 0, audio: 0 } }) } as Response;
      }
      if (url.endsWith('/discover')) return { ok: true, json: async () => ({
        items: [{ model_id: 'remote-omni', display_name: 'Remote Omni', description: '视觉理解', category: 'text', subcategory: null, capabilities: ['text', 'multimodal'] }],
        total: 1,
      }) } as Response;
      if (url.endsWith('/test')) return { ok: true, json: async () => ({ connected: true, message: '连接成功' }) } as Response;
      if (url.endsWith('/api/model-configurations') && init?.method === 'POST') return { ok: true, json: async () => ({
        id: 'cfg-1', category: 'text', provider: 'openai', provider_label: 'OpenAI',
        base_url: 'https://api.openai.com/v1', has_api_key: true, key_hint: '****form', enabled: true,
        models: [{ id: 'entry-1', model_id: 'remote-omni', display_name: 'Remote Omni', description: '视觉理解', category: 'text', subcategory: null, capabilities: ['text', 'multimodal'], enabled: true }],
      }) } as Response;
      if (url.includes('/models/entry-1') && init?.method === 'PATCH') return { ok: true, json: async () => ({ enabled: false }) } as Response;
      if (url.includes('/models/entry-1') && init?.method === 'DELETE') return { ok: true, json: async () => ({
        entry_id: 'entry-1', model_id: 'remote-omni', category: 'text', was_enabled: false, configuration_deleted: true,
      }) } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    const onSelect = vi.fn();
    const onConfigurationChange = vi.fn();
    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} onSelect={onSelect} onConfigurationChange={onConfigurationChange} />);

    expect(await screen.findByRole('heading', { name: '模型配置' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /文本模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /图像模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /视频模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /音频模型/ })).toBeTruthy();

    await userEvent.click(screen.getByRole('tab', { name: /视频模型/ }));
    expect(await screen.findByRole('option', { name: 'minimax' })).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: /文本模型/ }));

    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'openai');
    await userEvent.type(screen.getByLabelText('API 密钥'), 'api-key-from-form');
    await userEvent.click(screen.getByRole('button', { name: '加载模型' }));
    const discovered = await screen.findByRole('checkbox', { name: /Remote Omni · 多模态/ });
    await userEvent.click(discovered);
    await userEvent.click(screen.getByRole('button', { name: '连接测试' }));
    expect(await screen.findByText('连接成功')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '保存配置' }));
    expect(await screen.findByText('已保存模型')).toBeTruthy();
    expect(onConfigurationChange).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('switch', { name: /Remote Omni/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/models/entry-1'), expect.objectContaining({ method: 'PATCH' }),
    ));
    expect(onConfigurationChange).toHaveBeenCalledTimes(2);
    await userEvent.click(screen.getByRole('button', { name: 'Remote Omni 删除保存' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/models/entry-1'), expect.objectContaining({ method: 'DELETE' }),
    ));
    expect(screen.queryByRole('button', { name: 'Remote Omni 删除保存' })).toBeNull();
    expect(onConfigurationChange).toHaveBeenCalledTimes(3);
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('manages credential pools, declared video endpoints and shows the ComfyUI status, with no text tiers', async () => {
    const configuration = {
      id: 'cfg-1', category: 'text', provider: 'openai', provider_label: 'OpenAI',
      base_url: 'https://api.openai.com/v1', has_api_key: true, key_hint: '****main', enabled: true,
      models: [{ id: 'entry-1', model_id: 'writer-pro', display_name: 'Writer Pro', description: '', category: 'text', subcategory: null, capabilities: ['text'], enabled: true }],
      credentials: [] as Array<Record<string, unknown>>,
    };
    const settings = {
      video_endpoints: [{ family: 'acme_video', label: 'Acme', base_url: 'https://video.acme.test', model_ids: ['acme-v1'], modes: ['text'], has_api_key: true, key_hint: '****key', enabled: true, ready: true, spec: {} }],
      video_endpoint_placeholders: ['prompt', 'first_frame'],
      comfyui: { family: 'comfyui', label: 'ComfyUI（自托管工作流）', configured: false, workflow: 'missing', ready: false, problems: ['未提供工作流'], how_to: '导出工作流后设置环境变量' },
    };
    const posts: Array<{ url: string; method?: string; body?: unknown }> = [];
    const market = {
      sources: [{ id: 'src1', key: 'github:acme/market@main', kind: 'github', url: 'https://raw.githubusercontent.com/acme/market/main/market-index.json', label: 'Acme', official: false, enabled: true, fetched_at: null, error: '', entry_count: 1, index_name: 'Acme 市场' }],
      entries: [{ slug: 'acme-video', name: 'Acme 视频端点', version: '1.1.0', kind: 'video_endpoint', summary: '一个声明式视频供应商', author: 'acme', tags: [], source_id: 'src1', source_key: 'github:acme/market@main', source_label: 'Acme', installed: false, installed_family: null, installed_version: null, market_status: null, modified: false }],
      installed: [{ family: 'acme_video', source_id: 'src1', source_label: 'Acme', slug: 'acme-video', name: 'Acme 视频端点', version: '1.0.0', available_version: '1.1.0', market_status: 'update_available', modified: true, endpoint_present: true }],
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/api/market/')) {
        if (init?.method && init.method !== 'GET') {
          posts.push({ url: url.split('/api')[1], method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined });
          return { ok: true, json: async () => ({ updated: false, record: {}, endpoint: {} }) } as Response;
        }
        if (url.endsWith('/api/market/sources')) return { ok: true, json: async () => ({ items: market.sources }) } as Response;
        if (url.endsWith('/api/market/entries')) return { ok: true, json: async () => ({ items: market.entries }) } as Response;
        if (url.endsWith('/api/market/installed')) return { ok: true, json: async () => ({ items: market.installed }) } as Response;
      }
      if (init?.method && init.method !== 'GET') {
        posts.push({ url: url.split('/api/model-configurations')[1], method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined });
        if (url.includes('/credentials') && init.method === 'POST') {
          configuration.credentials = [{ id: 'cred-2', label: '备用', key_hint: '****0002', buckets: ['text'], enabled: true, uses: 0 }];
          return { ok: true, json: async () => configuration.credentials[0] } as Response;
        }
        if (url.includes('/credentials/cred-2') && init.method === 'DELETE') {
          configuration.credentials = [];
          return { ok: true, json: async () => ({ deleted: true }) } as Response;
        }
        if (url.includes('/settings/video-endpoints/')) return { ok: true, json: async () => ({ family: 'my_video', ready: true }) } as Response;
      }
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      if (url.endsWith('/api/model-configurations')) {
        return { ok: true, json: async () => ({ items: [configuration], summary: { text: 1, image: 0, video: 0, audio: 0 }, settings }) } as Response;
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);

    const pool = await screen.findByRole('region', { name: 'OpenAI 备用凭据' });
    await userEvent.click(within(pool).getByRole('button', { name: '添加备用 Key' }));
    await userEvent.type(within(pool).getByLabelText('备用凭据名称'), '备用');
    await userEvent.type(within(pool).getByLabelText('备用 API 密钥'), 'second-key-0002');
    await userEvent.click(within(pool).getByRole('checkbox', { name: '文本' }));
    await userEvent.click(within(pool).getByRole('button', { name: '保存备用 Key' }));
    expect(await within(pool).findByText('****0002')).toBeTruthy();
    expect(posts[0]).toEqual({ url: '/cfg-1/credentials', method: 'POST', body: { label: '备用', api_key: 'second-key-0002', buckets: ['text'] } });
    await userEvent.click(within(pool).getByRole('button', { name: '删除备用凭据 备用' }));
    await waitFor(() => expect(within(pool).queryByText('****0002')).toBeNull());

    // Every text call uses the model selected here; there is no per-tier override any more.
    expect(screen.queryByRole('region', { name: '文本分档' })).toBeNull();
    expect(screen.queryByLabelText('快速档模型')).toBeNull();

    await userEvent.click(screen.getByRole('tab', { name: /视频模型/ }));
    const endpoints = await screen.findByRole('region', { name: '声明式视频端点' });
    expect(within(endpoints).getByText('acme_video')).toBeTruthy();
    expect(within(endpoints).getByText(/就绪/)).toBeTruthy();
    await userEvent.type(within(endpoints).getByLabelText('端点族标识'), 'my_video');
    await userEvent.type(within(endpoints).getByLabelText('端点 API 密钥'), 'my-secret-key');
    await userEvent.click(within(endpoints).getByRole('button', { name: '保存端点' }));
    await waitFor(() => expect(posts.some(post => post.url === '/settings/video-endpoints/my_video')).toBe(true));
    const endpointPost = posts.find(post => post.url === '/settings/video-endpoints/my_video')?.body as { api_key: string; spec: { submit: { body: { prompt: string } } } };
    expect(endpointPost.api_key).toBe('my-secret-key');
    expect(endpointPost.spec.submit.body.prompt).toBe('{{prompt}}');

    // The installed endpoint shows where it came from and both axes of its state.
    expect(within(endpoints).getByText(/来自市场 · 可更新 · 已修改/)).toBeTruthy();

    const marketRegion = await screen.findByRole('region', { name: '市场' });
    expect(within(marketRegion).getByText('github:acme/market@main')).toBeTruthy();
    expect(within(marketRegion).getByText('1 个条目')).toBeTruthy();
    expect(within(marketRegion).getByText('acme-video@1.1.0')).toBeTruthy();
    await userEvent.click(within(marketRegion).getByRole('button', { name: '安装 acme-video' }));
    expect(screen.getByText('首次安装需要提供这个供应商的 API Key')).toBeTruthy();
    expect(posts.some(post => post.url?.startsWith('/market/'))).toBe(false);
    await userEvent.type(within(marketRegion).getByLabelText('API Key acme-video'), 'acme-key-0001');
    await userEvent.click(within(marketRegion).getByRole('button', { name: '安装 acme-video' }));
    await waitFor(() => expect(posts.some(post => post.url === '/market/sources/src1/entries/acme-video/install')).toBe(true));
    expect(posts.find(post => post.url === '/market/sources/src1/entries/acme-video/install')?.body).toEqual({ api_key: 'acme-key-0001', overwrite: false, discard_local: false });
    await userEvent.type(within(marketRegion).getByLabelText('市场源地址'), 'https://github.com/other/market');
    await userEvent.click(within(marketRegion).getByRole('button', { name: '添加市场源' }));
    await waitFor(() => expect(posts.some(post => post.url === '/market/sources' && post.method === 'POST')).toBe(true));
    expect(posts.find(post => post.url === '/market/sources')?.body).toEqual({ url: 'https://github.com/other/market' });

    const comfy = screen.getByRole('region', { name: 'ComfyUI 状态' });
    expect(within(comfy).getByText(/未就绪：未提供工作流/)).toBeTruthy();
    expect(within(comfy).getByText('导出工作流后设置环境变量')).toBeTruthy();
  });

  it('clears an unsaved API key when the dialog is cancelled', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      return { ok: true, json: async () => ({ items: [], summary: { text: 0, image: 0, video: 0, audio: 0 } }) } as Response;
    });
    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);
    await userEvent.selectOptions(await screen.findByLabelText('AI 供应商'), 'openai');
    const secret = screen.getByLabelText('API 密钥') as HTMLInputElement;
    await userEvent.type(secret, 'unsaved-api-secret');

    await userEvent.click(screen.getByRole('button', { name: '取消' }));

    expect(secret.value).toBe('');
  });

  it('renders and counts every saved model when a category contains more than five', async () => {
    const savedModels = Array.from({ length: 8 }, (_, index) => ({
      id: `saved-entry-${index + 1}`,
      model_id: `saved-audio-model-${index + 1}`,
      display_name: `Saved Audio Model ${index + 1}`,
      description: '',
      category: 'audio',
      subcategory: 'tts',
      capabilities: ['audio', 'tts'],
      enabled: true,
    }));
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      return { ok: true, json: async () => ({
        items: [{
          id: 'cfg-unlimited', category: 'audio', provider: 'elevenlabs', provider_label: 'ElevenLabs',
          base_url: 'https://api.elevenlabs.io', has_api_key: true, key_hint: '****test', enabled: true,
          models: savedModels,
        }],
        summary: { text: 0, image: 0, video: 0, audio: 8 },
      }) } as Response;
    });

    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);
    await userEvent.click(await screen.findByRole('tab', { name: /音频模型/ }));

    expect(screen.getByLabelText('已保存模型数量').textContent).toBe('共 8 个 · 已启用 8 个');
    expect(screen.getAllByRole('button', { name: /删除保存/ })).toHaveLength(8);
    expect(screen.getByText('Saved Audio Model 8')).toBeTruthy();
    expect(screen.getByRole('button', { name: /音频模型8/ })).toBeTruthy();
  });

  it('renders ElevenLabs voice conversion and voice design models', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      if (url.endsWith('/discover')) return { ok: true, json: async () => ({
        items: [
          { model_id: 'eleven_multilingual_sts_v2', display_name: 'Multilingual STS v2', description: '', category: 'audio', subcategory: 'voice_conversion', capabilities: ['audio', 'voice_conversion'] },
          { model_id: 'eleven_ttv_v3', display_name: 'Text to Voice Design', description: '', category: 'audio', subcategory: 'voice_design', capabilities: ['audio', 'voice_design'] },
        ],
        total: 2,
        credential_verified: false,
        warnings: ['官方目录已加载；模型列表 scope 未授权，连接测试仍会严格验证。'],
        service_capabilities: elevenCapabilities,
      }) } as Response;
      if (url.endsWith('/api/model-configurations') && init?.method === 'POST') return { ok: true, json: async () => ({
        id: 'cfg-audio', category: 'audio', provider: 'elevenlabs', provider_label: 'ElevenLabs',
        base_url: 'https://api.elevenlabs.io', has_api_key: true, key_hint: '****form', enabled: true,
        models: [
          { id: 'entry-sts', model_id: 'eleven_multilingual_sts_v2', display_name: 'Multilingual STS v2', description: '', category: 'audio', subcategory: 'voice_conversion', capabilities: ['audio', 'voice_conversion'], enabled: true },
          { id: 'entry-ttv', model_id: 'eleven_ttv_v3', display_name: 'Text to Voice Design', description: '', category: 'audio', subcategory: 'voice_design', capabilities: ['audio', 'voice_design'], enabled: true },
        ],
      }) } as Response;
      return { ok: true, json: async () => ({ items: [], summary: { text: 0, image: 0, video: 0, audio: 0 } }) } as Response;
    });

    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);
    await userEvent.click(await screen.findByRole('tab', { name: /音频模型/ }));
    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'elevenlabs');
    await userEvent.type(screen.getByLabelText('API 密钥'), 'api-key-from-form');
    await userEvent.click(screen.getByRole('button', { name: '加载模型' }));

    expect(await screen.findByRole('checkbox', { name: /Multilingual STS v2 · 语音转换/ })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /Text to Voice Design · 声音设计/ })).toBeTruthy();
    expect(screen.getByText(/官方目录已加载/)).toBeTruthy();
    const capabilityPanel = screen.getByRole('region', { name: 'ElevenLabs 完整能力' });
    expect(within(capabilityPanel).getByText('14/14')).toBeTruthy();
    elevenCapabilityLabels.forEach(label => {
      expect(within(capabilityPanel).getByText(label)).toBeTruthy();
    });
    await userEvent.click(within(capabilityPanel).getByRole('button', { name: /变声器/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: /Multilingual STS v2/ }));
    await userEvent.click(within(capabilityPanel).getByRole('button', { name: /声音设计/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: /Text to Voice Design/ }));
    expect(screen.getByText('已选择 2 个模型')).toBeTruthy();

    await userEvent.click(within(capabilityPanel).getByRole('button', { name: /配音/ }));
    expect(screen.getByText(/这是独立服务，无需选择模型/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '保存配置' }));
    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([url, options]) => String(url).endsWith('/api/model-configurations') && options?.method === 'POST');
      expect(saveCall).toBeTruthy();
      expect(JSON.parse(String(saveCall?.[1]?.body)).selected_model_ids).toEqual([
        'eleven_multilingual_sts_v2', 'eleven_ttv_v3',
      ]);
    });
  });

  it('loads MiniMax speech, Music 3.0 and Music Cover as distinct audio capabilities', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      if (url.endsWith('/discover')) return { ok: true, json: async () => ({
        items: [
          { model_id: 'speech-2.8-hd', display_name: 'MiniMax Speech 2.8 HD', description: '', category: 'audio', subcategory: 'tts', capabilities: ['audio', 'tts'] },
          { model_id: 'music-3.0', display_name: 'MiniMax Music 3.0', description: '', category: 'audio', subcategory: 'music', capabilities: ['audio', 'music'] },
          { model_id: 'music-cover', display_name: 'MiniMax Music Cover', description: '', category: 'audio', subcategory: 'music_cover', capabilities: ['audio', 'music-cover'] },
        ],
        total: 3,
        credential_verified: true,
      }) } as Response;
      return { ok: true, json: async () => ({ items: [], summary: { text: 0, image: 0, video: 0, audio: 0 } }) } as Response;
    });

    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);
    await userEvent.click(await screen.findByRole('tab', { name: /音频模型/ }));
    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'minimax');
    expect((screen.getByLabelText('基础 URL') as HTMLInputElement).value).toBe('https://api.minimaxi.com');
    await userEvent.type(screen.getByLabelText('API 密钥'), 'api-key-from-form');
    await userEvent.click(screen.getByRole('button', { name: '加载模型' }));

    expect(await screen.findByRole('checkbox', { name: /MiniMax Speech 2.8 HD · TTS 配音/ })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /MiniMax Music 3.0 · 音乐/ })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /MiniMax Music Cover · 音乐翻唱/ })).toBeTruthy();
  });
  it('shows the provider key hint only for providers that declare one', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/providers')) return { ok: true, json: async () => providers } as Response;
      return { ok: true, json: async () => ({ items: [], summary: { text: 0, image: 0, video: 0, audio: 0 } }) } as Response;
    });

    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} />);
    await userEvent.click(await screen.findByRole('tab', { name: /视频模型/ }));
    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'kling');

    expect((screen.getByLabelText('基础 URL') as HTMLInputElement).value).toBe('https://api-singapore.klingai.com');
    expect(screen.getByTestId('provider-key-hint').textContent).toContain('ACCESS_KEY:SECRET_KEY');

    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'minimax');
    expect(screen.queryByTestId('provider-key-hint')).toBeNull();
  });

});
