import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Boxes, Camera, ImagePlus, LoaderCircle, Plus, RefreshCw, Upload } from 'lucide-react';

import { API_BASE, apiRequest } from '../../api/client';


export type ElementKind = 'actor' | 'prop' | 'scene' | 'effect';

interface ElementFile {
  id: string;
  slot: string;
  url: string;
}

interface ElementItem {
  id: string;
  kind: ElementKind;
  name: string;
  description: string;
  status: string;
  version: number;
  files: ElementFile[];
}

interface ElementResponse {
  items: ElementItem[];
  total: number;
}

interface Props {
  initialKind: ElementKind;
  onBack: () => void;
}


const kindMeta: Record<ElementKind, { label: string; hint: string }> = {
  actor: { label: '演员', hint: '演员必须完成正面、正面 3/4、侧面、背面 3/4、背面五视图' },
  prop: { label: '道具', hint: '记录归属、位置、状态、材质与跨镜头连续性' },
  scene: { label: '场景', hint: '记录空间布局、时段、天气、灯光与机位锚点' },
  effect: { label: '特效', hint: '记录作用目标、时间、影响区域与结束状态' },
};

const actorSlots = [
  ['front', '正面'],
  ['front_three_quarter', '正面 3/4'],
  ['profile', '侧面'],
  ['rear_three_quarter', '背面 3/4'],
  ['back', '背面'],
];


export function ElementLibraryPage({ initialKind, onBack }: Props) {
  const [kind, setKind] = useState<ElementKind>(initialKind);
  const [items, setItems] = useState<ElementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [uploadTarget, setUploadTarget] = useState<string>('');
  const [uploadSlot, setUploadSlot] = useState('reference');
  const fileInput = useRef<HTMLInputElement>(null);

  const load = async (targetKind = kind) => {
    setLoading(true);
    setError('');
    try {
      const data = await apiRequest<ElementResponse>(`/api/elements?kind=${targetKind}&page=1&page_size=50`);
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '元素库加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(kind); }, 0);
    return () => window.clearTimeout(handle);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps -- reload when the concrete element route changes

  const selectKind = (next: ElementKind) => {
    setKind(next);
    setShowForm(false);
    setUploadTarget('');
    setUploadSlot(next === 'actor' ? 'front' : 'reference');
  };

  const addElement = async () => {
    if (!name.trim()) return;
    setBusy('create');
    setError('');
    try {
      await apiRequest('/api/elements', {
        method: 'POST',
        body: JSON.stringify({ kind, name: name.trim(), description: description.trim(), metadata: {} }),
      });
      setName('');
      setDescription('');
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加失败');
    } finally {
      setBusy('');
    }
  };

  const beginUpload = (elementId?: string) => {
    const target = elementId || items[0]?.id;
    if (!target) {
      setShowForm(true);
      setError('请先添加一个元素，再上传参考图。');
      return;
    }
    setUploadTarget(target);
    fileInput.current?.click();
  };

  const uploadFile = async (file?: File) => {
    if (!file || !uploadTarget) return;
    const form = new FormData();
    form.append('slot', kind === 'actor' ? uploadSlot : `reference-${Date.now()}`);
    form.append('file', file);
    setBusy(`upload:${uploadTarget}`);
    setError('');
    try {
      await apiRequest(`/api/elements/${uploadTarget}/files`, { method: 'POST', body: form });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setBusy('');
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const regenerate = async (item: ElementItem) => {
    setBusy(`regenerate:${item.id}`);
    setError('');
    try {
      await apiRequest(`/api/elements/${item.id}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ prompt: `保持 ${item.name} 的身份、状态和视觉锚点，重新生成当前版本` }),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新生成请求失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <main className="portal-page">
      <header className="portal-header">
        <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> 返回创作台</button>
        <div>
          <span className="eyebrow">ELEMENT LIBRARY</span>
          <h1>{kindMeta[kind].label}元素库</h1>
          <p>{kindMeta[kind].hint}</p>
        </div>
        <Boxes size={34} className="portal-mark" />
      </header>

      <div className="element-tabs" role="tablist" aria-label="元素类型">
        {(Object.keys(kindMeta) as ElementKind[]).map(value => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={kind === value}
            className={kind === value ? 'active' : ''}
            onClick={() => selectKind(value)}
          >{kindMeta[value].label}</button>
        ))}
      </div>

      <section className="element-toolbar">
        <div><strong>{items.length}</strong><span> 个{kindMeta[kind].label}元素</span></div>
        <div>
          {kind === 'actor' && (
            <label className="slot-select">上传视图
              <select value={uploadSlot} onChange={event => setUploadSlot(event.target.value)}>
                {actorSlots.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          )}
          <button type="button" className="secondary-action" onClick={() => beginUpload()}><Upload size={16} /> 上传</button>
          <button type="button" className="primary-action" onClick={() => setShowForm(value => !value)}><Plus size={16} /> 添加{kindMeta[kind].label}</button>
          <input ref={fileInput} hidden type="file" accept=".png,.jpg,.jpeg,.webp" onChange={event => void uploadFile(event.target.files?.[0])} />
        </div>
      </section>

      {showForm && (
        <section className="element-create-form">
          <label>名称<input value={name} onChange={event => setName(event.target.value)} placeholder={`输入${kindMeta[kind].label}名称`} /></label>
          <label>描述<textarea value={description} onChange={event => setDescription(event.target.value)} placeholder="身份、状态、材质、空间或效果约束" /></label>
          <button type="button" className="primary-action" onClick={() => void addElement()} disabled={!name.trim() || busy === 'create'}>
            {busy === 'create' ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />} 保存元素
          </button>
        </section>
      )}

      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? (
        <div className="empty-library"><LoaderCircle className="spin" /> 正在加载{kindMeta[kind].label}库…</div>
      ) : items.length === 0 ? (
        <div className="empty-library"><ImagePlus size={44} /><strong>还没有{kindMeta[kind].label}元素</strong><span>点击“添加{kindMeta[kind].label}”建立版本化资产，再上传参考图。</span></div>
      ) : (
        <div className="element-card-grid">
          {items.map(item => (
            <article className="element-card" key={item.id}>
              <div className="element-preview">
                {item.files[0] ? <img src={`${API_BASE}${item.files[0].url}`} alt={`${item.name} ${item.files[0].slot}`} /> : <Camera size={34} />}
                <span className={`status-badge ${item.status}`}>{item.status === 'ready' ? '已就绪' : '待完善'}</span>
              </div>
              <div className="element-card-body">
                <div><h2>{item.name}</h2><span>v{item.version}</span></div>
                <p>{item.description || kindMeta[kind].hint}</p>
                {kind === 'actor' && <small>五视图 {item.files.length}/5</small>}
                <div className="element-actions">
                  <button type="button" onClick={() => beginUpload(item.id)}><Upload size={14} /> 添加上传</button>
                  <button type="button" onClick={() => void regenerate(item)} disabled={busy === `regenerate:${item.id}`}><RefreshCw size={14} /> 重新生成</button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
