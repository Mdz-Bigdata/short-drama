// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ElementItem } from '../elementTypes';
import Element3DWorkspace from './Element3DWorkspace';


vi.mock('./ElementModelViewport', () => ({
  default: ({ name }: { name: string }) => <div role="img" aria-label={`${name} 模型画布`}>mock 3D canvas</div>,
}));

vi.mock('../museum/MuseumAssetExperience', () => ({
  default: ({ kind }: { kind: 'scene' | 'prop' }) => <div role="region" aria-label={`${kind} 文物数字展厅`}>八件内置馆藏</div>,
}));

const items: ElementItem[] = [
  {
    id: 'scene-1',
    kind: 'scene',
    name: '雨夜巷口',
    description: '狭窄巷道与潮湿地面',
    status: 'ready',
    version: 4,
    metadata: {},
    files: [],
    model3d: {
      schemaVersion: 'element-model.v1',
      state: 'ready',
      format: 'glb',
      contentUrl: '/api/elements/scene-1/model/content?v=4',
      sha256: 'abc',
      sizeBytes: 6 * 1024 * 1024,
      unit: 'meter',
      upAxis: 'Y',
      stats: {
        nodes: 21, meshes: 8, vertices: 120_000, triangles: 184_332,
        materials: 9, textures: 12, animations: 0, drawCalls: 16,
      },
      validation: { passed: true, warnings: ['建议将 Web 展示模型优化到 5 MB 以下'] },
    },
  },
  {
    id: 'scene-2',
    kind: 'scene',
    name: '旧车站月台',
    description: '清晨薄雾',
    status: 'draft',
    version: 1,
    metadata: {},
    files: [{
      id: 'scene-2-poster',
      slot: 'reference',
      mime_type: 'image/png',
      media_kind: 'image',
      size_bytes: 1_024,
      sha256: 'scene-2-poster-sha',
      url: '/media/elements/scene-2.png',
    }],
    model3d: null,
  },
];

afterEach(cleanup);


describe('Element3DWorkspace', () => {
  it('renders one selected model, server stats and the selected reference preview', async () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <Element3DWorkspace
        kind="scene"
        items={items}
        selectedId="scene-1"
        busy=""
        onSelect={onSelect}
        onCreate={vi.fn()}
        onUploadModel={vi.fn()}
        onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={vi.fn()}
        onDeletePoster={vi.fn()}
        onInspectPoster={vi.fn()}
      />,
    );

    expect(await screen.findByRole('img', { name: '雨夜巷口 模型画布' })).toBeTruthy();
    expect(screen.getByText('184,332')).toBeTruthy();
    expect(screen.getByText('16')).toBeTruthy();
    expect(screen.getByText('结构校验通过')).toBeTruthy();
    expect(screen.getByText('建议将 Web 展示模型优化到 5 MB 以下')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: '查看场景资产“旧车站月台”' }));
    expect(onSelect).toHaveBeenCalledWith('scene-2');
    rerender(
      <Element3DWorkspace
        kind="scene"
        items={items}
        selectedId="scene-2"
        busy=""
        onSelect={onSelect}
        onCreate={vi.fn()}
        onUploadModel={vi.fn()}
        onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={vi.fn()}
        onDeletePoster={vi.fn()}
        onInspectPoster={vi.fn()}
      />,
    );
    const preview = screen.getByRole('region', { name: '场景资产“旧车站月台”参考预览' });
    expect(within(preview).getByRole('img', { name: '旧车站月台 参考图' })).toBeTruthy();
    expect(within(preview).getByText('清晨薄雾')).toBeTruthy();
  });

  it('opens the integrated museum without mounting the private project viewer at the same time', async () => {
    render(
      <Element3DWorkspace
        kind="prop"
        items={items.map(item => ({ ...item, kind: 'prop' as const }))}
        selectedId="scene-1"
        busy=""
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onUploadModel={vi.fn()}
        onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={vi.fn()}
        onDeletePoster={vi.fn()}
        onInspectPoster={vi.fn()}
      />,
    );

    expect(await screen.findByRole('img', { name: '雨夜巷口 模型画布' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /文物数字展厅/ }));

    expect(await screen.findByRole('region', { name: 'prop 文物数字展厅' })).toBeTruthy();
    expect(screen.queryByRole('img', { name: '雨夜巷口 模型画布' })).toBeNull();
  });

  it('deletes the whole asset from the rail bin without selecting it', async () => {
    const propItems = items.map(item => ({ ...item, kind: 'prop' as const }));
    const onSelect = vi.fn();
    const onDelete = vi.fn();
    const onDeletePoster = vi.fn();
    render(
      <Element3DWorkspace
        kind="prop"
        items={propItems}
        selectedId="scene-1"
        busy=""
        onSelect={onSelect}
        onCreate={vi.fn()}
        onUploadModel={vi.fn()}
        onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={onDelete}
        onDeletePoster={onDeletePoster}
        onInspectPoster={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: '删除道具资产“旧车站月台”' }));

    // The bin removes the entry it sits on, not just that entry's image.
    expect(onDelete).toHaveBeenCalledWith(propItems[1]);
    expect(onDeletePoster).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('offers the rail bin even for an asset that has no reference image', async () => {
    const bare = [{ ...items[0], id: 'bare-1', name: '空道具', kind: 'prop' as const, files: [], model3d: null }];
    const onDelete = vi.fn();
    render(
      <Element3DWorkspace
        kind="prop"
        items={bare}
        selectedId="bare-1"
        busy=""
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onUploadModel={vi.fn()}
        onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={onDelete}
        onDeletePoster={vi.fn()}
        onInspectPoster={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: '删除道具资产“空道具”' }));
    expect(onDelete).toHaveBeenCalledWith(bare[0]);
  });
});
