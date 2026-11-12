// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Globe, Images } from 'lucide-react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardMoreMenu } from './StoryboardMoreMenu';

function menu(onSelect = vi.fn()) {
  return (
    <>
      <StoryboardMoreMenu
        label="更多"
        items={[
          { key: 'a', label: '360° 全景', icon: Globe, onSelect: () => onSelect('a') },
          { key: 'b', label: '图片池', icon: Images, disabled: true, onSelect: () => onSelect('b') },
          { key: 'c', label: '提示词分包', icon: Images, onSelect: () => onSelect('c') },
        ]}
      />
      <button type="button">外面</button>
    </>
  );
}

describe('StoryboardMoreMenu', () => {
  afterEach(cleanup);

  it('opens on its button, walks the entries with the arrow keys and runs the chosen one', async () => {
    const onSelect = vi.fn();
    render(menu(onSelect));
    const trigger = screen.getByRole('button', { name: '更多' });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('menu')).toBeNull();

    await userEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getAllByRole('menuitem')).toHaveLength(3);
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: '360° 全景' }));

    // The disabled entry is skipped, and the walk wraps round.
    await userEvent.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: '提示词分包' }));
    await userEvent.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: '360° 全景' }));
    await userEvent.keyboard('{End}{Enter}');

    expect(onSelect).toHaveBeenCalledWith('c');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('closes on Escape, giving focus back, and on a press outside', async () => {
    const onSelect = vi.fn();
    render(menu(onSelect));
    const trigger = screen.getByRole('button', { name: '更多' });

    await userEvent.click(trigger);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);

    await userEvent.click(trigger);
    expect(screen.getByRole('menu')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '外面' }));
    expect(screen.queryByRole('menu')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('closes on Escape while focus is still on its button, as when every entry is disabled', async () => {
    render(
      <StoryboardMoreMenu
        label="更多"
        items={[{ key: 'a', label: '360° 全景', icon: Globe, disabled: true, onSelect: vi.fn() }]}
      />,
    );
    const trigger = screen.getByRole('button', { name: '更多' });

    await userEvent.click(trigger);
    expect(screen.getByRole('menu')).toBeTruthy();
    expect(document.activeElement).toBe(trigger);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('steps from its button into the entries with the arrow keys, and leaves them alone while shut', async () => {
    render(menu());
    const trigger = screen.getByRole('button', { name: '更多' });

    trigger.focus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.queryByRole('menu')).toBeNull();

    await userEvent.click(trigger);
    trigger.focus();
    await userEvent.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: '提示词分包' }));
  });
});
