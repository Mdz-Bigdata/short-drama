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
  it('stretches the workbench from where it starts down to the bottom of the window', () => {
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 230, left: 0, right: 1200, bottom: 840, width: 1200, height: 610, x: 0, y: 230, toJSON: () => ({}),
    } as DOMRect);
    render(
      <Element3DWorkspace
        kind="scene" items={items} selectedId="scene-2" busy=""
        onSelect={vi.fn()} onCreate={vi.fn()} onUploadModel={vi.fn()} onUploadPoster={vi.fn()}
        onRegenerate={vi.fn()} onDelete={vi.fn()} onDeletePoster={vi.fn()} onInspectPoster={vi.fn()}
      />,
    );
    const workspace = screen.getByRole('region', { name: '场景 3D 资产工作台' });
    expect(workspace.style.getPropertyValue('--asset-workspace-height')).toBe('calc(100dvh - 246px)');
    rect.mockRestore();
  });

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

    // 没有 GLB：检查面板改为统计参考图本身，不再是一排破折号。
    expect(screen.queryByText('模型统计')).toBeNull();
    const referenceStats = screen.getByLabelText('参考图统计');
    expect(within(referenceStats).getByText('1 张')).toBeTruthy();
    expect(within(referenceStats).getByText('V01')).toBeTruthy();
    expect(within(referenceStats).getByText('未导入')).toBeTruthy();
    expect(screen.getByText('PNG · 2D 参考')).toBeTruthy();
    expect(screen.getByText('1.0 KB')).toBeTruthy();
    expect(screen.getByText('参考图可用')).toBeTruthy();
    expect(screen.getByText('尚未导入 3D 模型')).toBeTruthy();
  });

  it('shows a prop as front, left 45°, right 45° and back views and swaps the main preview', async () => {
    const file = (slot: string) => ({
      id: `token-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 1_024, sha256: `${slot}-sha`, url: `/media/elements/token-${slot}.png`,
    });
    const props: ElementItem[] = [
      {
        id: 'prop-1', kind: 'prop', name: '青铜令牌', description: '正面虎纹', status: 'ready', version: 3,
        metadata: {}, model3d: null,
        files: [file('reference'), file('prop_front'), file('prop_back'), file('prop_side'), file('prop_in_use'), file('prop_board')],
      },
      {
        id: 'prop-2', kind: 'prop', name: '旧钥匙', description: '只有一张参考图', status: 'ready', version: 1,
        metadata: {}, model3d: null, files: [file('reference')],
      },
    ];
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster: vi.fn(), onInspectPoster: vi.fn(),
    };
    const { rerender } = render(<Element3DWorkspace kind="prop" items={props} selectedId="prop-1" busy="" {...handlers} />);

    const strip = screen.getByRole('tablist', { name: '青铜令牌 视图' });
    expect(within(strip).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['比例总览', '正面', '侧面', '背面', '比例参照']);
    const preview = screen.getByRole('region', { name: '道具资产“青铜令牌”参考预览' });
    expect(within(preview).getByRole('img', { name: '青铜令牌 比例总览' }).getAttribute('src')).toContain('token-prop_board.png');

    await userEvent.click(within(preview).getByRole('button', { name: /全景图/ }));
    expect(handlers.onInspectPoster.mock.calls[0][1].slot).toBe('prop_board');

    await userEvent.click(within(strip).getByRole('tab', { name: '背面' }));
    expect(within(preview).getByRole('img', { name: '青铜令牌 背面' }).getAttribute('src')).toContain('token-prop_back.png');

    rerender(<Element3DWorkspace kind="prop" items={props} selectedId="prop-2" busy="" {...handlers} />);
    const empty = screen.getByRole('tablist', { name: '旧钥匙 视图' });
    expect(within(empty).getAllByText('待生成')).toHaveLength(1);
    expect(within(empty).getByText(/按物件生成视图、比例尺和手或人形参照/)).toBeTruthy();
    expect(within(screen.getByLabelText('参考图统计')).getByText('0')).toBeTruthy();
  });

  it('shows a scene as master, 45°, depth and detail views with the master as its reference', async () => {
    const file = (slot: string) => ({
      id: `study-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 2_048, sha256: `${slot}-sha`, url: `/media/elements/study-${slot}.png`,
    });
    const scenes: ElementItem[] = [
      {
        id: 'scene-views', kind: 'scene', name: '雨夜书房', description: '左侧木门，右侧花窗', status: 'ready', version: 2,
        metadata: {}, model3d: null,
        files: [file('reference'), file('scene_main'), file('scene_45'), file('scene_depth'), file('scene_detail')],
      },
      {
        id: 'scene-legacy', kind: 'scene', name: '旧城门', description: '只有一张宽幅参考图', status: 'ready', version: 1,
        metadata: {}, model3d: null, files: [file('reference')],
      },
    ];
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster: vi.fn(), onInspectPoster: vi.fn(),
    };
    const { rerender } = render(<Element3DWorkspace kind="scene" items={scenes} selectedId="scene-views" busy="" {...handlers} />);

    const strip = screen.getByRole('tablist', { name: '雨夜书房 四视角' });
    expect(within(strip).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['主场景全景', '45°斜角', '纵深视角', '关键细节']);
    const preview = screen.getByRole('region', { name: '场景资产“雨夜书房”参考预览' });
    expect(within(preview).getByRole('img', { name: '雨夜书房 主场景全景' }).getAttribute('src')).toContain('study-scene_main.png');

    await userEvent.click(within(strip).getByRole('tab', { name: '纵深视角' }));
    expect(within(preview).getByRole('img', { name: '雨夜书房 纵深视角' }).getAttribute('src')).toContain('study-scene_depth.png');
    expect(within(screen.getByLabelText('参考图统计')).getByText('5 张')).toBeTruthy();

    // An older scene with only its single wide reference still previews it, and says how to get the views.
    rerender(<Element3DWorkspace kind="scene" items={scenes} selectedId="scene-legacy" busy="" {...handlers} />);
    const empty = screen.getByRole('tablist', { name: '旧城门 四视角' });
    expect(within(empty).getAllByText('待生成')).toHaveLength(4);
    expect(within(empty).getByText(/生成主场景全景、45°斜角、纵深视角、关键细节四张空景视角/)).toBeTruthy();
    expect(screen.getByRole('img', { name: '旧城门 参考图' }).getAttribute('src')).toContain('study-reference.png');
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

  it('lets a prop\'s longest side be set, saved and cleared', async () => {
    const image = (slot: string) => ({
      id: slot, slot, media_kind: 'image', mime_type: 'image/png', url: `/m/${slot}.png`, size_bytes: 10,
    }) as ElementItem['files'][number];
    const prop = (scale: ElementItem['prop_scale'], slots: string[]): ElementItem => ({
      id: 'sword', kind: 'prop', name: '长剑', description: '', status: 'ready', version: 1, metadata: {}, model3d: null,
      files: slots.map(image), prop_scale: scale,
    });
    const onSetPropSize = vi.fn();
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster: vi.fn(), onInspectPoster: vi.fn(), onSetPropSize,
    };
    const estimated = prop({ longest_cm: 100, manual_cm: null, source: 'estimate' }, ['reference', 'prop_board']);
    const { rerender } = render(<Element3DWorkspace kind="prop" items={[estimated]} selectedId="sword" busy="" {...handlers} />);

    const input = screen.getByRole('spinbutton', { name: /最长边/ }) as HTMLInputElement;
    expect(input.placeholder).toBe('100');
    expect(screen.getByText(/按物件类别估算：约 100 cm/)).toBeTruthy();
    expect(screen.getByText(/比例总览会立刻重画/)).toBeTruthy();
    const save = screen.getByRole('button', { name: '保存尺寸' });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: '清除' })).toBeNull();

    await userEvent.type(input, '0.1');
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await userEvent.clear(input);
    await userEvent.type(input, '64{Enter}');
    expect(onSetPropSize).toHaveBeenCalledWith(estimated, 64);

    const manual = prop({ longest_cm: 64, manual_cm: 64, source: 'manual' }, ['reference']);
    rerender(<Element3DWorkspace kind="prop" items={[manual]} selectedId="sword" busy="" {...handlers} />);
    expect((screen.getByRole('spinbutton', { name: /最长边/ }) as HTMLInputElement).value).toBe('64');
    expect(screen.getByText(/下次生成参考图时使用/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '清除' }));
    expect(onSetPropSize).toHaveBeenLastCalledWith(manual, null);
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
