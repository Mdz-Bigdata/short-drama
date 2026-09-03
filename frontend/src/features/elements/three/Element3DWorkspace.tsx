import { lazy, Suspense, useMemo, useState } from 'react';
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

import { API_BASE } from '../../../api/client';
import { findPoster, formatFileSize, formatMetric, type ElementItem } from '../elementTypes';


const ElementModelViewport = lazy(() => import('./ElementModelViewport'));
const MuseumAssetExperience = lazy(() => import('../museum/MuseumAssetExperience'));

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
  onInspectPoster: (item: ElementItem) => void;
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
  const model = selected?.model3d;
  const stats = model?.stats ?? {};
  const label = kind === 'scene' ? '场景' : '道具';
  // 放大查看器沿用制片口径命名，与查看器标题里的类别一致。
  const viewerLabel = kind === 'scene' ? '拍摄场地' : '拍摄道具';
  const selectedDescription = selected?.description || (kind === 'scene'
    ? '补充空间布局、光线、时段与机位锚点。'
    : '补充材质、尺寸、状态与跨镜头连续性。');
  const locked = Boolean(busy);
  const KindIcon = kind === 'scene' ? Map : Package;

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
          <span><strong>项目资产</strong><small>{items.length} 项 · 私有鉴权</small></span>
        </button>
        <button
          type="button"
          className={view === 'museum' ? 'active museum' : 'museum'}
          aria-pressed={view === 'museum'}
          onClick={() => setView('museum')}
        >
          <Landmark size={15} />
          <span><strong>文物数字展厅</strong><small>8 件 · 内置 3D 馆藏</small></span>
        </button>
      </nav>

      {view === 'museum' ? (
        <Suspense fallback={<div className="museum-module-loader" role="status"><Layers3 className="spin" /> 正在开启文物数字展厅…</div>}>
          <MuseumAssetExperience kind={kind} />
        </Suspense>
      ) : (
        <section className="element-3d-workspace" aria-label={`${label} 3D 资产工作台`}>
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
                    {itemPoster?.url ? <img src={`${API_BASE}${itemPoster.url}`} alt="" /> : <KindIcon size={22} />}
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
          <button type="button" onClick={() => onUploadModel(selected?.id)} disabled={locked}><Upload size={15} /> 导入 GLB</button>
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
          <Suspense fallback={<div className="model-fetch-state" role="status"><Layers3 className="spin" /> 正在启动 3D 引擎…</div>}>
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
                onClick={() => onInspectPoster(selected)}
              >
                <img src={`${API_BASE}${poster.url}`} alt={`${selected.name} 参考图`} />
                <span className="element-preview__open-hint"><Maximize2 aria-hidden="true" /> 点击查看全景细节</span>
              </button>
              <span>2D REFERENCE</span>
            </div>
            <div className="asset-reference-preview__details">
              <div>
                <span>{label}参考资产 · VERSION {String(selected.version).padStart(2, '0')}</span>
                <h3>{selected.name}</h3>
                <p>{selectedDescription}</p>
              </div>
              <button type="button" onClick={() => onUploadModel(selected.id)} disabled={locked}><Upload size={16} /> 上传 3D 模型</button>
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
            ><ImagePlus size={16} /> 上传参考图</button>
          </div>
        )}
      </div>

      <aside className="asset-inspector">
        <div className="inspector-kicker"><KindIcon size={15} /> {label.toUpperCase()} / ASSET DETAIL</div>
        {selected ? (
          <>
            <div className="inspector-title">
              <div><h2>{selected.name}</h2><span>VERSION {String(selected.version).padStart(2, '0')}</span></div>
              <span className={`status-badge ${selected.status}`}>{model ? '3D 已就绪' : '待导入模型'}</span>
            </div>
            <p className="inspector-description">{selectedDescription}</p>

            <div className="inspector-section-title"><Layers3 size={14} /> 模型统计</div>
            <div className="model-stat-grid">
              <div><span>三角面</span><strong>{formatMetric(stats.triangles)}</strong></div>
              <div><span>顶点</span><strong>{formatMetric(stats.vertices)}</strong></div>
              <div><span>网格</span><strong>{formatMetric(stats.meshes)}</strong></div>
              <div><span>节点</span><strong>{formatMetric(stats.nodes)}</strong></div>
              <div><span>材质</span><strong>{formatMetric(stats.materials)}</strong></div>
              <div><span>贴图</span><strong>{formatMetric(stats.textures)}</strong></div>
              <div><span>绘制调用</span><strong>{formatMetric(stats.drawCalls)}</strong></div>
              <div><span>动画</span><strong>{formatMetric(stats.animations)}</strong></div>
            </div>

            <div className="asset-contract-list">
              <div><span>格式</span><strong>{model ? 'glTF 2.0 / GLB' : '—'}</strong></div>
              <div><span>文件大小</span><strong>{model ? formatFileSize(model.sizeBytes) : '—'}</strong></div>
              <div><span>坐标约定</span><strong>{model ? `${model.upAxis} Up · ${model.unit}` : '—'}</strong></div>
              <div><span>校验</span><strong>{model ? 'PASSED' : '—'}</strong></div>
            </div>

            {model?.validation.passed ? (
              <div className="model-quality passed"><CheckCircle2 size={16} /><div><strong>结构校验通过</strong><span>模型由受保护内容接口加载</span></div></div>
            ) : (
              <div className="model-quality"><AlertTriangle size={16} /><div><strong>缺少可预览模型</strong><span>参考图仍可继续使用</span></div></div>
            )}
            {model?.validation.warnings.map(warning => (
              <div className="model-warning" key={warning}><AlertTriangle size={14} /> {warning}</div>
            ))}

            <div className="inspector-actions">
              <button type="button" className="primary-action" onClick={() => onUploadModel(selected.id)} disabled={locked || busy === `model:${selected.id}`}>
                <Upload size={15} /> {model ? '替换 GLB' : '上传 GLB'}
              </button>
              <button type="button" onClick={() => onUploadPoster(selected.id)} disabled={locked}><ImagePlus size={15} /> 参考图</button>
              {poster && (
                <button type="button" className="danger-action" onClick={() => onDeletePoster(selected)} disabled={locked} aria-busy={busy === `delete-file:${poster.id}`}>
                  {busy === `delete-file:${poster.id}` ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                  {busy === `delete-file:${poster.id}` ? '正在删除参考图' : '删除参考图'}
                </button>
              )}
              <button type="button" onClick={() => onRegenerate(selected)} disabled={locked || busy === `regenerate:${selected.id}`}><RefreshCw size={15} /> 重生成参考图</button>
              <button type="button" className="danger-action asset-delete-action" onClick={() => onDelete(selected)} disabled={locked} aria-busy={busy === `delete:${selected.id}`}>
                {busy === `delete:${selected.id}` ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                {busy === `delete:${selected.id}` ? '正在删除资产' : '删除资产'}
              </button>
            </div>
          </>
        ) : (
          <div className="inspector-empty"><Database size={34} />选择或添加资产后查看模型详情</div>
        )}
      </aside>
        </section>
      )}
    </div>
  );
}
