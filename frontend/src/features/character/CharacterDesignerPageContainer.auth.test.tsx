// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CharacterDesignerPageContainer } from './CharacterDesignerPageContainer';

const embeddedCharacters = [
  { name: '沈砚之', role: '男主角', desc: '银丝半框眼镜。', sheet: null, views: [] },
];

function unauthorizedFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    void input;
    return {
      ok: false,
      status: 401,
      json: async () => ({ detail: '会话已过期，请重新登录' }),
    } as Response;
  });
}

describe('CharacterDesignerPageContainer under an expired session', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('stops polling the element library instead of retrying a 401 forever', async () => {
    const fetchMock = unauthorizedFetch();
    vi.stubGlobal('fetch', fetchMock);

    render(
      <CharacterDesignerPageContainer
        taskId="task-1"
        refreshKey="3:running:false"
        title="乱葬坑里有人醒"
        fallbackCharacters={embeddedCharacters}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    const elementCalls = () => fetchMock.mock.calls
      .filter(call => String(call[0]).includes('/api/elements')).length;
    const afterMount = elementCalls();

    // Let the app idle well past any retry cadence.
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

    expect(afterMount).toBeLessThanOrEqual(4);
    expect(elementCalls()).toBe(afterMount);
  });

  it('tells the user the session expired rather than showing a silent empty state', async () => {
    vi.stubGlobal('fetch', unauthorizedFetch());

    render(
      <CharacterDesignerPageContainer
        taskId="task-1"
        refreshKey="3:running:false"
        title="乱葬坑里有人醒"
        fallbackCharacters={embeddedCharacters}
        onRefresh={vi.fn()}
        onRegenerate={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    await act(async () => { await vi.advanceTimersByTimeAsync(50); });

    const status = screen.getAllByRole('status').map(node => node.textContent).join(' ');
    expect(status).toMatch(/登录|会话/);
  });
});
