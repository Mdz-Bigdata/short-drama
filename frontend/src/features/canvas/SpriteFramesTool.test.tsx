// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasContext, type CanvasActions } from './canvasContext';
import { connect, outputType } from './canvasGraph';
import * as nodeActions from './canvasNodeActions';
import { toolById } from './canvasTools';
import type { CanvasDoc, CanvasNode, NodeOutput } from './canvasTypes';
import { ToolBody } from './ToolBody';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function node(params: Record<string, unknown> = {}, label?: string): CanvasNode {
  return { id: 't1', kind: 'tool', track: 'freezone', x: 0, y: 0, width: 300, height: 340, artifact_id: null, payload: { params: { tool: 'sprite_frames', ...params }, ...(label ? { label } : {}) } };
}

function renderBody(target: CanvasNode, output: NodeOutput | null = null) {
  const patch = vi.fn();
  const actions = {
    taskId: 't', shots: [], deskToken: 0, patch, run: vi.fn(), cancel: vi.fn(), upload: vi.fn(), openDesk: vi.fn(), layOutBeats: vi.fn(), layOutShots: vi.fn(),
    options: { tools: { styles: [], engines: { image: true, vision: true, text: true, local: true, voice: true } } },
  } as unknown as CanvasActions;
  render(
    <CanvasContext.Provider value={actions}>
      <ToolBody node={target} output={output} media={<div>MEDIA</div>} prompt={label => <textarea aria-label={label} />} runBar={<button type="button">RUN</button>} />
    </CanvasContext.Provider>,
  );
  return { patch };
}

const SHEET: NodeOutput = {
  medium: 'image', url: '/media/sheet.png', zip: '/media/frames.zip',
  sprite: { frame_width: 202, frame_height: 126, count: 24, fps: 12, sheet: { columns: 4, rows: 6 } },
};

describe('the 抠像序列帧 tool', () => {
  it('is a free local video tool that hands on a picture', () => {
    const tool = toolById('sprite_frames');
    expect([tool?.group, tool?.engine, tool?.output]).toEqual(['video', 'local', 'image']);
    expect(outputType(node())).toBe('image');
    const video: CanvasNode = { id: 'v', kind: 'media', track: 'freezone', x: 0, y: 0, width: 1, height: 1, artifact_id: null, payload: { medium: 'video', output: { medium: 'video', url: '/a.mp4' } } };
    const image: CanvasNode = { ...video, id: 'i', payload: { medium: 'image', output: { medium: 'image', url: '/a.png' } } };
    const doc = (nodes: CanvasNode[]) => ({ nodes, edges: [] } as unknown as CanvasDoc);
    expect(connect(doc([video, node()]), 'v', 't1').ok).toBe(true);
    expect(connect(doc([image, node()]), 'i', 't1').ok).toBe(false);
  });

  it('says it is free, what it makes, and how to shoot for a clean cut-out; it takes no words', () => {
    renderBody(node());
    expect(screen.getByText('本机处理 · 免费')).toBeTruthy();
    expect(screen.getByText(/同样大小的透明 PNG/)).toBeTruthy();
    expect(screen.getByText(/品红通常比蓝、绿好/)).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('starts from the defaults the server uses', () => {
    renderBody(node());
    expect((screen.getByLabelText('底色') as HTMLSelectElement).value).toBe('auto');
    expect((screen.getByLabelText('容差') as HTMLInputElement).value).toBe('40');
    expect((screen.getByLabelText('帧率（帧/秒）') as HTMLInputElement).value).toBe('12');
    expect((screen.getByLabelText('最多帧数') as HTMLInputElement).value).toBe('120');
  });

  it('offers the colour picker only for a custom key colour, and writes what is picked', () => {
    renderBody(node());
    expect(screen.queryByLabelText('自定义颜色')).toBeNull();
    cleanup();
    const { patch } = renderBody(node({ key: 'custom' }));
    fireEvent.change(screen.getByLabelText('自定义颜色'), { target: { value: '#00ffcc' } });
    expect(patch.mock.calls[0][1]).toEqual({ params: { tool: 'sprite_frames', key: 'custom', key_hex: '#00ffcc' } });
  });

  it('a setting is written into the params', () => {
    const { patch } = renderBody(node());
    fireEvent.change(screen.getByLabelText('底色'), { target: { value: 'magenta' } });
    fireEvent.change(screen.getByLabelText('帧率（帧/秒）'), { target: { value: '8' } });
    expect(patch.mock.calls[0][1]).toEqual({ params: { tool: 'sprite_frames', key: 'magenta' } });
    expect(patch.mock.calls[1][1]).toEqual({ params: { tool: 'sprite_frames', fps: 8 } });
  });

  it('shows the sprite sheet, says what the ZIP holds and downloads it under the node\'s name', () => {
    const download = vi.spyOn(nodeActions, 'downloadMedia').mockResolvedValue('saved');
    renderBody(node({}, '挥刀 01'), SHEET);
    expect(screen.getByText('MEDIA')).toBeTruthy();
    expect(screen.getByText('24 帧 · 每帧 202×126 · 12 帧/秒 · 精灵图 4 列 × 6 行')).toBeTruthy();
    expect(screen.queryByText(/没有拼成精灵图/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '下载 ZIP' }));
    expect(download).toHaveBeenCalledWith('/media/frames.zip', '挥刀 01.zip');
  });

  it('says so when there were too many frames for a sheet', () => {
    renderBody(node(), { ...SHEET, sprite: { frame_width: 900, frame_height: 1600, count: 200, fps: 24, sheet: null } });
    expect(screen.getByText('200 帧 · 每帧 900×1600 · 24 帧/秒')).toBeTruthy();
    expect(screen.getByText(/没有拼成精灵图/)).toBeTruthy();
  });

  it('a result with no ZIP has no download row', () => {
    renderBody(node(), { medium: 'image', url: '/media/a.png' });
    expect(screen.queryByRole('button', { name: '下载 ZIP' })).toBeNull();
  });
});
