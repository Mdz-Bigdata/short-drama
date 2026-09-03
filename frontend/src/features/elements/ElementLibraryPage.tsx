import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Boxes, Camera, FileSearch, ImagePlus, LoaderCircle, Maximize2, Pencil, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';

import { API_BASE, apiRequest } from '../../api/client';
import AssetImageViewer, { type AssetImageViewerAsset } from './AssetImageViewer';
import { findPoster, findViewImage, type ElementFile, type ElementItem, type ElementKind } from './elementTypes';
import './ElementLibraryPage.css';


export type { ElementKind } from './elementTypes';

const Element3DWorkspace = lazy(() => import('./three/Element3DWorkspace'));

interface ElementResponse {
  items: ElementItem[];
  total: number;
}

interface Props {
  initialKind: ElementKind;
  onBack?: () => void;
  embedded?: boolean;
  taskId?: string;
  onCountChange?: (kind: ElementKind, total: number) => void;
  regenerateAllToken?: number;
  onGenerationStateChange?: (generating: boolean) => void;
}

interface ExtractionResult {
  kind: ElementKind;
  created: number;
  skipped: number;
  with_image?: number;
}

interface GenerationJob {
  id: string;
  kind: ElementKind;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed';
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  remaining: number;
  errors: Array<{ element_id: string; name: string; detail: string }>;
}

interface PendingUpload {
  type: 'image' | 'model';
  file: File;
  slot: string;
  workflowId: number;
  target?: {
    id: string;
    kind: ElementKind;
  };
}


const kindMeta: Record<ElementKind, { label: string; hint: string }> = {
  actor: { label: '演员', hint: '演员必须完成正面、正面 3/4、侧面、背面 3/4、背面五视图' },
  scene: { label: '场景', hint: '记录空间布局、时段、天气、灯光与机位锚点' },
  prop: { label: '道具', hint: '记录归属、位置、状态、材质与跨镜头连续性' },
  costume: { label: '服装', hint: '记录角色、造型状态、材质、换装节点与镜头连续性' },
  effect: { label: '特效', hint: '记录作用目标、时间、影响区域与结束状态' },
};

const actorSlots = [
  ['front', '正面'],
  ['front_three_quarter', '正面 3/4'],
  ['profile', '侧面'],
  ['rear_three_quarter', '背面 3/4'],
  ['back', '背面'],
];

function actorSlotLabel(slot: string): string {
  return actorSlots.find(([value]) => value === slot)?.[1] || '正面';
}


