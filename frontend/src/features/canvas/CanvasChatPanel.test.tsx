// @vitest-environment jsdom
import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { chatContext, CHAT_NODE_LIMIT, readTurn } from './canvasChat';
import { CanvasChatPanel } from './CanvasChatPanel';
import type { CanvasNode } from './canvasTypes';

const apiRequest = vi.hoisted(() => vi.fn());
vi.mock('../../api/client', () => ({ apiRequest }));

function node(id: string, kind: CanvasNode['kind'], label: string): CanvasNode {
  return { id, kind, track: 'freezone', x: 0, y: 0, width: 260, height: 200, artifact_id: null, payload: { label } };
}

const PICTURE = node('n_1', 'image_gen', '雨夜的街');
const NOTE = node('n_2', 'note', '备忘');

function panel(props: Partial<Parameters<typeof CanvasChatPanel>[0]> = {}) {
  const handlers = { flush: vi.fn(async () => true), onCanvasChanged: vi.fn(), onJump: vi.fn() };
  const view = render(<CanvasChatPanel taskId="t-1" canvasId="main" selected={[PICTURE, NOTE]} {...handlers} {...props} />);
  return { ...handlers, ...view };
}

function say(text: string) {
  fireEvent.change(screen.getByLabelText('对助手说'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: '发给助手' }));
}

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe('what the canvas tells the assistant', () => {
  it('names the board and each selected node, and no more than the limit', () => {
    expect(chatContext('main', [PICTURE, NOTE])).toEqual({
      canvas_id: 'main', nodes: [{ id: 'n_1', title: '雨夜的街', kind: 'image_gen' }, { id: 'n_2', title: '备忘', kind: 'note' }],
    });
    const many = Array.from({ length: CHAT_NODE_LIMIT + 9 }, (_, index) => node(`n_${index}`, 'note', `便签 ${index}`));
    expect(chatContext('b2', many).nodes).toHaveLength(CHAT_NODE_LIMIT);
  });

  it('reads a turn: the reply, the tools used, a proposal, and the canvas version written last', () => {
    const turn = readTurn({
      reply: '连好了。',
      tool_calls: [
        { tool: 'get_canvas', result: { ok: true, result: {} } },
        { tool: 'edit_canvas', result: { ok: true, result: { ui_action: { type: 'canvas_changed', canvas_id: 'main', version: 7, node_ids: ['n_1'] } } } },
        { tool: 'edit_canvas', result: { ok: true, result: { ui_action: { type: 'canvas_changed', canvas_id: 'main', version: 8, node_ids: ['n_2', 'n_1'] } } } },
        { tool: 'run_canvas_nodes', result: { ok: false, error: '余额不足' } },
      ],
      proposal: { tool: 'run_canvas_nodes', message: '运行 1 个节点，约 0.6 元', arguments: { node_ids: ['n_1'] } },
    });
    expect(turn.reply).toBe('连好了。');
    expect(turn.calls).toEqual([{ tool: 'get_canvas', ok: true }, { tool: 'edit_canvas', ok: true }, { tool: 'edit_canvas', ok: true }, { tool: 'run_canvas_nodes', ok: false, error: '余额不足' }]);
    expect(turn.canvas).toEqual({ canvasId: 'main', version: 8, nodeIds: ['n_1', 'n_2'] });
    expect(turn.proposal).toMatchObject({ tool: 'run_canvas_nodes', message: '运行 1 个节点，约 0.6 元' });
  });

  it('reads a malformed answer as an empty turn', () => {
    expect(readTurn(null)).toEqual({ reply: '', proposal: null, calls: [], canvas: null });
    expect(readTurn({ reply: 3, tool_calls: 'x', proposal: [] })).toEqual({ reply: '', proposal: null, calls: [], canvas: null });
  });
});

