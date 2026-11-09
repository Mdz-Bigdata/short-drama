import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type RefObject } from 'react';
import {
  AlertTriangle,
  Box,
  CheckCircle2,
  Database,
  ImagePlus,
  Landmark,
  Layers3,
  LockKeyhole,
  LoaderCircle,
  Map,
  Maximize2,
  Package,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';

import { apiUrl } from '../../../api/client';
import { findPoster, formatFileSize, formatMetric, propViews, sceneViews, type ElementFile, type ElementItem } from '../elementTypes';
import { t } from '../../../i18n';


const ElementModelViewport = lazy(() => import('./ElementModelViewport'));
const MuseumAssetExperience = lazy(() => import('../museum/MuseumAssetExperience'));

// 工作台占满页面剩下的高度：量出它在页面里的起点，底边落到窗口底部(留一点边)，窗口变了就重算。
const WORKSPACE_BOTTOM_GAP = 16;

function useFillViewportHeight<T extends HTMLElement>(remeasure: unknown): [RefObject<T | null>, string | undefined] {
  const ref = useRef<T | null>(null);
  const [height, setHeight] = useState<string>();
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || typeof window === 'undefined') return undefined;
    const update = () => {
      const top = Math.max(0, Math.round(node.getBoundingClientRect().top + window.scrollY));
      setHeight(`calc(100dvh - ${top + WORKSPACE_BOTTOM_GAP}px)`);
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
    // 从文物展厅切回项目资产时工作台是新挂上的节点，要重新量。
  }, [remeasure]);
  return [ref, height];
}

// 没导入 GLB 时，检查面板改为统计参考图本身：读出图片真实像素，再按常见画幅取名。
const ASPECT_NAMES: ReadonlyArray<readonly [ratio: number, label: string]> = [
  [21 / 9, '21:9'], [16 / 9, '16:9'], [3 / 2, '3:2'], [4 / 3, '4:3'], [1, '1:1'],
  [3 / 4, '3:4'], [2 / 3, '2:3'], [9 / 16, '9:16'],
];

function aspectLabel(width: number, height: number): string {
  const ratio = width / height;
  const named = ASPECT_NAMES.find(([value]) => Math.abs(ratio - value) / value < 0.02);
  return named ? named[1] : `${ratio.toFixed(2)}:1`;
}

function imageFormat(mime: string): string {
  const subtype = mime.split('/')[1]?.toUpperCase() ?? '';
  return subtype === 'JPG' ? 'JPEG' : subtype || '图片';
}

function useImageSize(url: string | undefined): { width: number; height: number } | null {
  const [size, setSize] = useState<{ url: string; width: number; height: number } | null>(null);
  useEffect(() => {
    if (!url) return undefined;
    let alive = true;
    const image = new Image();
    image.onload = () => {
      if (alive && image.naturalWidth && image.naturalHeight) {
        setSize({ url, width: image.naturalWidth, height: image.naturalHeight });
      }
    };
    image.src = url;
    return () => { alive = false; };
  }, [url]);
  return size && size.url === url ? size : null;
}

interface Props {
  kind: 'scene' | 'prop';
  items: ElementItem[];
  selectedId: string;
  busy: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onUploadModel: (id?: string) => void;
  onUploadPoster: (id?: string) => void;
  onRegenerate: (item: ElementItem) => void;
  onDelete: (item: ElementItem) => void;
  onDeletePoster: (item: ElementItem) => void;
  /** ``shown`` 是主预览里当前放的那张，放大时看的就是它。 */
  onInspectPoster: (item: ElementItem, shown?: ElementFile) => void;
  /** 改道具的最长边，``null`` 退回描述或估算。 */
  onSetPropSize?: (item: ElementItem, lengthCm: number | null) => void;
}

