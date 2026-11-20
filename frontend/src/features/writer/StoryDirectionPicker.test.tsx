// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryDirectionPicker, type StoryDirection, type StoryDirectionRequest } from './StoryDirectionPicker';
import { noGoLines } from './storyNoGo';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const refuse = (status: number, detail: string) => ({ ok: false, status, json: async () => ({ detail }) }) as Response;
const direction = (index: number): StoryDirection => ({
  title: `方向${index}`, logline: `一句话故事${index}`, conflict: `冲突${index}`, hook: `钩子${index}`, appeal: `看点${index}`,
});
const REQUEST: StoryDirectionRequest = { idea: '纸扎匠给早夭的女儿扎了纸人', creationMode: 'drama', episodeCount: 3, llmModel: 'deepseek-flash' };

function Harness({ request = REQUEST, onPick }: { request?: StoryDirectionRequest; onPick?: (value: StoryDirection | null) => void }) {
  const [value, setValue] = useState<StoryDirection | null>(null);
  const [noGo, setNoGo] = useState('');
  return (
    <StoryDirectionPicker
      request={request} value={value} onChange={next => { setValue(next); onPick?.(next); }} noGo={noGo} onNoGoChange={setNoGo}
    />
  );
}

describe('StoryDirectionPicker', () => {
  it('asks the model only when the button is pressed, and sends the idea with the no-go lines', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ directions: [1, 2, 3, 4].map(direction) }));
    render(<Harness />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText('会用 deepseek-flash 调用一次文本模型')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/创作禁区/), { target: { value: '1. 不要失忆梗\n\n- 不要重生\n不要重生' } });
    expect(screen.getByText('2 条，整部剧都不会出现')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    expect(await screen.findAllByRole('radio')).toHaveLength(4);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/story-directions');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]!.body))).toEqual({ ...REQUEST, storyNoGo: ['不要失忆梗', '不要重生'] });
    expect(screen.getByRole('button', { name: '换一批方向' })).toBeTruthy();
  });

  it('sends the hot topic the creator typed, and nothing extra when the box is empty', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ directions: [1, 2].map(direction) }));
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    await screen.findAllByRole('radio');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]!.body))).not.toHaveProperty('trend');
    fireEvent.change(screen.getByLabelText(/想借的热点/), { target: { value: '  素人一句话怼哭评委 ' } });
    fireEvent.click(screen.getByRole('button', { name: '换一批方向' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]!.body)).trend).toBe('素人一句话怼哭评委');
  });

  it('picks one direction, and a second click on it clears the choice', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ directions: [1, 2].map(direction) }));
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    const cards = await screen.findAllByRole('radio');
    fireEvent.click(cards[1]);
    expect(onPick).toHaveBeenLastCalledWith(direction(2));
    expect(cards[1].getAttribute('aria-checked')).toBe('true');
    expect(cards[0].getAttribute('aria-checked')).toBe('false');
    expect(screen.getByText('已选：方向2（再点一次取消）')).toBeTruthy();
    fireEvent.click(cards[1]);
    expect(onPick).toHaveBeenLastCalledWith(null);
    expect(screen.getByText('不选由总导演定')).toBeTruthy();
  });

  it('drops a pick that the next batch no longer offers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(ok({ directions: [1, 2].map(direction) }))
      .mockResolvedValueOnce(ok({ directions: [3, 4].map(direction) }));
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    fireEvent.click((await screen.findAllByRole('radio'))[0]);
    fireEvent.click(screen.getByRole('button', { name: '换一批方向' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(onPick).toHaveBeenLastCalledWith(null));
    expect(await screen.findByText('方向3')).toBeTruthy();
  });

  it('shows the server’s own words when no directions come back, and waits for a text model before asking', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(refuse(422, '模型没有给出回答，可以再试一次'));
    const { rerender } = render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    expect((await screen.findByRole('alert')).textContent).toContain('模型没有给出回答');
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    rerender(<Harness request={{ ...REQUEST, llmModel: '' }} />);
    expect((screen.getByRole('button', { name: '先给我几个故事方向' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('还没有可用的文本模型，先到模型设置里启用一个')).toBeTruthy();
  });

  it('recommends directions with no idea written, and the one picked becomes the idea', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({
      directions: [1, 2, 3, 4, 5].map(direction), ideas: [1, 2, 3, 4, 5].map(n => `想法 ${n}`), open: true,
    }));
    const onIdea = vi.fn();
    function Open() {
      const [idea, setIdea] = useState(' ');
      const [value, setValue] = useState<StoryDirection | null>(null);
      return (
        <>
          <input aria-label="想法" value={idea} onChange={event => setIdea(event.target.value)} />
          <StoryDirectionPicker
            request={{ ...REQUEST, idea }} value={value} onChange={setValue} noGo="" onNoGoChange={() => {}}
            onIdea={text => { onIdea(text); setIdea(text); }}
          />
        </>
      );
    }
    render(<Open />);
    const ask = screen.getByRole('button', { name: '还没想法？给我推荐几个方向' }) as HTMLButtonElement;
    expect(ask.disabled).toBe(false);
    expect(screen.getByText(/不写想法也行/)).toBeTruthy();
    fireEvent.click(ask);
    const cards = await screen.findAllByRole('radio');
    expect(cards).toHaveLength(5);
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body)).idea).toBe(' ');

    fireEvent.click(cards[1]);
    expect(onIdea).toHaveBeenLastCalledWith('想法 2');
    // Picking another while the box still holds what the last pick wrote follows the pick …
    fireEvent.click(cards[3]);
    expect(onIdea).toHaveBeenLastCalledWith('想法 4');
    // … but words the creator typed are left alone.
    fireEvent.change(screen.getByLabelText('想法'), { target: { value: '我自己的想法' } });
    fireEvent.click(cards[0]);
    expect(onIdea).toHaveBeenCalledTimes(2);
    expect((screen.getByLabelText('想法') as HTMLInputElement).value).toBe('我自己的想法');
  });

  it('does not touch an idea the creator wrote when a direction is picked', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ directions: [1, 2].map(direction), ideas: ['想法 1', '想法 2'] }));
    const onIdea = vi.fn();
    render(<StoryDirectionPicker request={REQUEST} value={null} onChange={() => {}} noGo="" onNoGoChange={() => {}} onIdea={onIdea} />);
    fireEvent.click(screen.getByRole('button', { name: '先给我几个故事方向' }));
    fireEvent.click((await screen.findAllByRole('radio'))[0]);
    expect(onIdea).not.toHaveBeenCalled();
  });

  it('reads no-go lines the way the server does', () => {
    expect(noGoLines(' 1. 不要失忆梗 \n2、不要重生\n• 不要失忆梗\n')).toEqual(['不要失忆梗', '不要重生']);
    expect(noGoLines(Array.from({ length: 20 }, (_item, index) => `不要${index}`).join('\n'))).toHaveLength(8);
    expect(noGoLines('字'.repeat(200))[0]).toHaveLength(60);
  });
});
