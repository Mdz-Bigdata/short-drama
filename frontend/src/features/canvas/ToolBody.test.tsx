// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasContext, type CanvasActions } from './canvasContext';
import { connect, effectiveOutput, outputType, RUNNABLE_KINDS } from './canvasGraph';
import { CANVAS_TOOLS, toolById } from './canvasTools';
import type { CanvasDoc, CanvasNode, NodeOutput, RunOptions } from './canvasTypes';
import { ToolBody } from './ToolBody';

afterEach(cleanup);

const STYLES = [
  { id: 'ink_wash', group: '绘画', names: { zh: '水墨', en: 'Ink wash', vi: 'Thủy mặc' }, prompt: '中国水墨', swatch: ['#222222', '#eeeeee'] as [string, string] },
  { id: 'noir', group: '写实', names: { zh: '黑色电影', en: 'Film noir', vi: 'Film noir' }, prompt: '黑色电影', swatch: ['#111111', '#aaaaaa'] as [string, string] },
];

function node(tool: string, params: Record<string, unknown> = {}): CanvasNode {
  return { id: 't1', kind: 'tool', track: 'freezone', x: 0, y: 0, width: 300, height: 340, artifact_id: null, payload: { params: { tool, ...params } } };
}

function renderBody(target: CanvasNode, { output = null, engines }: { output?: NodeOutput | null; engines?: Partial<NonNullable<RunOptions['tools']>['engines']> } = {}) {
  const patch = vi.fn();
  const layOutBeats = vi.fn();
  const actions = {
    taskId: 't', shots: [], deskToken: 0, patch, run: vi.fn(), cancel: vi.fn(), upload: vi.fn(), openDesk: vi.fn(), layOutBeats,
    options: { tools: { styles: STYLES, engines: { image: true, vision: true, text: true, local: true, voice: true, ...engines } } },
  } as unknown as CanvasActions;
  render(
    <CanvasContext.Provider value={actions}>
      <ToolBody node={target} output={output} media={<div>MEDIA</div>} prompt={label => <textarea aria-label={label} />} runBar={<button type="button">RUN</button>} />
    </CanvasContext.Provider>,
  );
  return { patch, layOutBeats };
}

describe('the tool node', () => {
  it('says who does the work and what it costs', () => {
    renderBody(node('redraw'));
    expect(screen.getByText('图像模型 · 计费')).toBeTruthy();
  });

  it('a local tool says it is free and what it really does', () => {
    renderBody(node('upscale_image'));
    expect(screen.getByText('本机处理 · 免费')).toBeTruthy();
    expect(screen.getByText(/不增加真实细节/)).toBeTruthy();
  });

  it('changing tool starts clean, keeping only the chosen model', () => {
    const { patch } = renderBody(node('relight', { light: 'neon', model: 'm1' }));
    fireEvent.change(screen.getByLabelText('工具'), { target: { value: 'sketch' } });
    expect(patch).toHaveBeenCalledWith('t1', { params: { tool: 'sketch', model: 'm1' } });
  });

  it('a parameter is written into the params', () => {
    const { patch } = renderBody(node('relight'));
    fireEvent.change(screen.getByLabelText('光线'), { target: { value: 'neon' } });
    expect(patch.mock.calls[0][1]).toEqual({ params: { tool: 'relight', light: 'neon' } });
  });

  it('style transfer offers the wall and marks the pick', () => {
    const { patch } = renderBody(node('style_transfer', { style: 'noir' }));
    const noir = screen.getByRole('radio', { name: '黑色电影' });
    expect(noir.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(screen.getByRole('radio', { name: '水墨' }));
    expect(patch.mock.calls[0][1]).toEqual({ params: { tool: 'style_transfer', style: 'ink_wash' } });
  });

  it('only style transfer shows the wall', () => {
    renderBody(node('redraw'));
    expect(screen.queryByRole('radiogroup', { name: '风格墙' })).toBeNull();
  });

  it('warns when what the tool needs is missing, before anyone presses run', () => {
    renderBody(node('reverse_prompt'), { engines: { vision: false } });
    expect(screen.getByText('没有配置多模态模型')).toBeTruthy();
  });

  it('a tool that takes no words has no text box', () => {
    renderBody(node('audio_extract'));
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('a text result is shown as text, with no media', () => {
    renderBody(node('reverse_prompt'), { output: { medium: 'text', url: '', text: '雨夜霓虹街道' } });
    expect(screen.getByText('雨夜霓虹街道')).toBeTruthy();
    expect(screen.queryByText('MEDIA')).toBeNull();
  });

  it('a beat plan can be laid out as nodes', () => {
    const beats = [{ title: '开门', prompt: '林夏推门' }, { title: '回头', prompt: '林夏回头' }];
    const { layOutBeats } = renderBody(node('beat_plan'), { output: { medium: 'text', url: '', text: '1. 开门', beats } });
    fireEvent.click(screen.getByRole('button', { name: '铺成 2 个节点' }));
    expect(layOutBeats).toHaveBeenCalledWith('t1', beats);
  });
});

describe('the tool node on the graph', () => {
  const doc = (nodes: CanvasNode[]): CanvasDoc => ({ nodes, edges: [] } as unknown as CanvasDoc);
  const video: CanvasNode = { id: 'v', kind: 'media', track: 'freezone', x: 0, y: 0, width: 1, height: 1, artifact_id: null, payload: { medium: 'video', output: { medium: 'video', url: '/a.mp4' } } };

  it('accepts what its tool takes and refuses the rest', () => {
    expect(connect(doc([video, node('video_erase')]), 'v', 't1').ok).toBe(true);
    expect(connect(doc([video, node('redraw')]), 'v', 't1')).toEqual({ ok: false, reason: '不接受' });
  });

  it('hands on what its tool makes', () => {
    expect(outputType(node('frame_extract'))).toBe('image');
    expect(outputType(node('audio_extract'))).toBe('audio');
    expect(outputType(node('reverse_prompt'))).toBe('text');
  });

  it('runs', () => {
    expect(RUNNABLE_KINDS.has('tool')).toBe(true);
  });

  it('a written result counts as a result', () => {
    const target = node('reverse_prompt');
    expect(effectiveOutput(target, doc([target]), { t1: { medium: 'text', url: '', text: '词' } })?.text).toBe('词');
  });

  it('tool ids are unique and an unknown one is not silently a tool', () => {
    expect(new Set(CANVAS_TOOLS.map(tool => tool.id)).size).toBe(CANVAS_TOOLS.length);
    expect(toolById('nope')).toBeUndefined();
    expect(toolById(undefined)?.id).toBe('redraw');
  });
});
