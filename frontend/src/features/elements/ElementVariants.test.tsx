// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';
import { variantOf, type ElementItem } from './elementTypes';

function actor(id: string, name: string, metadata: Record<string, unknown> = {}): ElementItem {
  return { id, kind: 'actor', name, description: `${name}的造型`, status: 'draft', version: 1, metadata, files: [], model3d: null };
}

describe('derived looks and products in the element library', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('reads variant facts from metadata and ignores anything else', () => {
    expect(variantOf(actor('a', '少年林夏', { variant: { of: '林夏', label: '少年', triggers: ['少年'], episodes: [1, 2] } })))
      .toEqual({ of: '林夏', label: '少年', triggers: ['少年'], episodes: [1, 2] });
    expect(variantOf(actor('b', '林夏'))).toBeNull();
    expect(variantOf(actor('c', 'x', { variant: { of: '' } }))).toBeNull();
  });

  it('marks an actor as a derived look of another character, shows the badge and can clear it', async () => {
    let young = actor('a-young', '少年林夏');
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/variant')) {
        const body = init?.body ? JSON.parse(String(init.body)) : undefined;
        calls.push({ method: String(init?.method), url: url.split('/api/elements')[1], body });
        young = init?.method === 'DELETE'
          ? actor('a-young', '少年林夏')
          : actor('a-young', '少年林夏', { variant: { of: body.of, label: body.label, triggers: [body.label, '校服'], episodes: [body.episode_from, body.episode_to] } });
        return { ok: true, json: async () => young } as Response;
      }
      return { ok: true, json: async () => ({ items: [actor('a-base', '林夏'), young], page: 1, page_size: 24, total: 2 }) } as Response;
    });

    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);
    await userEvent.click(await screen.findByRole('button', { name: '把“少年林夏”设为衍生形象' }));
    const form = screen.getByRole('form', { name: '设置“少年林夏”的衍生形象' });
    const base = within(form).getByLabelText('来源角色');
    expect(within(base).getAllByRole('option').map(option => option.textContent)).toEqual(['选择角色', '林夏']);
    await userEvent.selectOptions(base, '林夏');
    await userEvent.type(within(form).getByLabelText('造型名'), '少年');
    await userEvent.type(within(form).getByLabelText('触发词'), '校服');
    await userEvent.type(within(form).getByLabelText('起始集'), '1');
    await userEvent.type(within(form).getByLabelText('结束集'), '2');
    await userEvent.click(within(form).getByRole('button', { name: '保存衍生形象' }));

    expect(await screen.findByText(/衍生自「林夏」 · 少年/)).toBeTruthy();
    expect(screen.getByText(/第 1–2 集/)).toBeTruthy();
    expect(calls[0]).toEqual({ method: 'PUT', url: '/a-young/variant', body: { of: '林夏', label: '少年', triggers: '校服', episode_from: 1, episode_to: 2 } });

    await userEvent.click(screen.getByRole('button', { name: '取消“少年林夏”的衍生形象' }));
    await waitFor(() => expect(screen.queryByText(/衍生自「林夏」/)).toBeNull());
    expect(calls[1]).toMatchObject({ method: 'DELETE', url: '/a-young/variant' });
  });

  it('has a product page whose assets are uploaded photos', async () => {
    const requested: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      requested.push(String(input));
      return { ok: true, json: async () => ({ items: [], page: 1, page_size: 24, total: 0 }) } as Response;
    });
    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);
    await userEvent.click(await screen.findByRole('tab', { name: '商品' }));
    expect(await screen.findByRole('heading', { name: /商品元素库/ })).toBeTruthy();
    expect(screen.getByText(/上传实物照片/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加商品' })).toBeTruthy();
    expect(requested.some(url => url.includes('kind=product'))).toBe(true);
  });
});
