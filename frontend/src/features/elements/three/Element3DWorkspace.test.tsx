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
        // 主参考图是正面那张另存的一份，内容一样。
        files: [{ ...file('reference'), sha256: 'prop_front-sha' }, file('prop_front'), file('prop_back'), file('prop_side'), file('prop_in_use'), file('prop_board')],
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

  it('shows a scene as master, 45°, depth, detail and reverse views with the master as its reference', async () => {
    const file = (slot: string) => ({
      id: `study-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 2_048, sha256: `${slot}-sha`, url: `/media/elements/study-${slot}.png`,
    });
    const scenes: ElementItem[] = [
      {
        id: 'scene-views', kind: 'scene', name: '雨夜书房', description: '左侧木门，右侧花窗', status: 'ready', version: 2,
        metadata: {}, model3d: null,
        files: [{ ...file('reference'), sha256: 'scene_main-sha' }, file('scene_scale'), file('scene_main'), file('scene_45'), file('scene_depth'), file('scene_detail'), file('scene_reverse')],
        scene_scale: { text: '房间面宽约4.5米、房间进深约5.5米', source: 'table' },
      },
      {
        id: 'scene-no-scale', kind: 'scene', name: '客栈暗室', description: '约两丈见方', status: 'ready', version: 1,
        metadata: {}, model3d: null,
        files: [{ ...file('reference'), sha256: 'scene_main-sha' }, file('scene_main'), file('scene_45'), file('scene_depth'), file('scene_detail')],
        scene_scale: { text: '房间面宽约6.7米、房间进深约6.7米', source: 'description' },
      },
      {
        id: 'scene-legacy', kind: 'scene', name: '旧城门', description: '只有一张宽幅参考图', status: 'ready', version: 1,
        metadata: {}, model3d: null, files: [file('reference')],
      },
    ];
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster: vi.fn(), onInspectPoster: vi.fn(), onDrawSceneScale: vi.fn(), onDrawSceneReverse: vi.fn(),
    };
    const { rerender } = render(<Element3DWorkspace kind="scene" items={scenes} selectedId="scene-views" busy="" {...handlers} />);

    const strip = screen.getByRole('tablist', { name: '雨夜书房 视角' });
    expect(within(strip).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['人物比例', '主场景全景', '45°斜角', '纵深视角', '关键细节', '反打视角']);
    const preview = screen.getByRole('region', { name: '场景资产“雨夜书房”参考预览' });
    // The human-scale board opens first.
    expect(within(preview).getByRole('img', { name: '雨夜书房 人物比例' }).getAttribute('src')).toContain('study-scene_scale.png');
    expect(screen.getByText('房间面宽约4.5米、房间进深约5.5米')).toBeTruthy();
    expect(screen.getByText(/按场地类型估算/)).toBeTruthy();

    await userEvent.click(within(strip).getByRole('tab', { name: '纵深视角' }));
    expect(within(preview).getByRole('img', { name: '雨夜书房 纵深视角' }).getAttribute('src')).toContain('study-scene_depth.png');
    expect(within(screen.getByLabelText('参考图统计')).getByText('7 张')).toBeTruthy();

    // A scene drawn before the human-scale board offers to draw it from its panorama.
    rerender(<Element3DWorkspace kind="scene" items={scenes} selectedId="scene-no-scale" busy="" {...handlers} />);
    const noScale = screen.getByRole('tablist', { name: '客栈暗室 视角' });
    expect(within(screen.getByRole('region', { name: '场景资产“客栈暗室”参考预览' }))
      .getByRole('img', { name: '客栈暗室 主场景全景' })).toBeTruthy();
    await userEvent.click(within(noScale).getByRole('tab', { name: /点此生成人物比例/ }));
    expect(handlers.onDrawSceneScale).toHaveBeenCalledWith(scenes[1]);
    // …and the reverse view, drawn from the same panorama.
    await userEvent.click(within(noScale).getByRole('tab', { name: /点此生成反打视角/ }));
    expect(handlers.onDrawSceneReverse).toHaveBeenCalledWith(scenes[1]);
    expect(screen.getByText(/来自描述/)).toBeTruthy();

    // An older scene with only its single wide reference still previews it, and says how to get the views.
    rerender(<Element3DWorkspace kind="scene" items={scenes} selectedId="scene-legacy" busy="" {...handlers} />);
    const empty = screen.getByRole('tablist', { name: '旧城门 视角' });
    expect(within(empty).getAllByText('待生成')).toHaveLength(6);
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

  it('deletes the picture on show, not whichever file is the main reference', async () => {
    const file = (slot: string) => ({
      id: `study-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 2_048, sha256: `${slot}-sha`, url: `/media/elements/study-${slot}.png`,
    });
    const scene: ElementItem = {
      id: 'scene-views', kind: 'scene', name: '雨夜书房', description: '', status: 'ready', version: 2, metadata: {}, model3d: null,
      files: [file('reference'), file('scene_scale'), file('scene_main'), file('scene_45')],
    };
    const legacy: ElementItem = { ...scene, id: 'scene-legacy', name: '旧城门', files: [file('reference')] };
    const withModel: ElementItem = { ...scene, id: 'scene-model', name: '码头', model3d: items[0].model3d };
    const onDeletePoster = vi.fn();
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster, onInspectPoster: vi.fn(),
    };
    const all = [scene, legacy, withModel];
    const { rerender } = render(<Element3DWorkspace kind="scene" items={all} selectedId="scene-views" busy="" {...handlers} />);

    // The human-scale board is what opens, so that is what the button names and removes.
    await userEvent.click(screen.getByRole('button', { name: '删除这张：人物比例' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(scene, scene.files[1], '「人物比例」这张图');

    await userEvent.click(screen.getByRole('tab', { name: '45°斜角' }));
    await userEvent.click(screen.getByRole('button', { name: '删除这张：45°斜角' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(scene, scene.files[3], '「45°斜角」这张图');

    // While it runs, the button for that very picture carries the spinner state.
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-views" busy="delete-file:study-scene_45" {...handlers} />);
    const deleting = screen.getByRole('button', { name: '正在删除：45°斜角' });
    expect(deleting.getAttribute('aria-busy')).toBe('true');

    // The person's own upload is not a copy of any view, so it gets a place of its own and can be removed too.
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-views" busy="" {...handlers} />);
    const strip = screen.getByRole('tablist', { name: '雨夜书房 视角' });
    expect(within(strip).getAllByRole('tab').at(-1)?.textContent).toBe('主参考图');
    await userEvent.click(within(strip).getByRole('tab', { name: '主参考图' }));
    expect(screen.getByRole('img', { name: '雨夜书房 主参考图' }).getAttribute('src')).toContain('study-reference.png');
    await userEvent.click(screen.getByRole('button', { name: '删除这张：主参考图' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(scene, scene.files[0], '「主参考图」这张图');

    // A main reference that is only the stored copy of a view is not listed twice.
    const copied: ElementItem = { ...scene, id: 'scene-copied', name: '茶馆', files: [{ ...scene.files[0], sha256: 'scene_main-sha' }, ...scene.files.slice(1)] };
    rerender(<Element3DWorkspace kind="scene" items={[copied]} selectedId="scene-copied" busy="" {...handlers} />);
    expect(within(screen.getByRole('tablist', { name: '茶馆 视角' })).queryByRole('tab', { name: '主参考图' })).toBeNull();

    // No views yet: the single reference is on show.
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-legacy" busy="" {...handlers} />);
    expect(within(screen.getByRole('tablist', { name: '旧城门 视角' })).queryByRole('tab', { name: '主参考图' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '删除参考图' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(legacy, legacy.files[0], '参考图');

    // With a model on the stage no view is on show, so it is the main reference that goes.
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-model" busy="" {...handlers} />);
    await userEvent.click(screen.getByRole('button', { name: '删除参考图' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(withModel, withModel.files[0], '参考图');
  });

  it('lets an asset with a model go back to its reference views, and keeps the size controls', async () => {
    const file = (slot: string) => ({
      id: `dock-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 2_048, sha256: `${slot}-sha`, url: `/media/elements/dock-${slot}.png`,
    });
    const dock: ElementItem = {
      id: 'dock', kind: 'scene', name: '码头', description: '', status: 'ready', version: 2, metadata: {},
      model3d: items[0].model3d, files: [file('reference'), file('scene_scale'), file('scene_main'), file('scene_45')],
    };
    const sword: ElementItem = {
      id: 'sword', kind: 'prop', name: '长剑', description: '', status: 'ready', version: 1, metadata: {},
      model3d: items[0].model3d, files: [file('reference')], prop_scale: { longest_cm: 100, manual_cm: null, source: 'estimate' },
    };
    const onDeletePoster = vi.fn();
    const onSetPropSize = vi.fn();
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster, onInspectPoster: vi.fn(), onSetPropSize,
    };
    const all = [dock, items[0], items[1]];
    const { rerender } = render(<Element3DWorkspace kind="scene" items={all} selectedId="dock" busy="" {...handlers} />);

    // The model opens first, and the two choices say which one is on the stage.
    expect(screen.getByRole('img', { name: '码头 模型画布' })).toBeTruthy();
    const stageSwitch = screen.getByRole('group', { name: '主预览显示' });
    const showModel = within(stageSwitch).getByRole('button', { name: '看 3D 模型' });
    const showReference = within(stageSwitch).getByRole('button', { name: '看参考图' });
    expect(showModel.getAttribute('aria-pressed')).toBe('true');
    expect(showReference.getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('button', { name: '删除参考图' })).toBeTruthy();

    await userEvent.click(showReference);
    expect(screen.queryByRole('img', { name: '码头 模型画布' })).toBeNull();
    expect(showReference.getAttribute('aria-pressed')).toBe('true');
    const preview = screen.getByRole('region', { name: '场景资产“码头”参考预览' });
    expect(within(preview).getByRole('img', { name: '码头 人物比例' }).getAttribute('src')).toContain('dock-scene_scale.png');
    // The model is already there, so the preview does not ask for one again.
    expect(within(preview).queryByRole('button', { name: '上传 3D 模型' })).toBeNull();

    // Now a view is on show, so it is that view the delete button names and removes.
    await userEvent.click(screen.getByRole('tab', { name: '45°斜角' }));
    expect(within(preview).getByRole('img', { name: '码头 45°斜角' }).getAttribute('src')).toContain('dock-scene_45.png');
    await userEvent.click(screen.getByRole('button', { name: '删除这张：45°斜角' }));
    expect(onDeletePoster).toHaveBeenLastCalledWith(dock, dock.files[3], '「45°斜角」这张图');

    await userEvent.click(showModel);
    expect(screen.getByRole('img', { name: '码头 模型画布' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除参考图' })).toBeTruthy();

    // The choice belongs to the asset it was made on: another asset opens on its model again.
    await userEvent.click(showReference);
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-1" busy="" {...handlers} />);
    expect(screen.getByRole('img', { name: '雨夜巷口 模型画布' })).toBeTruthy();
    // Nothing to switch to without a reference image, or without a model.
    expect(screen.queryByRole('group', { name: '主预览显示' })).toBeNull();
    rerender(<Element3DWorkspace kind="scene" items={all} selectedId="scene-2" busy="" {...handlers} />);
    expect(screen.queryByRole('group', { name: '主预览显示' })).toBeNull();

    // A prop keeps its real-size field once it has a model.
    rerender(<Element3DWorkspace kind="prop" items={[sword]} selectedId="sword" busy="" {...handlers} />);
    expect(screen.getByRole('img', { name: '长剑 模型画布' })).toBeTruthy();
    expect(screen.getByText('184,332')).toBeTruthy();
    await userEvent.type(screen.getByRole('spinbutton', { name: /最长边/ }), '64{Enter}');
    expect(onSetPropSize).toHaveBeenCalledWith(sword, 64);
  });

  it('marks the one action that is running and keeps its name', () => {
    const file = (slot: string) => ({
      id: `inn-${slot}`, slot, mime_type: 'image/png', media_kind: 'image' as const,
      size_bytes: 2_048, sha256: `${slot}-sha`, url: `/media/elements/inn-${slot}.png`,
    });
    const scene: ElementItem = {
      id: 'inn', kind: 'scene', name: '客栈暗室', description: '', status: 'ready', version: 1, metadata: {}, model3d: null,
      files: [file('reference'), file('scene_main')],
    };
    const handlers = {
      onSelect: vi.fn(), onCreate: vi.fn(), onUploadModel: vi.fn(), onUploadPoster: vi.fn(), onRegenerate: vi.fn(),
      onDelete: vi.fn(), onDeletePoster: vi.fn(), onInspectPoster: vi.fn(), onDrawSceneScale: vi.fn(), onSetPropSize: vi.fn(),
    };
    const { rerender } = render(<Element3DWorkspace kind="scene" items={[scene]} selectedId="inn" busy="" {...handlers} />);
    const busyNames = () => screen.getAllByRole('button').concat(screen.getAllByRole('tab'))
      .filter(node => node.getAttribute('aria-busy') === 'true')
      .map(node => node.textContent?.trim());
    expect(busyNames()).toEqual([]);

    rerender(<Element3DWorkspace kind="scene" items={[scene]} selectedId="inn" busy="regenerate:inn" {...handlers} />);
    expect(screen.getByRole('button', { name: '重生成参考图' }).textContent).toContain('正在生成…');
    expect(busyNames()).toEqual(['正在生成…']);

    rerender(<Element3DWorkspace kind="scene" items={[scene]} selectedId="inn" busy="model:inn" {...handlers} />);
    expect(screen.getByRole('button', { name: '上传 GLB' }).textContent).toContain('上传中…');
    expect(screen.getByRole('button', { name: '上传 3D 模型' }).getAttribute('aria-busy')).toBe('true');

    rerender(<Element3DWorkspace kind="scene" items={[scene]} selectedId="inn" busy="upload:inn" {...handlers} />);
    expect(screen.getByRole('button', { name: '参考图' }).textContent).toContain('上传中…');
    expect(busyNames()).toEqual(['上传中…']);

    // Drawing the human-scale board from the panorama: the empty cell says so instead of 点此生成.
    rerender(<Element3DWorkspace kind="scene" items={[scene]} selectedId="inn" busy="scale:inn" {...handlers} />);
    expect(busyNames()).toEqual(['正在生成…人物比例']);

    const sword: ElementItem = {
      id: 'sword', kind: 'prop', name: '长剑', description: '', status: 'ready', version: 1, metadata: {}, model3d: null,
      files: [file('reference')], prop_scale: { longest_cm: 100, manual_cm: null, source: 'estimate' },
    };
    rerender(<Element3DWorkspace kind="prop" items={[sword]} selectedId="sword" busy="size:sword" {...handlers} />);
    expect(screen.getByRole('button', { name: '保存尺寸' }).textContent).toContain('正在保存…');
    expect(busyNames()).toEqual(['正在保存…']);
  });
});
