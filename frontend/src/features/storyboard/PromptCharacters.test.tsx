// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PromptCharacters } from './PromptCharacters';

const characters = ['沈砚', '谢云遥', '贺兰霆', '太后萧氏'].map(name => ({
  name,
  appearance: `${name}的完整外貌描述。`.repeat(60),
  costume: `${name}本场服装的完整信息`,
}));

describe('PromptCharacters', () => {
  let resize: (width: number) => void;
  const disconnect = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) {
        resize = width => callback([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      observe() {}
      disconnect = disconnect;
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('shows complete character information one at a time on a narrow layout and pages through every character', async () => {
    const user = userEvent.setup();
    render(<PromptCharacters characters={characters} />);
    act(() => resize(280));

    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getByText(characters[0].appearance).textContent).toBe(characters[0].appearance);
    expect(screen.getByText('第 1 / 4 页 · 角色 1–1')).toBeTruthy();
    expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true);

    for (const character of characters.slice(1)) {
      await user.click(screen.getByRole('button', { name: '下一页' }));
      expect(screen.getByRole('article', { name: character.name })).toBeTruthy();
      expect(screen.getByText(character.costume)).toBeTruthy();
    }
    expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: '上一页' }));
    expect(screen.getByRole('article', { name: '贺兰霆' })).toBeTruthy();
  });

  it('keeps the current character reachable as available width and page size change', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<PromptCharacters characters={characters} />);
    act(() => resize(1100));
    expect(screen.getAllByRole('article')).toHaveLength(3);
    await user.click(screen.getByRole('button', { name: '下一页' }));
    expect(screen.getByRole('article', { name: '太后萧氏' })).toBeTruthy();

    act(() => resize(700));
    expect(screen.getByText('第 2 / 2 页 · 角色 3–4')).toBeTruthy();
    expect(screen.getAllByRole('article')).toHaveLength(2);
    act(() => resize(280));
    expect(screen.getByText('第 4 / 4 页 · 角色 4–4')).toBeTruthy();
    expect(screen.getByRole('article', { name: '太后萧氏' })).toBeTruthy();
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });
});
