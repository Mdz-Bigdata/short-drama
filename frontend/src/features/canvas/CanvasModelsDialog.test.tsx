// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ProjectModels } from './canvasFilmApi';
import { CanvasModelsDialog } from './CanvasModelsDialog';

const api = vi.hoisted(() => ({ fetchProjectModels: vi.fn(), saveProjectModels: vi.fn() }));
vi.mock('./canvasFilmApi', async importOriginal => ({ ...await importOriginal<typeof import('./canvasFilmApi')>(), ...api }));

const VIEW: ProjectModels = {
  models: {
    text: { chosen: '', effective: 'deepseek-flash', choices: ['deepseek-flash', 'deepseek-v4-pro'] },
    image: { chosen: 'seedream', effective: 'seedream', choices: ['seedream', 'doubao-seedream-5-0-pro'] },
    video: { chosen: 'seedance-2-5', effective: 'seedance-2-5', choices: ['seedance-2-5', 'minimax-h3'] },
    audio: { chosen: '', effective: 'local-tts', choices: [] },
  },
  extras: { music: false, sfx: false },
  running: false,
};

afterEach(() => {
  cleanup();
  api.fetchProjectModels.mockReset();
  api.saveProjectModels.mockReset();
});

describe('the project models from the canvas', () => {
  it('shows the four models and sends only what changed', async () => {
    api.fetchProjectModels.mockResolvedValue(VIEW);
    api.saveProjectModels.mockResolvedValue({ ...VIEW, models: { ...VIEW.models, text: { ...VIEW.models.text, chosen: 'deepseek-v4-pro' } } });
    const onSaved = vi.fn();
    render(<CanvasModelsDialog projectId="p" onSaved={onSaved} onClose={vi.fn()} />);
    const text = await screen.findByLabelText('文本模型') as HTMLSelectElement;
    expect(text.value).toBe('');
    expect(screen.getByRole('option', { name: '模型配置中心默认（deepseek-flash）' })).toBeTruthy();
    expect((screen.getByLabelText('视频模型') as HTMLSelectElement).value).toBe('seedance-2-5');
    expect(screen.getByText(/配乐和音效要用 ElevenLabs/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(text, { target: { value: 'deepseek-v4-pro' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await screen.findByText('已保存，之后运行的节点用新模型。');
    expect(api.saveProjectModels).toHaveBeenCalledWith('p', { text: 'deepseek-v4-pro' });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('says why a choice was refused and keeps the dialog open', async () => {
    api.fetchProjectModels.mockResolvedValue(VIEW);
    api.saveProjectModels.mockRejectedValue(new Error('图像模型 x 没有在模型配置中心启用'));
    const onSaved = vi.fn();
    render(<CanvasModelsDialog projectId="p" onSaved={onSaved} onClose={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText('图像模型'), { target: { value: 'doubao-seedream-5-0-pro' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await screen.findByText('图像模型 x 没有在模型配置中心启用');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('changes nothing while a stage is running', async () => {
    api.fetchProjectModels.mockResolvedValue({ ...VIEW, running: true });
    render(<CanvasModelsDialog projectId="p" onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('流水线正在执行某一步，等它结束再换模型。')).toBeTruthy());
    expect((screen.getByLabelText('文本模型') as HTMLSelectElement).disabled).toBe(true);
  });
});
