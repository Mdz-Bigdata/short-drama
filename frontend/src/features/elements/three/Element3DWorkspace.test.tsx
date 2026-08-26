// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
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
    files: [],
    model3d: null,
  },
];

afterEach(cleanup);


describe('Element3DWorkspace', () => {
  it('renders one selected model, server stats and a graceful missing-model state', async () => {
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
      />,
    );

    expect(await screen.findByRole('img', { name: '雨夜巷口 模型画布' })).toBeTruthy();
    expect(screen.getByText('184,332')).toBeTruthy();
    expect(screen.getByText('16')).toBeTruthy();
    expect(screen.getByText('结构校验通过')).toBeTruthy();
    expect(screen.getByText('建议将 Web 展示模型优化到 5 MB 以下')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: /旧车站月台/ }));
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
      />,
    );
    expect(screen.getByText('旧车站月台 尚未绑定 3D 模型')).toBeTruthy();
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
      />,
    );

    expect(await screen.findByRole('img', { name: '雨夜巷口 模型画布' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /文物数字展厅/ }));

    expect(await screen.findByRole('region', { name: 'prop 文物数字展厅' })).toBeTruthy();
    expect(screen.queryByRole('img', { name: '雨夜巷口 模型画布' })).toBeNull();
  });
});
