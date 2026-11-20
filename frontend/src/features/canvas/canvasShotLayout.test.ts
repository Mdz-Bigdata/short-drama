import { describe, expect, it } from 'vitest';

import { newNode } from './canvasGraph';
import { castSheets, clipPrompt, framePrompt, layOutShotTable, SHOT_COLUMN, shotPairs } from './canvasShotLayout';
import type { TableCast, TableShot } from './canvasTypes';

const SHOTS: TableShot[] = [
  { size: '近景', motion: '推', seconds: 6, desc: '林晚推开门', dialogue: '林晚：有人吗？' },
  { size: '', motion: '', seconds: 0, desc: '雨街空镜', dialogue: '' },
];

describe('a shot table laid out as shots', () => {
  it('draws each frame from what is seen and the camera, and gives each clip its lines after the lead', () => {
    expect(framePrompt(SHOTS[0])).toBe('林晚推开门，近景，推');
    expect(framePrompt(SHOTS[1])).toBe('雨街空镜');
    expect(clipPrompt(SHOTS[0])).toBe('林晚推开门\n台词：林晚：有人吗？');
    expect(clipPrompt(SHOTS[1])).toBe('雨街空镜');
  });

  it('makes a first frame feeding a video node per shot, in a row right of the table', () => {
    const table = { ...newNode('tool', 100, 50), width: 300 };
    const { nodes, edges } = shotPairs(table, SHOTS);
    expect(nodes.map(node => [node.kind, node.payload.label])).toEqual([
      ['image_gen', '镜1 首帧'], ['video_gen', '镜1 视频'], ['image_gen', '镜2 首帧'], ['video_gen', '镜2 视频'],
    ]);
    expect(nodes[1].payload.params).toEqual({ durationSeconds: 6 });
    expect(nodes[3].payload.params).toBeUndefined();
    expect(nodes[0].x).toBeGreaterThan(table.x + table.width);
    expect(nodes[2].x - nodes[0].x).toBe(SHOT_COLUMN);
    expect(nodes[1].y).toBeGreaterThan(nodes[0].y);
    expect(edges.map(edge => [edge.source, edge.target, edge.payload.role])).toEqual([
      [nodes[0].id, nodes[1].id, 'first_frame'], [nodes[2].id, nodes[3].id, 'first_frame'],
    ]);
  });

  it('adds them to the canvas, and nothing when the table is gone', () => {
    const table = newNode('tool', 0, 0);
    const doc = { nodes: [table], edges: [] };
    expect(layOutShotTable(doc, table.id, SHOTS)?.nodes).toHaveLength(5);
    expect(layOutShotTable(doc, 'gone', SHOTS)).toBeNull();
    expect(layOutShotTable(doc, table.id, [])).toBeNull();
  });

  it('draws each frame from the words the server wrote for it, looks included, when it has them', () => {
    const table = newNode('tool', 0, 0);
    const { nodes } = shotPairs(table, SHOTS, ['林晚推开门，近景，推。人物：林晚（二十出头，黑色长发）']);
    expect(nodes[0].payload.prompt).toBe('林晚推开门，近景，推。人物：林晚（二十出头，黑色长发）');
    expect(nodes[2].payload.prompt).toBe('雨街空镜');
  });
});

describe('one face per character', () => {
  const SHOTS4: TableShot[] = [
    { size: '', motion: '', seconds: 4, desc: '女孩进门', characters: ['女孩'], dialogue: '女孩：还营业吗？' },
    { size: '', motion: '', seconds: 4, desc: '店主抬头', characters: ['店主'], dialogue: '店主：一直在等你。' },
    { size: '', motion: '', seconds: 4, desc: '两人对望', characters: ['女孩', '店主'], dialogue: '' },
    { size: '', motion: '', seconds: 4, desc: '女孩愣住', characters: ['女孩'], dialogue: '女孩：等我？' },
  ];
  const CAST: TableCast[] = [
    { name: '女孩', look: '二十出头，黑色短发', sheet_prompt: '女孩的人物定妆照：二十出头，黑色短发。画面里只有这一个人' },
    { name: '店主', look: '七十岁，白发', sheet_prompt: '店主的人物定妆照：七十岁，白发。画面里只有这一个人' },
    { name: '路人', look: '中年男子', sheet_prompt: '路人的人物定妆照' },
  ];

  it('draws one look sheet per character the server wrote one for, feeding every frame they are in', () => {
    const table = newNode('tool', 100, 600);
    const { nodes, edges } = shotPairs(table, SHOTS4, [], CAST);
    const sheets = nodes.filter(node => String(node.payload.label).endsWith('·定妆'));
    expect(sheets.map(node => [node.kind, node.payload.label, node.payload.prompt])).toEqual([
      ['image_gen', '女孩·定妆', CAST[0].sheet_prompt], ['image_gen', '店主·定妆', CAST[1].sheet_prompt],
    ]);
    expect(sheets.every(sheet => sheet.y < table.y)).toBe(true);
    const frames = nodes.filter(node => String(node.payload.label).endsWith('首帧')).map(node => node.id);
    const fed = (sheet: string) => edges.filter(edge => edge.source === sheet && edge.payload.role === 'ref_image').map(edge => frames.indexOf(edge.target));
    expect(fed(sheets[0].id)).toEqual([0, 2, 3]);
    expect(fed(sheets[1].id)).toEqual([1, 2]);
    // No frame hands its framing on to another any more.
    expect(edges.some(edge => frames.includes(edge.source) && frames.includes(edge.target))).toBe(false);
  });

  it('draws no sheet for a character without one, or with no frame to feed', () => {
    expect(castSheets([{ node: newNode('image_gen', 0, 0), characters: ['女孩'] }], [{ name: '女孩', look: '短发' }], { x: 0, y: 0 }).nodes).toEqual([]);
    expect(castSheets([], CAST, { x: 0, y: 0 }).nodes).toEqual([]);
    expect(shotPairs(newNode('tool', 0, 0), SHOTS).edges.every(edge => edge.payload.role === 'first_frame')).toBe(true);
  });
});