describe('the assistant inside the canvas', () => {
  it('saves the canvas, then sends the message with the board and the selected nodes', async () => {
    apiRequest.mockResolvedValue({ reply: '好。', tool_calls: [] });
    const { flush } = panel();
    expect(within(screen.getByRole('list', { name: '随消息带上的节点' })).getAllByRole('listitem').map(item => item.textContent)).toEqual(['雨夜的街', '备忘']);
    say('把这两个连起来');
    await screen.findByText('好。');
    expect(flush).toHaveBeenCalledTimes(1);
    expect(apiRequest).toHaveBeenCalledTimes(1);
    const [path, init] = apiRequest.mock.calls[0];
    expect(path).toBe('/api/drama/t-1/assistant');
    expect(JSON.parse(init.body)).toEqual({
      message: '把这两个连起来',
      context: { canvas: { canvas_id: 'main', nodes: [{ id: 'n_1', title: '雨夜的街', kind: 'image_gen' }, { id: 'n_2', title: '备忘', kind: 'note' }] } },
    });
    expect(screen.getByText('带上了：雨夜的街、备忘')).toBeTruthy();
    expect((screen.getByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('');
  });

  it('still shows the answer when React mounts it twice, as it does in development', async () => {
    apiRequest.mockResolvedValue({ reply: '好。' });
    render(
      <StrictMode>
        <CanvasChatPanel taskId="t-1" canvasId="main" selected={[]} flush={async () => true} onCanvasChanged={vi.fn()} onJump={vi.fn()} />
      </StrictMode>,
    );
    say('画布上现在有什么');
    await screen.findByText('好。');
    expect(screen.queryByText('助手在想…')).toBeNull();
  });

  it('sends the board alone when the selection is detached', async () => {
    apiRequest.mockResolvedValue({ reply: '好。' });
    panel();
    fireEvent.click(screen.getByLabelText('带上选中的节点'));
    expect(screen.queryByRole('list', { name: '随消息带上的节点' })).toBeNull();
    say('画布上现在有什么');
    await screen.findByText('好。');
    expect(JSON.parse(apiRequest.mock.calls[0][1].body).context).toEqual({ canvas: { canvas_id: 'main', nodes: [] } });
  });

  it('sends on Enter, not on Shift + Enter, and nothing when there is nothing to send', async () => {
    apiRequest.mockResolvedValue({ reply: '好。' });
    panel();
    const input = screen.getByLabelText('对助手说');
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.change(input, { target: { value: '第一行' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(apiRequest).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await screen.findByText('好。');
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });

  it('brings the canvas up to date when the assistant wrote this board, and can jump to what it changed', async () => {
    apiRequest.mockResolvedValue({
      reply: '连好了。',
      tool_calls: [{ tool: 'edit_canvas', result: { ok: true, result: { ui_action: { type: 'canvas_changed', canvas_id: 'main', version: 9, node_ids: ['n_2', 'n_1'] } } } }],
    });
    const { onCanvasChanged, onJump } = panel();
    say('把这两个连起来');
    await screen.findByText('连好了。');
    expect(onCanvasChanged).toHaveBeenCalledWith(9, ['n_2', 'n_1']);
    expect(screen.getByText('用了：edit_canvas')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '看它改的 2 个节点' }));
    expect(onJump).toHaveBeenCalledWith('n_2');
  });

  it('leaves this board alone when the assistant wrote another one', async () => {
    apiRequest.mockResolvedValue({
      reply: '改了第二张。',
      tool_calls: [{ tool: 'edit_canvas', result: { ok: true, result: { ui_action: { type: 'canvas_changed', canvas_id: 'second', version: 4, node_ids: ['x'] } } } }],
    });
    const { onCanvasChanged } = panel();
    say('改第二张画布');
    await screen.findByText('改了第二张。');
    expect(onCanvasChanged).not.toHaveBeenCalled();
  });

  it('asks before anything paid: the proposal waits for a confirm or a cancel', async () => {
    apiRequest.mockResolvedValueOnce({ reply: '要运行这个节点吗？', proposal: { tool: 'run_canvas_nodes', message: '运行 1 个节点，约 0.6 元', arguments: {} } });
    panel();
    say('运行这个节点');
    const proposal = await screen.findByRole('group', { name: '等您确认' });
    expect(within(proposal).getByText('运行 1 个节点，约 0.6 元')).toBeTruthy();
    expect(apiRequest).toHaveBeenCalledTimes(1);
    apiRequest.mockResolvedValueOnce({ reply: '已放弃。' });
    fireEvent.click(within(proposal).getByRole('button', { name: '放弃' }));
    await screen.findByText('已放弃。');
    expect(JSON.parse(apiRequest.mock.calls[1][1].body).message).toBe('/cancel');
    // The answered proposal keeps its text and loses its buttons.
    expect(screen.queryByRole('button', { name: '确认执行' })).toBeNull();
  });

  it('does not send while the canvas cannot be saved, and gives the words back', async () => {
    const flush = vi.fn(async () => false);
    panel({ flush });
    say('把这张图换成夜景');
    await screen.findByText(/画布还没保存成功/);
    expect(flush).toHaveBeenCalled();
    expect(apiRequest).not.toHaveBeenCalled();
    expect((screen.getByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('把这张图换成夜景');
  });

  it('shows why the assistant could not be reached and gives the words back', async () => {
    apiRequest.mockImplementation(async () => { throw new Error('助手现在不可用'); });
    panel();
    say('把这张图换成夜景');
    await screen.findByText('助手现在不可用');
    await waitFor(() => expect((screen.getByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('把这张图换成夜景'));
  });
});