function PropSizeField({ item, locked, onSave }: { item: ElementItem; locked: boolean; onSave: (lengthCm: number | null) => void }) {
  const scale = item.prop_scale;
  const [draft, setDraft] = useState(scale?.manual_cm ? String(scale.manual_cm) : '');
  if (!scale) return null;
  const value = Number(draft);
  const valid = draft.trim() !== '' && value >= 0.5 && value <= 5000;
  const changed = valid && value !== scale.manual_cm;
  const hasBoard = item.files.some(file => file.slot === 'prop_board');
  const source = scale.source === 'manual'
    ? t('手动设置')
    : scale.source === 'description'
      ? t('来自描述：{0} cm', [String(scale.longest_cm)])
      : scale.source === 'table'
        ? t('来自道具标尺参照表：{0}', [scale.size_text || `${scale.longest_cm} cm`])
        : t('按物件类别估算：约 {0} cm', [String(scale.longest_cm)]);
  return (
    <form
      className="asset-prop-size"
      onSubmit={event => {
        event.preventDefault();
        if (changed && !locked) onSave(value);
      }}
    >
      <label>
        <span>{t('最长边')}</span>
        <input
          type="number"
          min={0.5}
          max={5000}
          step="any"
          inputMode="decimal"
          value={draft}
          placeholder={String(scale.longest_cm)}
          disabled={locked}
          onChange={event => setDraft(event.target.value)}
        />
        <span>cm</span>
      </label>
      <button type="submit" disabled={locked || !changed}>{t('保存尺寸')}</button>
      {scale.manual_cm !== null && (
        <button type="button" disabled={locked} onClick={() => onSave(null)}>{t('清除')}</button>
      )}
      <small>
        {source}
        {' · '}
        {hasBoard
          ? t('比例总览会立刻重画，不调用模型；手持或人形那格是模型画的，重生成才会变。')
          : t('下次生成参考图时使用。')}
      </small>
    </form>
  );
}


