// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';

import { EXPORT_FORMAT, exportCanvas, exportFileName, importOffset, mergeImport, parseCanvasImport } from './canvasExport';
import { newNode } from './canvasGraph';
import type { CanvasDoc, CanvasNode, NodeKind } from './canvasTypes';

function node(id: string, kind: NodeKind, patch: Partial<CanvasNode> = {}): CanvasNode {
  return { ...newNode(kind, 0, 0), id, width: 100, height: 100, ...patch };
}

const doc: CanvasDoc = {
  nodes: [
    node('g', 'group', { x: -20, y: -40, width: 400, height: 300, payload: { label: '组' } }),
    node('a', 'image_gen', { payload: { prompt: 'p', groupId: 'g', committed: { marker: 'm' } } }),
    node('b', 'video_gen', { x: 200, payload: { groupId: 'g' } }),
    node('art', 'artifact', { x: 500, artifact_id: 'art-1', track: 'mainline' }),
  ],
  edges: [{ id: 'e1', source: 'a', target: 'b', kind: 'reference', payload: { role: 'first_frame' } }],
};

describe('exportCanvas', () => {
  it('writes a manifest with the title, view and current results', async () => {
    const blob = exportCanvas(doc, {
      title: '第一集', viewport: { x: 1, y: 2, zoom: 0.5 }, outputs: { a: { medium: 'image', url: '/media/a.png' } }, now: new Date('2026-01-02T03:04:05Z'),
    });
    expect(blob.type).toBe('application/json');
    const manifest = JSON.parse(await blob.text());
    expect(manifest).toMatchObject({ format: EXPORT_FORMAT, version: 1, title: '第一集', exported_at: '2026-01-02T03:04:05.000Z', viewport: { x: 1, y: 2, zoom: 0.5 } });
    expect(manifest.nodes.find((item: CanvasNode) => item.id === 'a').payload.output.url).toBe('/media/a.png');
    expect(manifest.edges).toHaveLength(1);
    expect(JSON.parse(await exportCanvas(doc, { title: 'x' }).text()).viewport).toBeNull();
  });

  it('names the file after the title', () => {
    expect(exportFileName('第一集 / 草稿')).toBe('第一集 草稿.novara-canvas.json');
    expect(exportFileName('  ')).toBe('画布.novara-canvas.json');
  });
});

describe('parseCanvasImport', () => {
  async function roundTrip() {
    return parseCanvasImport(await exportCanvas(doc, { title: '第一集', viewport: { x: 1, y: 2, zoom: 0.5 } }).text());
  }

  it('gives every node and edge a fresh id and follows them in edges and groups', async () => {
    const imported = await roundTrip();
    expect(imported.title).toBe('第一集');
    expect(imported.viewport).toEqual({ x: 1, y: 2, zoom: 0.5 });
    const ids = imported.doc.nodes.map(item => item.id);
    expect(ids.some(id => ['g', 'a', 'b', 'art'].includes(id))).toBe(false);
    const [group, a, b, art] = imported.doc.nodes;
    expect(a.payload.groupId).toBe(group.id);
    expect(b.payload.groupId).toBe(group.id);
    expect(a.payload.committed).toBeUndefined();
    expect(art.artifact_id).toBe('art-1');
    expect(art.track).toBe('freezone');
    const [link] = imported.doc.edges;
    expect(link).toMatchObject({ source: a.id, target: b.id, kind: 'reference', payload: { role: 'first_frame' } });
    expect(link.id).not.toBe('e1');
    // Twice is two independent copies.
    const again = await roundTrip();
    expect(again.doc.nodes.some(item => ids.includes(item.id))).toBe(false);
  });

  it('drops edges to missing nodes and memberships of missing groups, and fills sizes', () => {
    const text = JSON.stringify({
      format: EXPORT_FORMAT, version: 1, title: 't',
      nodes: [{ id: 'x', kind: 'note', x: 0, y: 0, payload: { groupId: 'nowhere' } }],
      edges: [{ id: 'e', source: 'x', target: 'gone', kind: 'dependency', payload: {} }],
      viewport: { x: 0, y: 0, zoom: 0 },
    });
    const imported = parseCanvasImport(text);
    expect(imported.doc.edges).toEqual([]);
    expect(imported.doc.nodes[0].payload.groupId).toBeUndefined();
    expect([imported.doc.nodes[0].width, imported.doc.nodes[0].height]).toEqual([240, 150]);
    expect(imported.viewport).toBeNull();
  });

  it('refuses what is not a canvas export, in Chinese', () => {
    const base = { format: EXPORT_FORMAT, version: 1, title: 't', edges: [] };
    expect(() => parseCanvasImport('not json')).toThrow('导入失败：文件不是有效的 JSON。');
    expect(() => parseCanvasImport(JSON.stringify({ format: 'other', nodes: [] }))).toThrow('导入失败：这不是画布导出文件。');
    expect(() => parseCanvasImport(JSON.stringify({ ...base, version: 2, nodes: [] }))).toThrow('导入失败：不支持的导出版本 2。');
    expect(() => parseCanvasImport(JSON.stringify({ ...base, nodes: [{ id: 'x', kind: 'spaceship', x: 0, y: 0 }] }))).toThrow('导入失败：不认识的节点类型「spaceship」。');
    expect(() => parseCanvasImport(JSON.stringify({ ...base, nodes: [{ id: 'x', kind: 'note' }] }))).toThrow('导入失败：第 1 个节点缺少位置。');
    expect(() => parseCanvasImport(JSON.stringify({ ...base, nodes: [{ id: 'x', kind: 'note', x: 0, y: 0 }, { id: 'x', kind: 'note', x: 0, y: 0 }] }))).toThrow('导入失败：节点编号「x」重复。');
    expect(() => parseCanvasImport(JSON.stringify({ ...base, nodes: 'none' }))).toThrow('导入失败：文件里缺少节点或连线列表。');
    expect(() => parseCanvasImport(JSON.stringify({
      ...base, nodes: [{ id: 'x', kind: 'note', x: 0, y: 0 }, { id: 'y', kind: 'image_gen', x: 0, y: 0 }], edges: [{ id: 'e', source: 'x', target: 'y', kind: 'teleport' }],
    }))).toThrow('导入失败：不认识的连线类型「teleport」。');
  });
});

describe('placing an import', () => {
  it('lands 120px right of what is there, top-aligned', async () => {
    const imported = parseCanvasImport(await exportCanvas(doc, { title: 't' }).text());
    const offset = importOffset(doc.nodes, imported.doc.nodes);
    // Existing content spans x -20..600 and starts at y -40; the import spans the same.
    expect(offset).toEqual({ dx: 600 + 120 - -20, dy: 0 });
    expect(importOffset([], imported.doc.nodes)).toEqual({ dx: 0, dy: 0 });
    const merged = mergeImport(doc, imported.doc, offset);
    expect(merged.ids).toHaveLength(4);
    expect(merged.doc.nodes[0].kind).toBe('group');
    expect(merged.doc.nodes[0].x).toBe(-20 + offset.dx);
    expect(merged.doc.edges).toHaveLength(2);
  });
});
