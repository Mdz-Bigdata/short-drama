// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ModelConfigurationCenter } from './ModelConfigurationCenter';


const providers = {
  items: [
    { category: 'text', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'image', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'video', providers: [{ id: 'minimax', label: 'minimax', default_base_url: 'https://api.minimaxi.com' }] },
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
});
