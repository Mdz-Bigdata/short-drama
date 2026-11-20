import { describe, expect, it } from 'vitest';

import { newNode } from './canvasGraph';
import { searchNodes } from './canvasSearch';
import type { CanvasNode, NodeKind, NodePayload } from './canvasTypes';

function node(id: string, kind: NodeKind, payload: NodePayload): CanvasNode {
  return { ...newNode(kind, 0, 0, payload), id };
}

describe('searchNodes', () => {
  const nodes = [
    node('prompt-hit', 'image_gen', { label: '镜头一', prompt: 'A rainy Night street, neon' }),
    node('title-mid', 'video_gen', { label: '追逐 night 场' }),
    node('title-prefix', 'note', { label: 'Night market', text: 'stalls' }),
    node('file-hit', 'media', { output: { medium: 'image', url: '/m/x.png', filename: 'night_cover.png' } }),
    node('style', 'style_ref', { styleText: '冷色调 霓虹 夜景' }),
    node('tool', 'tool', { output: { medium: 'text', url: '', text: '第一段：夜里 下雨' } }),
    node('html', 'tool', { output: { medium: 'text', url: '', text: '<p>night</p>', html: true } }),
  ];

  it('ranks title prefix, then title, then other fields', () => {
    expect(searchNodes(nodes, 'night').map(hit => [hit.id, hit.field])).toEqual([
      ['title-prefix', 'title'], ['title-mid', 'title'], ['prompt-hit', 'prompt'], ['file-hit', 'filename'],
    ]);
  });

  it('ignores case and spaces, and marks the match in the original text', () => {
    const [hit] = searchNodes(nodes, 'RAINY  ni');
    expect(hit.id).toBe('prompt-hit');
    expect(hit.snippet.text.slice(hit.snippet.start, hit.snippet.end)).toBe('rainy Ni');
    const [style] = searchNodes(nodes, '霓虹夜景');
    expect(style.field).toBe('styleText');
    expect(style.snippet.text.slice(style.snippet.start, style.snippet.end)).toBe('霓虹 夜景');
    expect(searchNodes(nodes, '夜里下雨')[0]).toMatchObject({ id: 'tool', field: 'output' });
  });

  it('falls back to the kind for an unnamed node and trims long snippets', () => {
    const long = node('long', 'note', { text: `${'前'.repeat(60)}目标${'后'.repeat(100)}` });
    const [hit] = searchNodes([long], '目标');
    expect(hit.title).toBe('文本注释');
    expect(hit.snippet.text.startsWith('…')).toBe(true);
    expect(hit.snippet.text.endsWith('…')).toBe(true);
    expect(hit.snippet.text.slice(hit.snippet.start, hit.snippet.end)).toBe('目标');
  });

  it('returns nothing for an empty query and honours the limit', () => {
    expect(searchNodes(nodes, '   ')).toEqual([]);
    const many = Array.from({ length: 100 }, (_, index) => node(`n${index}`, 'note', { label: `场景 ${index}` }));
    expect(searchNodes(many, '场景')).toHaveLength(80);
    expect(searchNodes(many, '场景', { limit: 5 })).toHaveLength(5);
  });
});
