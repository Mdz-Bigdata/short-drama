// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ModelConfigurationCenter } from './ModelConfigurationCenter';


const providers = {
  items: [
    { category: 'text', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'image', providers: [{ id: 'openai', label: 'OpenAI', default_base_url: 'https://api.openai.com/v1' }] },
    { category: 'video', providers: [{ id: 'minimax', label: 'MiniMax H3', default_base_url: 'https://api.minimaxi.com' }] },
    { category: 'audio', providers: [{ id: 'elevenlabs', label: 'ElevenLabs', default_base_url: 'https://api.elevenlabs.io' }] },
  ],
};


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
      if (url.includes('/models/entry-1')) return { ok: true, json: async () => ({ enabled: false }) } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    const onSelect = vi.fn();
    render(<ModelConfigurationCenter open role="admin" onClose={() => undefined} onSelect={onSelect} />);

    expect(await screen.findByRole('heading', { name: '模型配置' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /文本模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /图像模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /视频模型/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /音频模型/ })).toBeTruthy();

    await userEvent.selectOptions(screen.getByLabelText('AI 供应商'), 'openai');
    await userEvent.type(screen.getByLabelText('API 密钥'), 'api-key-from-form');
    await userEvent.click(screen.getByRole('button', { name: '加载模型' }));
    expect(await screen.findByRole('option', { name: /Remote Omni/ })).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('模型名称'), 'remote-omni');
    await userEvent.click(screen.getByRole('button', { name: '连接测试' }));
    expect(await screen.findByText('连接成功')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '保存配置' }));
    expect(await screen.findByText('已保存模型')).toBeTruthy();
    await userEvent.click(screen.getByRole('switch', { name: /Remote Omni/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/models/entry-1'), expect.objectContaining({ method: 'PATCH' }),
    ));
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
});
