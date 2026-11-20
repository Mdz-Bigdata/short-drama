// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SerialBriefPicker } from './SerialBriefPicker';
import { EMPTY_SERIAL_BRIEF, genreClashes, serialBriefPayload, type SerialBrief } from './serialBrief';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const PLAN = {
  min_episodes: 30,
  episodes: [{ episode: 10, kind: 'identity', label: '身份即将揭露' }, { episode: 18, kind: 'truth', label: '真相即将大白' }],
};

function Harness({ episodes = 60, onValue }: { episodes?: number; onValue?: (value: SerialBrief) => void }) {
  const [value, setValue] = useState<SerialBrief>(EMPTY_SERIAL_BRIEF);
  return <SerialBriefPicker value={value} episodeCount={episodes} onChange={next => { setValue(next); onValue?.(next); }} />;
}

describe('SerialBriefPicker', () => {
  it('stacks genres in the order clicked, numbers them, and stops at three', () => {
    const onValue = vi.fn();
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    render(<Harness onValue={onValue} />);
    expect(screen.getByText('可以叠到 3 个，第一个定基调；不选由总导演定')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '战神归来' }));
    expect(screen.getByText('隐姓埋名的强者回到看不起他的人中间')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '萌宝' }));
    fireEvent.click(screen.getByRole('button', { name: /都市情感/ }));
    expect(onValue).toHaveBeenLastCalledWith({ ...EMPTY_SERIAL_BRIEF, genres: ['war_god', 'baby', 'urban_romance'] });
    expect(screen.getByRole('button', { name: /战神归来/ }).textContent).toBe('1战神归来');
    expect(screen.getByRole('button', { name: /萌宝/ }).getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByRole('button', { name: '喜剧' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('已经叠了 3 个，再点一个已选的可以取消')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /战神归来/ }));
    expect(onValue).toHaveBeenLastCalledWith({ ...EMPTY_SERIAL_BRIEF, genres: ['baby', 'urban_romance'] });
    expect((screen.getByRole('button', { name: '喜剧' }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('points out a pair of genres that pull against each other', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '甜宠' }));
    expect(screen.queryByText(/气质相冲/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '末日重生' }));
    expect(screen.getByText('甜宠和末日的气质相冲，除非你就是要这种反差')).toBeTruthy();
    expect(genreClashes(['mystery', 'baby', 'comedy'])).toHaveLength(1);
  });

  it('picks one tone and one ending, and a second click clears it', () => {
    const onValue = vi.fn();
    render(<Harness onValue={onValue} />);
    fireEvent.click(screen.getByRole('radio', { name: '爽燃' }));
    fireEvent.click(screen.getByRole('radio', { name: '暗黑' }));
    fireEvent.click(screen.getByRole('radio', { name: '反转式' }));
    expect(onValue).toHaveBeenLastCalledWith({ ...EMPTY_SERIAL_BRIEF, tone: 'dark', ending: 'twist' });
    expect(screen.getByText('代价真实，人心复杂')).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: '暗黑' }));
    expect(onValue).toHaveBeenLastCalledWith({ ...EMPTY_SERIAL_BRIEF, ending: 'twist' });
  });

  it('asks where the paywall episodes fall only after the box is ticked, with the length and the lead genre', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok(PLAN));
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '甜宠' }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox', { name: /规划付费卡点/ }));
    expect(await screen.findByText('共 2 个付费卡点')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/serial-brief/paywall?episodes=60&genre=sweet');
    expect(screen.getByText('第 10 集')).toBeTruthy();
    expect(screen.getByText('真相即将大白')).toBeTruthy();
  });

  it('says so when the serial is too short for a paywall plan, and when the positions could not be read', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ min_episodes: 30, episodes: [] }));
    const view = render(<Harness episodes={12} />);
    fireEvent.click(screen.getByRole('checkbox', { name: /规划付费卡点/ }));
    expect(await screen.findByText('不到 30 集的剧不规划付费卡点')).toBeTruthy();
    view.unmount();
    fetchMock.mockRejectedValue(new Error('offline'));
    render(<Harness />);
    fireEvent.click(screen.getByRole('checkbox', { name: /规划付费卡点/ }));
    await waitFor(() => expect(screen.getByText('付费卡点的位置没有取到，不影响创建')).toBeTruthy());
  });

  it('sends only what was chosen', () => {
    expect(serialBriefPayload(EMPTY_SERIAL_BRIEF)).toEqual({});
    expect(serialBriefPayload({ genres: ['war_god', 'baby'], tone: 'blazing', ending: '', overseas: true, paywall: true })).toEqual({
      storyGenres: ['war_god', 'baby'], storyTone: 'blazing', overseas: true, paywallPlan: true,
    });
  });
});
