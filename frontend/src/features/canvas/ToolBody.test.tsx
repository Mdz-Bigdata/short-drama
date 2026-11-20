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
  const layOutShots = vi.fn();
  const actions = {
    taskId: 't', shots: [], deskToken: 0, patch, run: vi.fn(), cancel: vi.fn(), upload: vi.fn(), openDesk: vi.fn(), layOutBeats, layOutShots,
    options: { tools: { styles: STYLES, engines: { image: true, vision: true, text: true, local: true, voice: true, ...engines } } },
  } as unknown as CanvasActions;
  render(
    <CanvasContext.Provider value={actions}>
      <ToolBody node={target} output={output} media={<div>MEDIA</div>} prompt={label => <textarea aria-label={label} />} runBar={<button type="button">RUN</button>} />
    </CanvasContext.Provider>,
  );
  return { patch, layOutBeats, layOutShots };
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

  it('character extraction says what to connect and what it writes', () => {
    renderBody(node('character_extract'));
    expect(screen.getByText('多模态模型 · 计费')).toBeTruthy();
    expect(screen.getByText(/性别年龄、五官、面部标记、发型、体型、服装、配饰、画风/)).toBeTruthy();
    expect(screen.getByLabelText('连了图：写图里哪个人、叫什么（可选）；没连图：写角色描述')).toBeTruthy();
  });

  it('character extraction still runs on words when only the text model is set up', () => {
    renderBody(node('character_extract'), { engines: { vision: false } });
    expect(screen.queryByText('没有配置多模态模型')).toBeNull();
    cleanup();
    renderBody(node('character_extract'), { engines: { vision: false, text: false } });
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

  it('a shot table lays out as shots with the server\'s frame words, and says when the count is off', () => {
    const shots = [
      { size: '中景', motion: '', seconds: 4, desc: '女孩进门', characters: ['女孩'], dialogue: '女孩：还营业吗？' },
      { size: '近景', motion: '', seconds: 4, desc: '店主抬头', characters: ['店主'], dialogue: '店主：一直在等你。' },
    ];
    const beats = [{ title: '第 1 镜', prompt: '女孩进门，中景。人物：女孩（二十出头）' }, { title: '第 2 镜', prompt: '店主抬头，近景。人物：店主（白发）' }];
    const { layOutShots } = renderBody(node('shot_table'), { output: { medium: 'text', url: '', text: '1. …', beats, shots, asked: 3 } });
    expect(screen.getByText('要的是 3 个镜头，模型给了 2 个：可以重新运行，或铺上去后删掉多的')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '铺成 2 个镜头' }));
    expect(layOutShots).toHaveBeenCalledWith('t1', shots, beats.map(beat => beat.prompt), []);
  });

  it('a shot table says which lines it moved out of the script\'s order', () => {
    renderBody(node('shot_table'), { output: { medium: 'text', url: '', text: '1. …', beats: [], shots: [], line_order: ['还开着吗？'] } });
    expect(screen.getByText('这几句台词的顺序和剧本不一致：「还开着吗？」。可以重新运行，或铺上去后改一下视频节点里的台词')).toBeTruthy();
  });

  it('a shot table that got the count it asked for says nothing about it, and offers a shot count setting', () => {
    renderBody(node('shot_table', { shots: 2 }), { output: { medium: 'text', url: '', text: '1. …', beats: [], shots: [{ size: '', motion: '', seconds: 4, desc: '甲', dialogue: '' }, { size: '', motion: '', seconds: 4, desc: '乙', dialogue: '' }], asked: 2 } });
    expect(screen.queryByText(/要的是/)).toBeNull();
    expect((screen.getByLabelText('镜头数（0 = 按剧本）') as HTMLInputElement).value).toBe('2');
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