export default function Element3DWorkspace({
  kind,
  items,
  selectedId,
  busy,
  onSelect,
  onCreate,
  onUploadModel,
  onUploadPoster,
  onRegenerate,
  onDelete,
  onDeletePoster,
  onInspectPoster,
  onSetPropSize,
}: Props) {
  const [view, setView] = useState<'project' | 'museum'>('project');
  const [query, setQuery] = useState('');
  const selected = items.find(item => item.id === selectedId) ?? items[0];
  const visibleItems = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    if (!needle) return items;
    return items.filter(item => `${item.name} ${item.description}`.toLocaleLowerCase('zh-CN').includes(needle));
  }, [items, query]);
  const poster = selected ? findPoster(selected) : undefined;
  // 道具视图 / 场地四视角：选中哪一张就在主预览里放哪一张，换资产后回到第一张(比例总览 / 全景)。
  const [viewChoice, setViewChoice] = useState<{ itemId: string; slot: string } | null>(null);
  const selectedViews = selected ? (kind === 'prop' ? propViews(selected) : sceneViews(selected)) : [];
  const activeView = selectedViews.find(view => (
    view.file && viewChoice?.itemId === selected?.id && view.slot === viewChoice?.slot
  )) ?? selectedViews.find(view => view.file);
  const model = selected?.model3d;
  const stats = model?.stats ?? {};
  const referenceImages = selected?.files.filter(file => file.media_kind === 'image' && Boolean(file.url)) ?? [];
  const shownReference = activeView?.file ?? poster;
  const shownSize = useImageSize(shownReference?.url ? apiUrl(shownReference.url) : undefined);
  const filledViews = selectedViews.filter(view => view.file).length;
  const label = kind === 'scene' ? '场景' : '道具';
  // 放大查看器沿用制片口径命名，与查看器标题里的类别一致。
  const viewerLabel = kind === 'scene' ? '拍摄场地' : '拍摄道具';
  const selectedDescription = selected?.description || (kind === 'scene'
    ? '补充空间布局、光线、时段与机位锚点。'
    : '补充材质、尺寸、状态与跨镜头连续性。');
  const locked = Boolean(busy);
  const KindIcon = kind === 'scene' ? Map : Package;
  const [workspaceRef, workspaceHeight] = useFillViewportHeight<HTMLElement>(view);

  return (
    <div className="element-3d-module">
      <nav className="asset-mode-switch" aria-label={`${label} 3D 资产视图`}>
        <button
          type="button"
          className={view === 'project' ? 'active' : ''}
          aria-pressed={view === 'project'}
          onClick={() => setView('project')}
        >
          <LockKeyhole size={15} />
          <span><strong>{t('项目资产')}</strong><small>{items.length} 项 · 私有鉴权</small></span>
        </button>
        <button
          type="button"
          className={view === 'museum' ? 'active museum' : 'museum'}
          aria-pressed={view === 'museum'}
          onClick={() => setView('museum')}
        >
          <Landmark size={15} />
          <span><strong>{t('文物数字展厅')}</strong><small>{t('8 件 · 内置 3D 馆藏')}</small></span>
        </button>
      </nav>

      {view === 'museum' ? (
        <Suspense fallback={<div className="museum-module-loader" role="status"><Layers3 className="spin" /> {t('正在开启文物数字展厅…')}</div>}>
          <MuseumAssetExperience kind={kind} />
        </Suspense>
      ) : (
        <section
          ref={workspaceRef}
          className="element-3d-workspace"
          aria-label={`${label} 3D 资产工作台`}
          style={workspaceHeight ? ({ '--asset-workspace-height': workspaceHeight } as CSSProperties) : undefined}
        >
      <aside className="asset-rail">
        <div className="asset-rail-heading">
          <div><span>ASSET INDEX</span><strong>{label}资产</strong></div>
          <b>{String(items.length).padStart(2, '0')}</b>
        </div>
        <label className="asset-search">
          <Search size={15} />
          <span className="sr-only">搜索{label}资产</span>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder={`搜索${label}、描述…`} />
        </label>

        <div
          className="asset-rail-list"
          role="region"
          aria-label={`${label}资产列表，可上下滚动`}
          tabIndex={0}
        >
          {visibleItems.length === 0 ? (
            <div className="asset-rail-empty"><Database size={28} /><span>{items.length ? '没有匹配资产' : `还没有${label}资产`}</span></div>
          ) : visibleItems.map((item, index) => {
            const itemPoster = findPoster(item);
            // The rail's bin removes the whole asset — the entry it sits on —
            // not just that asset's reference image.
            const deletingAsset = busy === `delete:${item.id}`;
            return (
              <div
                key={item.id}
                className={`asset-rail-item${selected?.id === item.id ? ' active' : ''}`}
              >
                <button
                  type="button"
                  className="asset-rail-select"
                  aria-current={selected?.id === item.id ? 'true' : undefined}
                  aria-label={`查看${label}资产“${item.name}”`}
                  onClick={() => onSelect(item.id)}
                >
                  <span className="asset-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="asset-rail-thumb">
                    {itemPoster?.url ? <img src={apiUrl(itemPoster.url)} alt="" /> : <KindIcon size={22} />}
                  </span>
                  <span className="asset-rail-copy">
                    <strong>{item.name}</strong>
                    <small>v{item.version} · {item.model3d ? 'GLB READY' : item.files.length ? '2D ONLY' : 'EMPTY'}</small>
                  </span>
                  <i className={item.model3d ? 'has-model' : ''}>{item.model3d ? '3D' : '2D'}</i>
                </button>
                <button
                  type="button"
                  className="asset-rail-delete"
                  onClick={() => onDelete(item)}
                  disabled={locked}
                  aria-busy={deletingAsset}
                  aria-label={deletingAsset
                    ? `正在删除${label}资产“${item.name}”`
                    : `删除${label}资产“${item.name}”`}
                  title={`删除${label}资产`}
                >
                  {deletingAsset ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                </button>
              </div>
            );
          })}
        </div>

        <div className="asset-rail-actions">
          <button type="button" onClick={onCreate} disabled={locked}><Plus size={15} /> 新增{label}</button>
          <button type="button" onClick={() => onUploadModel(selected?.id)} disabled={locked}><Upload size={15} /> {t('导入 GLB')}</button>
        </div>
      </aside>

      <div className="asset-stage">
        <div className="asset-stage-chrome">
          <div><span>DATA ASSET / {kind.toUpperCase()}</span><strong>{selected?.name ?? `未选择${label}`}</strong></div>
          <div className="asset-live-status"><i /> {model ? 'MODEL ONLINE' : 'AWAITING MODEL'}</div>
        </div>

        {!selected ? (
          <div className="asset-stage-empty">
            <KindIcon size={64} />
            <span>建立第一项{label}资产后，即可导入 GLB 并在浏览器中检查空间与材质。</span>
            <button type="button" onClick={onCreate} disabled={locked}><Plus size={16} /> 添加{label}</button>
          </div>
        ) : model ? (
          <Suspense fallback={<div className="model-fetch-state" role="status"><Layers3 className="spin" /> {t('正在启动 3D 引擎…')}</div>}>
            <ElementModelViewport name={selected.name} contentUrl={model.contentUrl} posterUrl={poster?.url ?? undefined} />
          </Suspense>
        ) : poster?.url ? (
          <section
            className="asset-reference-preview"
            role="region"
            aria-label={`${label}资产“${selected.name}”参考预览`}
          >
            <div className="asset-reference-preview__media">
              <button
                type="button"
                className="asset-reference-preview__open"
                aria-label={`查看${viewerLabel}“${selected.name}”全景图`}
                onClick={() => onInspectPoster(selected, activeView?.file)}
              >
                <img
                  src={apiUrl(activeView?.file?.url ?? poster.url)}
                  alt={activeView?.file ? `${selected.name} ${activeView.label}` : `${selected.name} 参考图`}
                />
                <span className="element-preview__open-hint"><Maximize2 aria-hidden="true" /> {t('点击查看全景细节')}</span>
              </button>
              <span>2D REFERENCE</span>
            </div>
            <div
              className={`asset-prop-views${kind === 'scene' ? ' asset-prop-views--scene' : ''}`}
              role="tablist"
              aria-label={`${selected.name} ${kind === 'prop' ? '视图' : '四视角'}`}
            >
              {selectedViews.map(view => (
                <button
                  key={view.slot}
                  type="button"
                  role="tab"
                  aria-selected={activeView?.slot === view.slot}
                  className={activeView?.slot === view.slot ? 'is-active' : ''}
                  disabled={!view.file}
                  onClick={() => setViewChoice({ itemId: selected.id, slot: view.slot })}
                >
                  {view.file?.url
                    ? <img src={apiUrl(view.file.url)} alt="" />
                    : <span className="asset-prop-views__empty">{t('待生成')}</span>}
                  <small>{view.label}</small>
                </button>
              ))}
              {!selectedViews.some(view => view.file) && (
                <p className="asset-prop-views__hint">{kind === 'prop'
                  ? t('点「重生成参考图」按物件生成视图、比例尺和手或人形参照。')
                  : t('点「重生成参考图」生成主场景全景、45°斜角、纵深视角、关键细节四张空景视角。')}</p>
              )}
            </div>
            <div className="asset-reference-preview__details">
              <div>
                <span>{label}参考资产 · VERSION {String(selected.version).padStart(2, '0')}</span>
                <h3>{selected.name}</h3>
                <p>{selectedDescription}</p>
              </div>
              <button type="button" onClick={() => onUploadModel(selected.id)} disabled={locked}><Upload size={16} /> {t('上传 3D 模型')}</button>
            </div>
          </section>
        ) : (
          <div className="asset-stage-empty">
            <Box size={68} />
            <strong>{selected.name} 尚无参考图或 3D 模型</strong>
            <span>先上传对应的{label}参考图；如需空间检查，可继续导入自包含的 glTF 2.0 GLB。</span>
            <button
              type="button"
              aria-label={`为“${selected.name}”上传参考图`}
              onClick={() => onUploadPoster(selected.id)}
              disabled={locked}
            ><ImagePlus size={16} /> {t('上传参考图')}</button>
          </div>
        )}
      </div>

      <aside className="asset-inspector">
        <div className="inspector-kicker"><KindIcon size={15} /> {label.toUpperCase()} / ASSET DETAIL</div>
        {selected ? (
          <>
            <div className="inspector-title">
              <div><h2>{selected.name}</h2><span>VERSION {String(selected.version).padStart(2, '0')}</span></div>
              <span className={`status-badge ${selected.status}`}>{model ? t('3D 已就绪') : t('待导入模型')}</span>
            </div>
            <p className="inspector-description">{selectedDescription}</p>

            {model ? (
              <>
                <div className="inspector-section-title"><Layers3 size={14} /> {t('模型统计')}</div>
                <div className="model-stat-grid">
                  <div><span>{t('三角面')}</span><strong>{formatMetric(stats.triangles)}</strong></div>
                  <div><span>{t('顶点')}</span><strong>{formatMetric(stats.vertices)}</strong></div>
                  <div><span>{t('网格')}</span><strong>{formatMetric(stats.meshes)}</strong></div>
                  <div><span>{t('节点')}</span><strong>{formatMetric(stats.nodes)}</strong></div>
                  <div><span>{t('材质')}</span><strong>{formatMetric(stats.materials)}</strong></div>
                  <div><span>{t('贴图')}</span><strong>{formatMetric(stats.textures)}</strong></div>
                  <div><span>{t('绘制调用')}</span><strong>{formatMetric(stats.drawCalls)}</strong></div>
                  <div><span>{t('动画')}</span><strong>{formatMetric(stats.animations)}</strong></div>
                </div>

                <div className="asset-contract-list">
                  <div><span>{t('格式')}</span><strong>glTF 2.0 / GLB</strong></div>
                  <div><span>{t('文件大小')}</span><strong>{formatFileSize(model.sizeBytes)}</strong></div>
                  <div><span>{t('坐标约定')}</span><strong>{`${model.upAxis} Up · ${model.unit}`}</strong></div>
                  <div><span>{t('校验')}</span><strong>{model.validation.passed ? 'PASSED' : t('未通过')}</strong></div>
                </div>
              </>
            ) : (
              <>
                <div className="inspector-section-title"><Layers3 size={14} /> {t('参考图统计')}</div>
                <div className="model-stat-grid" aria-label={t('参考图统计')}>
                  <div><span>{t('参考图')}</span><strong>{t('{0} 张', [referenceImages.length])}</strong></div>
                  <div><span>{t('分辨率')}</span><strong>{shownSize ? `${shownSize.width}×${shownSize.height}` : '—'}</strong></div>
                  <div><span>{t('画幅')}</span><strong>{shownSize ? aspectLabel(shownSize.width, shownSize.height) : '—'}</strong></div>
                  <div><span>{t('像素')}</span><strong>{shownSize ? `${(shownSize.width * shownSize.height / 1e6).toFixed(1)} MP` : '—'}</strong></div>
                  {kind === 'prop' ? (
                    <div><span>{t('视图')}</span><strong>{String(filledViews)}</strong></div>
                  ) : (
                    <div><span>{t('资产版本')}</span><strong>{`V${String(selected.version).padStart(2, '0')}`}</strong></div>
                  )}
                  <div><span>{t('3D 模型')}</span><strong>{t('未导入')}</strong></div>
                </div>

                {kind === 'prop' && onSetPropSize && selected.prop_scale && (
                  <PropSizeField
                    key={`${selected.id}:${selected.prop_scale.manual_cm ?? ''}`}
                    item={selected}
                    locked={locked}
                    onSave={lengthCm => onSetPropSize(selected, lengthCm)}
                  />
                )}

                <div className="asset-contract-list">
                  <div><span>{t('格式')}</span><strong>{shownReference ? `${imageFormat(shownReference.mime_type)} · ${t('2D 参考')}` : '—'}</strong></div>
                  <div><span>{t('文件大小')}</span><strong>{shownReference ? formatFileSize(shownReference.size_bytes) : '—'}</strong></div>
                  <div><span>{t('坐标约定')}</span><strong>{t('导入 GLB 后确定')}</strong></div>
                  <div><span>{t('校验')}</span><strong>{shownReference ? t('参考图可用') : t('缺少参考图')}</strong></div>
                </div>
              </>
            )}

            {model?.validation.passed ? (
              <div className="model-quality passed"><CheckCircle2 size={16} /><div><strong>{t('结构校验通过')}</strong><span>{t('模型由受保护内容接口加载')}</span></div></div>
            ) : model ? (
              <div className="model-quality"><AlertTriangle size={16} /><div><strong>{t('模型结构校验未通过')}</strong><span>{t('请按下方提示修正后重新导入 GLB')}</span></div></div>
            ) : (
              <div className="model-quality"><AlertTriangle size={16} /><div>
                <strong>{shownReference ? t('尚未导入 3D 模型') : t('缺少参考图与 3D 模型')}</strong>
                <span>{shownReference
                  ? t('上传 GLB 后统计三角面、顶点、材质与动画；参考图可继续用于制作。')
                  : t('先上传或重生成参考图；需要空间检查时再导入 GLB。')}</span>
              </div></div>
            )}
            {model?.validation.warnings.map(warning => (
              <div className="model-warning" key={warning}><AlertTriangle size={14} /> {warning}</div>
            ))}

            <div className="inspector-actions">
              <button type="button" className="primary-action" onClick={() => onUploadModel(selected.id)} disabled={locked || busy === `model:${selected.id}`}>
                <Upload size={15} /> {model ? t('替换 GLB') : t('上传 GLB')}
              </button>
              <button type="button" onClick={() => onUploadPoster(selected.id)} disabled={locked}><ImagePlus size={15} /> {t('参考图')}</button>
              {poster && (
                <button type="button" className="danger-action" onClick={() => onDeletePoster(selected)} disabled={locked} aria-busy={busy === `delete-file:${poster.id}`}>
                  {busy === `delete-file:${poster.id}` ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                  {busy === `delete-file:${poster.id}` ? '正在删除参考图' : '删除参考图'}
                </button>
              )}
              <button type="button" onClick={() => onRegenerate(selected)} disabled={locked || busy === `regenerate:${selected.id}`}><RefreshCw size={15} /> {t('重生成参考图')}</button>
              <button type="button" className="danger-action asset-delete-action" onClick={() => onDelete(selected)} disabled={locked} aria-busy={busy === `delete:${selected.id}`}>
                {busy === `delete:${selected.id}` ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                {busy === `delete:${selected.id}` ? '正在删除资产' : '删除资产'}
              </button>
            </div>
          </>
        ) : (
          <div className="inspector-empty"><Database size={34} />{t('选择或添加资产后查看模型详情')}</div>
        )}
      </aside>
        </section>
      )}
    </div>
  );
}
