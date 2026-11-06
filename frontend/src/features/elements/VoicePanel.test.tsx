// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '../../api/client';
import { VoicePanel } from './VoicePanel';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);
const LONG_PROMPT = '二十八岁女声，音色清亮微冷，语速偏快，干声，情绪中性，不带混响';

function view(overrides: Record<string, unknown> = {}) {
  return {
    narration_delivery: 'use_tts',
    narrator: { voice_id: '', source: '', label: '', voice_prompt: LONG_PROMPT, take: null, rounds: [] },
    characters: [
      { name: '林夏', voice_id: '', voice_prompt: LONG_PROMPT, voice_desc: '清亮', take: null,
        rounds: [{ seed: 1, previews: [{ generated_voice_id: 'gen-1', url: '/media/a.mp3' }] }] },
      { name: '周牧', voice_id: 'v-zhou', voice_prompt: '', voice_desc: '', take: null, rounds: [] },
    ],
    ...overrides,
  };
}

function serve(current: unknown) {
  mocked.mockImplementation(async (path: unknown) => {
    if (String(path).startsWith('/api/production/audio/voices')) return { voices: [{ voice_id: 'lib-1', name: 'Rachel' }] };
    return current as never;
  });
}

describe('VoicePanel', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('shows each character with a cast state and the latest takes', async () => {
    serve(view());
    render(<VoicePanel taskId="t1" />);
    expect(await screen.findByText('林夏')).toBeTruthy();
    expect(mocked).toHaveBeenCalledWith('/api/drama/t1/voices');
    expect(screen.getByText('未选角')).toBeTruthy();
    expect(screen.getByRole('button', { name: '选这一版' })).toBeTruthy();
    expect(screen.getByLabelText('试听第 1 版').getAttribute('src')).toContain('/media/a.mp3');
  });

  it('asks before a paid audition and sends the edited prompt', async () => {
    serve(view());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<VoicePanel taskId="t1" />);
    const prompt = await screen.findByLabelText('“林夏”的音色设计提示词');
    fireEvent.change(prompt, { target: { value: `${LONG_PROMPT}加一点` } });
    fireEvent.click(screen.getAllByRole('button', { name: '换一批试听' })[0]);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(mocked).not.toHaveBeenCalledWith('/api/drama/t1/characters/voice/audition', expect.anything());
    fireEvent.click(screen.getAllByRole('button', { name: '换一批试听' })[0]);
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/characters/voice/audition', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ name: '林夏', voice_prompt: `${LONG_PROMPT}加一点` }),
    })));
  });

  it('casts a take for a character', async () => {
    serve(view());
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/characters/voice/cast', expect.objectContaining({
      body: JSON.stringify({ name: '林夏', generated_voice_id: 'gen-1' }),
    })));
    expect((await screen.findByRole('status')).textContent).toContain('林夏');
  });

  it('holds back auditions until a character has a usable prompt', async () => {
    serve(view());
    render(<VoicePanel taskId="t1" />);
    const prompt = await screen.findByLabelText('“周牧”的音色设计提示词');
    expect(screen.getByText('提示词至少 20 字')).toBeTruthy();
    expect(prompt.closest('li')?.querySelector('button[disabled]')).toBeTruthy();
  });

  it('picks a narrator from cast voices and the account library, and can go back to the default', async () => {
    serve(view());
    render(<VoicePanel taskId="t1" />);
    const select = await screen.findByLabelText('用已有声音') as HTMLSelectElement;
    await screen.findByRole('option', { name: 'Rachel' });
    expect([...select.options].map(option => option.textContent)).toEqual(['默认声音', '周牧', 'Rachel']);
    fireEvent.change(select, { target: { value: 'lib-1' } });
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/voices/narrator', expect.objectContaining({
      method: 'PUT', body: JSON.stringify({ voice_id: 'lib-1', label: 'Rachel' }),
    })));
    await screen.findByRole('status');
    fireEvent.change(select, { target: { value: '' } });
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/api/drama/t1/voices/narrator', { method: 'DELETE' }));
  });

  it('works without a provider key for the library, and says when narration goes to post', async () => {
    mocked.mockImplementation(async (path: unknown) => {
      if (String(path).startsWith('/api/production/audio/voices')) throw new ApiError('no key', 502);
      return view({ narration_delivery: 'post_production' }) as never;
    });
    render(<VoicePanel taskId="t1" />);
    expect(await screen.findByText('这个项目把旁白留给后期配音，这里定的声音不会用上。')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('reports a refused action', async () => {
    mocked.mockImplementation(async (path: unknown) => {
      if (String(path).endsWith('/cast')) throw new ApiError('任务正在执行阶段，等它结束后再定角色音色', 409);
      if (String(path).startsWith('/api/production/audio/voices')) return { voices: [] };
      return view() as never;
    });
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    expect((await screen.findByRole('alert')).textContent).toContain('正在执行');
  });
});
