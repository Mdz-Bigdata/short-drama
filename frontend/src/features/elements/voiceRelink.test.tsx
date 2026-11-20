// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '../../api/client';
import { VoicePanel } from './VoicePanel';
import { relinkQuestion, waitForRelink, type VoiceRelinkPreview } from './voiceRelink';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);
const view = {
  narration_delivery: 'use_tts',
  narrator: { voice_id: '', source: '', label: '', voice_prompt: '', take: null, rounds: [] },
  characters: [{ name: '林夏', voice_id: 'v-old', voice_prompt: '清亮女声', voice_desc: '清亮', take: null,
    rounds: [{ seed: 1, previews: [{ generated_voice_id: 'gen-2', url: '/media/b.mp3' }] }] }],
};
const preview = (patch: Partial<VoiceRelinkPreview> = {}): VoiceRelinkPreview => ({
  name: '林夏', lines: 12, episodes: [1, 2], native_shots: 3, billed: true, provider: 'elevenlabs', films_to_rerender: [1], ...patch,
});

function serve(answer: () => unknown) {
  mocked.mockImplementation(async (path: unknown) => {
    const url = String(path);
    if (url.startsWith('/api/production/audio/voices')) return { voices: [] };
    if (url.includes('/voice-relink-preview')) return answer() as never;
    return (url.endsWith('/voice/cast') ? {} : view) as never;
  });
}
const casts = () => mocked.mock.calls.filter(([url]) => String(url).endsWith('/characters/voice/cast'));

describe('changing a cast voice', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('says what the redub touches and costs, and waits for a yes', async () => {
    serve(() => preview());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    const asked = String(confirm.mock.calls[0][0]);
    expect(asked).toContain('第 1、2 集里的 12 句台词');
    expect(asked).toContain('会产生费用');
    expect(asked).toContain('3 个用原声的镜头会改成配音');
    expect(asked).toContain('第 1 集的成片要重新合成');
    expect(casts()).toHaveLength(0);
    expect(mocked).toHaveBeenCalledWith('/api/drama/t1/characters/%E6%9E%97%E5%A4%8F/voice-relink-preview?voice=gen-2');

    fireEvent.click(screen.getByRole('button', { name: '选这一版' }));
    await waitFor(() => expect(casts()).toHaveLength(1));
    expect(await screen.findByText(/已有成片需要重新合成/)).toBeTruthy();
  });

  it('refuses a voice another character already has', async () => {
    serve(() => preview({ taken_by: '周牧' }));
    const confirm = vi.spyOn(window, 'confirm');
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    expect(await screen.findByText('这个声音已经给了「周牧」，每个角色的声音要各不相同。')).toBeTruthy();
    expect(confirm).not.toHaveBeenCalled();
    expect(casts()).toHaveLength(0);
  });

  it('goes straight through on a backend that does not redub', async () => {
    serve(() => { throw new ApiError('Not Found', 404); });
    const confirm = vi.spyOn(window, 'confirm');
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    await waitFor(() => expect(casts()).toHaveLength(1));
    expect(confirm).not.toHaveBeenCalled();
  });

  it('reports a redub done on the spot', async () => {
    mocked.mockImplementation(async (path: unknown) => {
      const url = String(path);
      if (url.startsWith('/api/production/audio/voices')) return { voices: [] } as never;
      if (url.includes('/voice-relink-preview')) return preview({ billed: false, native_shots: 0 }) as never;
      if (url.endsWith('/voice/cast')) return { voiceRelink: { status: 'done', message: '已重配林夏的 12 句台词。' } } as never;
      return view as never;
    });
    render(<VoicePanel taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '选这一版' }));
    expect(await screen.findByText('已重配林夏的 12 句台词。')).toBeTruthy();
  });

  it('waits for a background redub to finish', async () => {
    const answers = [{ relink: { status: 'running' } }, { relink: { status: 'failed', error: '配音服务超时' } }];
    mocked.mockImplementation(async () => answers.shift() as never);
    const waits: number[] = [];
    const result = await waitForRelink('/api/drama/t1', '林夏', async ms => { waits.push(ms); });
    expect(result).toEqual({ status: 'failed', error: '配音服务超时' });
    expect(waits).toEqual([3000, 3000]);
  });

  it('does not ask when the redub is free and keeps every lip in sync', () => {
    expect(relinkQuestion(preview({ billed: false, native_shots: 0 }))).toBe('');
    expect(relinkQuestion(preview({ episodes: [0], films_to_rerender: [] }))).toContain('全片里的 12 句台词');
    expect(relinkQuestion(null)).toBe('');
  });
});
