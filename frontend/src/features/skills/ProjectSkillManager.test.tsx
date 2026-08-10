// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProjectSkillManager } from './ProjectSkillManager';


const skill = {
  id: 'skill-1', name: '细腻表演', slug: 'nuanced-acting', description: '微表情',
  markdown_content: '# 表演\n停顿后再回答。', source_type: 'created', command: '/skill.nuanced-acting',
  content_sha256: 'a'.repeat(64), version: 1, enabled: true,
  created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
};


describe('ProjectSkillManager', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('creates, edits, toggles, uploads and imports project Markdown Skills', async () => {
    let items = [skill];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/project-skills') && (!init || !init.method)) {
        return { ok: true, json: async () => ({ items, total: items.length, enabled_count: items.filter(item => item.enabled).length }) } as Response;
      }
      if (url.endsWith('/api/project-skills') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        const created = { ...skill, id: 'skill-2', ...body, command: `/skill.${body.slug}` };
        items = [...items, created];
        return { ok: true, json: async () => created } as Response;
      }
      if (url.endsWith('/skill-1') && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body));
        items = items.map(item => item.id === 'skill-1' ? { ...item, ...body, version: 2 } : item);
        return { ok: true, json: async () => items[0] } as Response;
      }
      if (url.endsWith('/skill-1/enabled')) {
        items = items.map(item => item.id === 'skill-1' ? { ...item, enabled: false } : item);
        return { ok: true, json: async () => items[0] } as Response;
      }
      if (url.endsWith('/upload') || url.endsWith('/import')) {
        return { ok: true, json: async () => ({ ...skill, id: url.endsWith('/upload') ? 'uploaded' : 'imported' }) } as Response;
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ProjectSkillManager open role="admin" onClose={() => undefined} />);
    expect(await screen.findByRole('heading', { name: '项目 Skill 管理' })).toBeTruthy();
    expect(screen.getByText('/skill.nuanced-acting')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: '新增 Skill' }));
    await userEvent.type(screen.getByLabelText('Skill 名称'), '运镜连贯性');
    await userEvent.type(screen.getByLabelText('命令标识'), 'camera-continuity');
    await userEvent.type(screen.getByLabelText('Markdown 指令'), '# 运镜\n保持运动方向。');
    await userEvent.click(screen.getByRole('button', { name: '保存 Skill' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/project-skills$/), expect.objectContaining({ method: 'POST' }),
    ));

    await userEvent.click(screen.getByRole('button', { name: /编辑细腻表演/ }));
    const description = screen.getByLabelText('Skill 描述');
    await userEvent.clear(description);
    await userEvent.type(description, '控制情绪节拍');
    await userEvent.click(screen.getByRole('button', { name: '保存 Skill' }));
    await userEvent.click(screen.getByRole('switch', { name: /启用细腻表演/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/skill-1/enabled'), expect.objectContaining({ method: 'PATCH' }),
    ));

    const mdInput = screen.getByLabelText('选择 Markdown 文件') as HTMLInputElement;
    await userEvent.upload(mdInput, new File(['# Upload'], 'uploaded.md', { type: 'text/markdown' }));
    const zipInput = screen.getByLabelText('选择 Skill 包文件') as HTMLInputElement;
    await userEvent.upload(zipInput, new File(['zip'], 'bundle.zip', { type: 'application/zip' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/import'), expect.objectContaining({ method: 'POST' }),
    ));
  });

  it('cancels an unsaved Markdown edit without sending it', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ items: [skill], total: 1, enabled_count: 1 }),
    } as Response);
    render(<ProjectSkillManager open role="admin" onClose={() => undefined} />);
    await screen.findByText('/skill.nuanced-acting');
    await userEvent.click(screen.getByRole('button', { name: '新增 Skill' }));
    await userEvent.type(screen.getByLabelText('Markdown 指令'), 'UNSAVED-SKILL-CONTENT');
    await userEvent.click(screen.getByRole('button', { name: '取消编辑' }));
    expect(screen.queryByDisplayValue('UNSAVED-SKILL-CONTENT')).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