export function ElementLibraryPage({
  initialKind,
  onBack,
  embedded = false,
  taskId,
  onCountChange,
  regenerateAllToken = 0,
  onGenerationStateChange,
}: Props) {
  const [kind, setKind] = useState<ElementKind>(initialKind);
  const [items, setItems] = useState<ElementItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [uploadTarget, setUploadTarget] = useState<string>('');
  const [uploadSlot, setUploadSlot] = useState(initialKind === 'actor' ? 'front' : 'reference');
  const [pendingUpload, setPendingUpload] = useState<PendingUpload | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [imageViewerAsset, setImageViewerAsset] = useState<AssetImageViewerAsset | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const modelInput = useRef<HTMLInputElement>(null);
  const toolbarImageButton = useRef<HTMLButtonElement>(null);
  const toolbarCreateButton = useRef<HTMLButtonElement>(null);
  const createForm = useRef<HTMLElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const kindRef = useRef<ElementKind>(initialKind);
  const loadSequence = useRef(0);
  const uploadWorkflow = useRef(0);
  const creatingRef = useRef(false);
  const busyRef = useRef('');
  const generationSequence = useRef(0);
  const lastRegenerateAllToken = useRef(regenerateAllToken);

  const setCreateInFlight = (value: boolean) => {
    creatingRef.current = value;
    setCreating(value);
  };

  const startMutation = (key: string) => {
    if (busyRef.current) return false;
    busyRef.current = key;
    setBusy(key);
    setNotice('');
    return true;
  };

  const finishMutation = (key: string) => {
    if (busyRef.current !== key) return;
    busyRef.current = '';
    setBusy(current => current === key ? '' : current);
  };

  const load = async (targetKind = kind) => {
    if (targetKind !== kindRef.current) return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const data = await apiRequest<ElementResponse>(`/api/elements?kind=${targetKind}&page=1&page_size=50`);
      if (sequence !== loadSequence.current || targetKind !== kindRef.current) return;
      const nextTotal = Number.isFinite(data.total) ? data.total : data.items.length;
      setItems(data.items);
      setTotal(nextTotal);
      onCountChange?.(targetKind, nextTotal);
      setSelectedId(current => data.items.some(item => item.id === current) ? current : (data.items[0]?.id ?? ''));
    } catch (err) {
      if (sequence !== loadSequence.current || targetKind !== kindRef.current) return;
      setError(err instanceof Error ? err.message : '元素库加载失败');
    } finally {
      if (sequence === loadSequence.current && targetKind === kindRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(kind); }, 0);
    return () => window.clearTimeout(handle);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps -- reload when the concrete element route changes

  useEffect(() => {
    if (!showForm) return;
    const handle = window.setTimeout(() => {
      createForm.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      nameInput.current?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(handle);
  }, [showForm]);

  const selectKind = (next: ElementKind) => {
    if (next === kindRef.current) return;
    kindRef.current = next;
    loadSequence.current += 1;
    setKind(next);
    setItems([]);
    setTotal(0);
    setLoading(true);
    setShowForm(false);
    uploadWorkflow.current += 1;
    setError('');
    setNotice('');
    setName('');
    setDescription('');
    setUploadTarget('');
    setPendingUpload(null);
    setSelectedId('');
    setImageViewerAsset(null);
    setUploadSlot(next === 'actor' ? 'front' : 'reference');
  };

  const sendUpload = async (pending: PendingUpload, target: string, targetKind: ElementKind) => {
    const form = new FormData();
    if (pending.type === 'image') {
      form.append('slot', targetKind === 'actor' ? pending.slot : 'reference');
    }
    form.append('file', pending.file);
    const endpoint = pending.type === 'model'
      ? `/api/elements/${target}/model`
      : `/api/elements/${target}/files`;
    await apiRequest(endpoint, { method: 'POST', body: form });
  };

  const closeCreateForm = () => {
    uploadWorkflow.current += 1;
    setError('');
    setName('');
    setDescription('');
    setPendingUpload(null);
    setShowForm(false);
  };

  const discardPendingUpload = () => {
    if (creatingRef.current || busyRef.current) return;
    if (pendingUpload?.target) {
      closeCreateForm();
      return;
    }
    uploadWorkflow.current += 1;
    setPendingUpload(null);
    setError('');
  };

  const isCurrentUploadWorkflow = (pending: PendingUpload) => (
    pending.workflowId === uploadWorkflow.current
    && (!pending.target || pending.target.kind === kindRef.current)
  );

  const addElement = async () => {
    if (!name.trim() || creatingRef.current || busyRef.current) return;
    const targetKind = kindRef.current;
    const uploadAfterCreate = pendingUpload;
    const createWorkflowId = uploadAfterCreate?.workflowId ?? ++uploadWorkflow.current;
    const createWorkflowIsCurrent = () => (
      createWorkflowId === uploadWorkflow.current && targetKind === kindRef.current
    );
    if (!startMutation('create')) return;
    setCreateInFlight(true);
    setError('');
    let created: ElementItem;
    try {
      created = await apiRequest<ElementItem>('/api/elements', {
        method: 'POST',
        body: JSON.stringify({ kind: targetKind, name: name.trim(), description: description.trim(), metadata: {} }),
      });
    } catch (err) {
      if (createWorkflowIsCurrent()) setError(err instanceof Error ? err.message : '添加失败');
      finishMutation('create');
      setCreateInFlight(false);
      return;
    }

    const uploadAttempt = uploadAfterCreate ? {
      ...uploadAfterCreate,
      target: { id: created.id, kind: targetKind },
    } : null;

    if (createWorkflowIsCurrent()) {
      setSelectedId(created.id);
      setUploadTarget(created.id);
      if (uploadAttempt) setPendingUpload(uploadAttempt);
    }

    if (!uploadAttempt) {
      if (createWorkflowIsCurrent()) {
        closeCreateForm();
        await load(targetKind);
      }
      finishMutation('create');
      setCreateInFlight(false);
      return;
    }

    if (!isCurrentUploadWorkflow(uploadAttempt)) {
      finishMutation('create');
      setCreateInFlight(false);
      return;
    }

    let uploadError = '';
    try {
      await sendUpload(uploadAttempt, created.id, targetKind);
    } catch (err) {
      const fallback = uploadAttempt.type === 'model' ? '3D 模型上传失败' : '参考图上传失败';
      uploadError = err instanceof Error ? err.message : fallback;
    }

    if (isCurrentUploadWorkflow(uploadAttempt)) {
      if (uploadError) {
        await load(targetKind);
        if (!isCurrentUploadWorkflow(uploadAttempt)) {
          finishMutation('create');
          setCreateInFlight(false);
          return;
        }
        setPendingUpload(uploadAttempt);
        setShowForm(true);
        setError(`${kindMeta[targetKind].label}已创建，但${uploadError}`);
      } else {
        closeCreateForm();
        await load(targetKind);
      }
    }
    finishMutation('create');
    setCreateInFlight(false);
  };

  const retryPendingFileUpload = async () => {
    const uploadAttempt = pendingUpload;
    const target = uploadAttempt?.target;
    if (!uploadAttempt || !target || !isCurrentUploadWorkflow(uploadAttempt) || creatingRef.current || busyRef.current) return;
    if (!startMutation('create')) return;
    setCreateInFlight(true);
    setError('');
    try {
      await sendUpload(uploadAttempt, target.id, target.kind);
      if (isCurrentUploadWorkflow(uploadAttempt)) {
        closeCreateForm();
        await load(target.kind);
      }
    } catch (err) {
      if (isCurrentUploadWorkflow(uploadAttempt)) {
        const fallback = uploadAttempt.type === 'model' ? '3D 模型上传失败' : '参考图上传失败';
        setError(err instanceof Error ? err.message : fallback);
      }
    } finally {
      finishMutation('create');
      setCreateInFlight(false);
    }
  };

  const beginImageUpload = (elementId?: string) => {
    if (creatingRef.current || busyRef.current) return;
    const target = elementId || ((kind === 'scene' || kind === 'prop') ? selectedId : '') || items[0]?.id;
    setUploadTarget(target);
    if (target) setSelectedId(target);
    setError('');
    imageInput.current?.click();
  };

  const beginModelUpload = (elementId?: string) => {
    if (creatingRef.current || busyRef.current) return;
    const target = elementId || selectedId || items[0]?.id;
    setUploadTarget(target);
    if (target) setSelectedId(target);
    setError('');
    modelInput.current?.click();
  };

  const uploadSelectedFile = async (type: PendingUpload['type'], file?: File) => {
    if (!file || creatingRef.current || busyRef.current) return;
    const workflowId = ++uploadWorkflow.current;
    const target = uploadTarget;
    const targetKind = kindRef.current;
    const replacesTrackedUpload = Boolean(pendingUpload?.target);
    const uploadAttempt: PendingUpload = {
      type,
      file,
      slot: uploadSlot,
      workflowId,
      ...(target ? { target: { id: target, kind: targetKind } } : {}),
    };
    if (!target) {
      setPendingUpload(uploadAttempt);
      setShowForm(true);
      setError('');
      return;
    }

    if (replacesTrackedUpload) {
      setPendingUpload(uploadAttempt);
      setShowForm(true);
    }

    const busyKey = `${type === 'model' ? 'model' : 'upload'}:${target}`;
    if (!startMutation(busyKey)) return;
    setError('');
    try {
      await sendUpload(uploadAttempt, target, targetKind);
      if (isCurrentUploadWorkflow(uploadAttempt)) {
        if (replacesTrackedUpload) closeCreateForm();
        await load(targetKind);
      }
    } catch (err) {
      if (isCurrentUploadWorkflow(uploadAttempt)) {
        const fallback = type === 'model' ? '3D 模型上传失败' : '上传失败';
        setError(err instanceof Error ? err.message : fallback);
      }
    } finally {
      finishMutation(busyKey);
    }
  };

  /*
   * Each chosen file owns an immutable workflow id and optional target. Older
   * async completions may finish on the server, but can no longer rebuild UI
   * state or pair a newer File with an older asset after tab switches.
   */

  const toggleCreateForm = () => {
    if (creatingRef.current || busyRef.current) return;
    setError('');
    if (showForm) {
      closeCreateForm();
      return;
    }
    uploadWorkflow.current += 1;
    setPendingUpload(null);
    setShowForm(true);
  };

  const openCreateForm = () => {
    if (creatingRef.current || busyRef.current) return;
    setError('');
    if (showForm) {
      createForm.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      nameInput.current?.focus({ preventScroll: true });
      return;
    }
    uploadWorkflow.current += 1;
    setName('');
    setDescription('');
    setPendingUpload(null);
    setShowForm(true);
  };

  /** Mine the project's screenplay for this kind and add what it names. */
  const importFromScript = async () => {
    if (!taskId || creatingRef.current || busyRef.current) return;
    const targetKind = kindRef.current;
    const label = kindMeta[targetKind].label;
    if (!startMutation('extract')) return;
    setError('');
    try {
      const result = await apiRequest<ExtractionResult>(
        `/api/drama/${encodeURIComponent(taskId)}/production-assets/${targetKind}/import`,
        { method: 'POST', body: JSON.stringify({}) },
      );
      if (targetKind !== kindRef.current) return;
      await load(targetKind);
      if (targetKind !== kindRef.current) return;
      const images = Number(result.with_image || 0);
      setNotice(result.created > 0
        ? `已从剧本提取 ${result.created} 个${label}资产`
          + (images ? `，其中 ${images} 个带参考图` : '，暂无参考图，可上传或重新生成')
          + (result.skipped ? `，跳过 ${result.skipped} 个已存在项` : '')
          + '。'
        : result.skipped > 0
          ? `剧本中的 ${result.skipped} 个${label}已全部存在于资产库。`
          : `剧本中尚未标注${label}信息，可手动添加或补充剧本后重试。`);
    } catch (err) {
      if (targetKind === kindRef.current) {
        setError(err instanceof Error ? err.message : `从剧本提取${label}失败`);
      }
    } finally {
      finishMutation('extract');
    }
  };

  const regenerateAllMissing = async () => {
    const targetKind = kindRef.current;
    if (targetKind === 'actor' || creatingRef.current || busyRef.current) return;
    const label = kindMeta[targetKind].label;
    const busyKey = 'generate-all';
    if (!startMutation(busyKey)) return;
    const sequence = ++generationSequence.current;
    onGenerationStateChange?.(true);
    setError('');
    setNotice(`正在检查${label}资产的缺失参考图…`);
    try {
      let job = await apiRequest<GenerationJob>('/api/elements/generation-jobs', {
        method: 'POST',
        body: JSON.stringify({ kind: targetKind, task_id: taskId || null }),
      });
      while (job.status === 'queued' || job.status === 'running') {
        if (sequence !== generationSequence.current || targetKind !== kindRef.current) return;
        setNotice(`正在生成${label}参考图：${job.processed}/${job.total}，剩余 ${job.remaining} 项…`);
        job = await apiRequest<GenerationJob>(`/api/elements/generation-jobs/${encodeURIComponent(job.id)}`);
        if (job.status === 'queued' || job.status === 'running') {
          await new Promise(resolve => window.setTimeout(resolve, 1_200));
        }
      }
      if (sequence !== generationSequence.current || targetKind !== kindRef.current) return;
      await load(targetKind);
      if (sequence !== generationSequence.current || targetKind !== kindRef.current) return;
      if (job.failed > 0) {
        setError(`${job.succeeded} 项${label}参考图生成成功，${job.failed} 项失败；可再次点击补全失败项。`);
      } else if (job.total === 0) {
        setNotice(`${label}资产的参考图已全部完整，无需重复生成。`);
      } else {
        setNotice(`${job.succeeded} 项${label}参考图已生成完整。`);
      }
    } catch (err) {
      if (sequence === generationSequence.current && targetKind === kindRef.current) {
        setError(err instanceof Error ? err.message : `批量生成${label}参考图失败`);
      }
    } finally {
      if (sequence === generationSequence.current) onGenerationStateChange?.(false);
      finishMutation(busyKey);
    }
  };

  useEffect(() => {
    if (regenerateAllToken === lastRegenerateAllToken.current) return;
    lastRegenerateAllToken.current = regenerateAllToken;
    void regenerateAllMissing();
  }, [regenerateAllToken]); // eslint-disable-line react-hooks/exhaustive-deps -- token deliberately starts one generation run

  useEffect(() => () => {
    generationSequence.current += 1;
  }, []);

  const renameElement = async (item: ElementItem) => {
    if (creatingRef.current || busyRef.current) return;
    const label = kindMeta[item.kind].label;
    const nextName = window.prompt(`重命名${label}资产`, item.name);
    if (nextName === null) return;
    const trimmed = nextName.trim();
    if (!trimmed || trimmed === item.name) return;
    const targetKind = kindRef.current;
    const busyKey = `rename:${item.id}`;
    if (!startMutation(busyKey)) return;
    setError('');
    try {
      await apiRequest(`/api/elements/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: trimmed }),
      });
      if (targetKind !== kindRef.current) return;
      await load(targetKind);
      if (targetKind === kindRef.current) setNotice(`已重命名为“${trimmed}”。`);
    } catch (err) {
      if (targetKind === kindRef.current) setError(err instanceof Error ? err.message : `重命名${label}资产失败`);
    } finally {
      finishMutation(busyKey);
    }
  };

  const deleteElement = async (item: ElementItem) => {
    if (creatingRef.current || busyRef.current) return;
    const label = kindMeta[item.kind].label;
    if (!window.confirm(`确定删除${label}资产“${item.name}”吗？关联的参考图与 3D 模型也会一并删除，此操作不可撤销。`)) return;
    const targetKind = kindRef.current;
    const busyKey = `delete:${item.id}`;
    if (!startMutation(busyKey)) return;
    setError('');
    try {
      await apiRequest(`/api/elements/${item.id}`, { method: 'DELETE' });
      if (targetKind !== kindRef.current) return;
      setItems(current => current.filter(entry => entry.id !== item.id));
      setSelectedId(current => current === item.id ? '' : current);
      setUploadTarget(current => current === item.id ? '' : current);
      if (pendingUpload?.target?.id === item.id) closeCreateForm();
      await load(targetKind);
      if (targetKind === kindRef.current) {
        setNotice(`已删除${label}资产“${item.name}”。`);
        window.setTimeout(() => toolbarCreateButton.current?.focus(), 0);
      }
    } catch (err) {
      if (targetKind === kindRef.current) setError(err instanceof Error ? err.message : `删除${label}资产失败`);
    } finally {
      finishMutation(busyKey);
    }
  };

  const deleteReference = async (item: ElementItem, poster: ElementFile, label = '参考图') => {
    if (creatingRef.current || busyRef.current) return;
    if (!window.confirm(`确定删除“${item.name}”的${label}吗？此操作不可撤销。`)) return;
    const targetKind = kindRef.current;
    const busyKey = `delete-file:${poster.id}`;
    if (!startMutation(busyKey)) return;
    setError('');
    try {
      await apiRequest(`/api/elements/${item.id}/files/${poster.id}`, { method: 'DELETE' });
      if (targetKind !== kindRef.current) return;
      setItems(current => current.map(entry => entry.id === item.id
        ? { ...entry, files: entry.files.filter(file => file.id !== poster.id) }
        : entry));
      await load(targetKind);
      if (targetKind === kindRef.current) {
        setNotice(`已删除“${item.name}”的${label}。`);
        window.setTimeout(() => toolbarImageButton.current?.focus(), 0);
      }
    } catch (err) {
      if (targetKind === kindRef.current) setError(err instanceof Error ? err.message : `删除${label}失败`);
    } finally {
      finishMutation(busyKey);
    }
  };

  const regenerate = async (item: ElementItem) => {
    if (creatingRef.current || busyRef.current) return;
    const busyKey = `regenerate:${item.id}`;
    if (!startMutation(busyKey)) return;
    setError('');
    try {
      const regenerated = await apiRequest<ElementItem | { status: string }>(`/api/elements/${item.id}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ prompt: `保持 ${item.name} 的身份、状态和视觉锚点，重新生成当前版本` }),
      });
      if (item.kind === 'actor') {
        setNotice(`“${item.name}”的五视图重新生成请求已提交。`);
        return;
      }
      const targetKind = kindRef.current;
      if (targetKind !== item.kind) return;
      if ('id' in regenerated) {
        setItems(current => current.map(entry => entry.id === item.id ? regenerated : entry));
      }
      await load(targetKind);
      if (targetKind === kindRef.current) setNotice(`已重新生成“${item.name}”的参考图。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新生成请求失败');
    } finally {
      finishMutation(busyKey);
    }
  };

  const spatialKind = kind === 'scene' || kind === 'prop';
  const retryUploadTarget = pendingUpload?.target?.kind === kind ? pendingUpload.target.id : '';
  const Root = embedded ? 'section' : 'main';

  return (
    <Root
      className={`${embedded ? '' : 'portal-page ' }element-library-page${embedded ? ' element-library-page--embedded' : ''}`}
      {...(embedded ? { role: 'region', 'aria-label': `${kindMeta[kind].label}资产工作区` } : {})}
    >
      {!embedded && (
        <header className="portal-header">
          <button type="button" className="back-button" onClick={onBack}><ArrowLeft size={18} /> 返回创作台</button>
          <div>
            <span className="eyebrow">ELEMENT LIBRARY</span>
            <h1>{kindMeta[kind].label}元素库</h1>
            <p>{kindMeta[kind].hint}</p>
          </div>
          <Boxes size={34} className="portal-mark" />
        </header>
      )}

      {!embedded && (
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
      )}

      <section className="element-toolbar">
        <div><strong>{total}</strong><span> 个{kindMeta[kind].label}元素</span></div>
        <div>
          {kind === 'actor' && (
            <label className="slot-select">上传视图
              <select value={uploadSlot} onChange={event => setUploadSlot(event.target.value)} disabled={Boolean(busy)}>
                {actorSlots.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          )}
          {spatialKind ? (
            <>
              <button ref={toolbarImageButton} type="button" className="secondary-action" onClick={() => beginImageUpload()} disabled={Boolean(busy)}><ImagePlus size={16} /> 上传参考图</button>
              <button type="button" className="secondary-action model-upload-action" onClick={() => beginModelUpload()} disabled={Boolean(busy)}><Upload size={16} /> 上传 3D 模型</button>
            </>
          ) : (
            <button ref={toolbarImageButton} type="button" className="secondary-action" onClick={() => beginImageUpload()} disabled={Boolean(busy)}><Upload size={16} /> 上传</button>
          )}
          {taskId && (
            <button
              type="button"
              className="secondary-action"
              onClick={() => { void importFromScript(); }}
              disabled={Boolean(busy)}
            >
              <FileSearch size={16} /> {busy === 'extract' ? '提取中…' : '从剧本提取'}
            </button>
          )}
          <button ref={toolbarCreateButton} type="button" className="primary-action" onClick={toggleCreateForm} disabled={Boolean(busy)}><Plus size={16} /> 添加{kindMeta[kind].label}</button>
          <input
            ref={imageInput}
            hidden
            type="file"
            accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
            onChange={event => {
              const file = event.target.files?.[0];
              event.target.value = '';
              void uploadSelectedFile('image', file);
            }}
          />
          {spatialKind && (
            <input
              ref={modelInput}
              hidden
              type="file"
              accept=".glb,model/gltf-binary"
              onChange={event => {
                const file = event.target.files?.[0];
                event.target.value = '';
                void uploadSelectedFile('model', file);
              }}
            />
          )}
        </div>
      </section>

      {showForm && (
        <section className="element-create-form" ref={createForm} aria-label={`添加${kindMeta[kind].label}`}>
          {pendingUpload && (
            <div className="pending-element-upload" role="status" aria-live="polite">
              <span className={`pending-upload-icon ${pendingUpload.type}`} aria-hidden="true">
                {pendingUpload.type === 'model' ? <Boxes size={18} /> : <ImagePlus size={18} />}
              </span>
              <span>
                <strong>
                  {retryUploadTarget
                    ? `${kindMeta[kind].label}已创建，${pendingUpload.type === 'model' ? '3D 模型' : '参考图'}等待重试`
                    : pendingUpload.type === 'model' ? '3D 模型已就绪' : '参考图已就绪'}
                </strong>
                <small>{pendingUpload.file.name} · {(pendingUpload.file.size / 1024).toFixed(1)} KB</small>
              </span>
              <button
                type="button"
                onClick={discardPendingUpload}
                disabled={Boolean(busy)}
              >{retryUploadTarget ? '放弃重试' : '移除'}</button>
            </div>
          )}
          <label>名称<input ref={nameInput} value={name} onChange={event => setName(event.target.value)} placeholder={`输入${kindMeta[kind].label}名称`} disabled={Boolean(busy)} /></label>
          <label>描述<textarea value={description} onChange={event => setDescription(event.target.value)} placeholder="身份、状态、材质、空间或效果约束" disabled={Boolean(busy)} /></label>
          <button
            type="button"
            className="primary-action"
            onClick={() => void (retryUploadTarget ? retryPendingFileUpload() : addElement())}
            disabled={Boolean(busy) || (!retryUploadTarget && !name.trim())}
          >
            {creating ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
            {retryUploadTarget && pendingUpload
              ? ` 重试上传${pendingUpload.type === 'model' ? ' 3D 模型' : '参考图'}`
              : pendingUpload
                ? ` 保存并上传${pendingUpload.type === 'model' ? ' 3D 模型' : '参考图'}`
                : ' 保存元素'}
          </button>
        </section>
      )}

      {error && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="element-success" role="status" aria-live="polite">{notice}</div>}
      {loading ? (
        <div className="empty-library"><LoaderCircle className="spin" /> 正在加载{kindMeta[kind].label}库…</div>
      ) : spatialKind ? (
        <Suspense fallback={<div className="empty-library"><LoaderCircle className="spin" /> 正在启动 3D 资产工作台…</div>}>
          <Element3DWorkspace
            kind={kind}
            items={items}
            selectedId={selectedId}
            busy={creating ? 'create' : busy}
            onSelect={setSelectedId}
            onCreate={openCreateForm}
            onUploadModel={beginModelUpload}
            onUploadPoster={beginImageUpload}
            onRegenerate={item => { void regenerate(item); }}
            onDelete={item => { void deleteElement(item); }}
            onDeletePoster={item => {
              const poster = findPoster(item);
              if (poster) void deleteReference(item, poster);
            }}
            onInspectPoster={item => {
              // 与服装/特效同构：有参考图才提供放大查看入口。
              const poster = findPoster(item);
              if (!poster?.url) return;
              setImageViewerAsset({
                kind: item.kind,
                name: item.name,
                description: item.description || kindMeta[item.kind].hint,
                imageUrl: `${API_BASE}${poster.url}`,
              });
            }}
          />
        </Suspense>
      ) : items.length === 0 ? (
        <div className="empty-library"><ImagePlus size={44} /><strong>还没有{kindMeta[kind].label}元素</strong><span>点击“添加{kindMeta[kind].label}”建立版本化资产，再上传参考图。</span></div>
      ) : (
        <div className="element-card-grid">
          {items.map(item => {
            // The actor slot selector doubles as the preview switch: whichever
            // five-view slot it names is the image every card shows.
            const previewFile = kind === 'actor' ? findViewImage(item, uploadSlot) : findPoster(item);
            const previewLabel = kind === 'actor' ? `${actorSlotLabel(uploadSlot)}视图` : '参考图';
            const descriptionText = item.description || kindMeta[kind].hint;
            // 服装/特效沿用全景卡布局；数字演员保持原卡面，仅叠加放大入口。
            const panoramaLayout = item.kind === 'costume' || item.kind === 'effect';
            const imageUrl = previewFile?.url ? `${API_BASE}${previewFile.url}` : '';
            const openViewerLabel = item.kind === 'costume'
              ? `查看服装资产“${item.name}”全景图`
              : item.kind === 'effect'
                ? `查看特效资产“${item.name}”细节图`
                : `查看数字演员“${item.name}”的${previewLabel}`;
            return (
            <article
              className={`element-card element-card--${item.kind}`}
              aria-label={`${kindMeta[item.kind].label}资产“${item.name}”`}
              key={item.id}
            >
              <div className={`element-preview${panoramaLayout ? ' element-preview--panorama' : ''}`}>
                {previewFile?.url
                  ? (
                    <button
                      type="button"
                      className="element-preview__open"
                      aria-label={openViewerLabel}
                      onClick={() => setImageViewerAsset({
                        kind: item.kind,
                        name: item.name,
                        // 数字演员按当前五视图逐图放大，标注正在查看的视图。
                        description: item.kind === 'actor' ? `${previewLabel} · ${descriptionText}` : descriptionText,
                        imageUrl,
                      })}
                    >
                      <img src={imageUrl} alt={`${item.name} ${previewLabel}`} />
                      <span className="element-preview__open-hint"><Maximize2 aria-hidden="true" /> 点击查看全景细节</span>
                    </button>
                  )
                  : (
                    <span className="element-preview__missing">
                      <Camera size={34} aria-hidden="true" />
                      {kind === 'actor' && <small>{previewLabel}未上传</small>}
                    </span>
                  )}
                <span className={`status-badge ${item.status}`}>{item.status === 'ready' ? '已就绪' : '待完善'}</span>
              </div>
              {panoramaLayout && (
                <div className="element-card-summary">
                  <div><h2>{item.name}</h2><span>v{item.version}</span></div>
                  <p>{descriptionText}</p>
                </div>
              )}
              <div className={`element-card-body${panoramaLayout ? ' element-card-body--actions-only' : ''}`}>
                {!panoramaLayout && (
                  <>
                    <div><h2>{item.name}</h2><span>v{item.version}</span></div>
                    <p>{descriptionText}</p>
                  </>
                )}
                {kind === 'actor' && <small>五视图 {item.files.length}/5</small>}
                <div className="element-actions">
                  <button type="button" onClick={() => beginImageUpload(item.id)} disabled={creating || Boolean(busy)}><Upload size={14} /> 添加上传</button>
                  <button
                    type="button"
                    onClick={() => void renameElement(item)}
                    disabled={creating || Boolean(busy)}
                    aria-label={`重命名${kindMeta[item.kind].label}资产“${item.name}”`}
                  >
                    <Pencil size={14} /> {busy === `rename:${item.id}` ? '重命名中' : '重命名'}
                  </button>
                  <button type="button" onClick={() => void regenerate(item)} disabled={creating || Boolean(busy)}><RefreshCw size={14} /> 重新生成</button>
                  {previewFile && (
                    <button
                      type="button"
                      className="element-delete-action"
                      onClick={() => void deleteReference(item, previewFile, previewLabel)}
                      disabled={creating || Boolean(busy)}
                      aria-label={busy === `delete-file:${previewFile.id}`
                        ? `正在删除“${item.name}”的${previewLabel}`
                        : `删除“${item.name}”的${previewLabel}`}
                    >
                      {busy === `delete-file:${previewFile.id}` ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                      {busy === `delete-file:${previewFile.id}` ? `正在删除${previewLabel}` : `删除${previewLabel}`}
                    </button>
                  )}
                  <button
                    type="button"
                    className="element-delete-action"
                    onClick={() => void deleteElement(item)}
                    disabled={creating || Boolean(busy)}
                    aria-label={busy === `delete:${item.id}`
                      ? `正在删除${kindMeta[item.kind].label}资产“${item.name}”`
                      : `删除${kindMeta[item.kind].label}资产“${item.name}”`}
                  >
                    {busy === `delete:${item.id}` ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                    {busy === `delete:${item.id}` ? '正在删除资产' : '删除资产'}
                  </button>
                </div>
              </div>
            </article>
            );
          })}
        </div>
      )}
      {imageViewerAsset && (
        <AssetImageViewer asset={imageViewerAsset} onClose={() => setImageViewerAsset(null)} />
      )}
    </Root>
  );
}
