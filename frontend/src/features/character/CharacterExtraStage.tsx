import { ImagePlus, LoaderCircle, Plus, Trash2, UsersRound, WandSparkles, X } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';

import { apiRequest } from '../../api/client';
import type { ElementItem } from '../elements/elementTypes';
import { extraThumbnail } from './characterExtras';
import { t } from '../../i18n';

/**
 * 群演在「数字演员」页里和主演同在角色库：左栏角色库里一组「群演」，选中一位时中间一栏换成它的参考图和操作。
 * 群演仍是资产库里的 extra 类资产，只是不再在页面下方另开一个资产库。
 */

interface GenerationJob {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed';
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  remaining: number;
}

/** 角色库「群演」一组的工具：新建一位群演、补齐缺图(付费出图，只补没有图的)。 */
export function ExtrasLibraryTools({
  taskId,
  onCreated,
  onFilled,
  onBusyChange,
}: {
  taskId?: string;
  onCreated: (item: ElementItem) => void;
  onFilled: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState<'' | 'create' | 'fill'>('');
  const [message, setMessage] = useState('');

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy('create');
    setMessage('');
    try {
      const created = await apiRequest<ElementItem>('/api/elements', {
        method: 'POST',
        body: JSON.stringify({
          kind: 'extra',
          name: name.trim(),
          description: description.trim(),
          metadata: taskId ? { task_id: taskId } : {},
        }),
      });
      setName('');
      setDescription('');
      setCreating(false);
      onCreated(created);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('添加失败'));
    } finally {
      setBusy('');
    }
  };

  const fill = async () => {
    if (busy) return;
    setBusy('fill');
    onBusyChange?.(true);
    setMessage(t('正在检查群演的缺失参考图…'));
    try {
      let job = await apiRequest<GenerationJob>('/api/elements/generation-jobs', {
        method: 'POST',
        body: JSON.stringify({ kind: 'extra', task_id: taskId || null }),
      });
      while (job.status === 'queued' || job.status === 'running') {
        setMessage(t('正在生成群演参考图：{0}/{1}，剩余 {2} 项…', [job.processed, job.total, job.remaining]));
        await new Promise(resolve => window.setTimeout(resolve, 1_200));
        job = await apiRequest<GenerationJob>(`/api/elements/generation-jobs/${encodeURIComponent(job.id)}`);
      }
      setMessage(job.total === 0
        ? t('群演都已有参考图。')
        : t('群演参考图已补齐 {0} 项，失败 {1} 项。', [job.succeeded, job.failed]));
      onFilled();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('补图失败'));
    } finally {
      setBusy('');
      onBusyChange?.(false);
    }
  };

  return (
    <div className="character-library__extras-tools">
      <div className="character-library__extras-actions">
        <button type="button" onClick={() => setCreating(open => !open)} aria-expanded={creating} disabled={Boolean(busy)}>
          {creating ? <X size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />} {creating ? t('取消') : t('添加群演')}
        </button>
        <button
          type="button"
          onClick={() => { void fill(); }}
          disabled={Boolean(busy)}
          title={t('只为没有参考图的群演出图，每张一次付费出图')}
        >
          {busy === 'fill' ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : <WandSparkles size={14} aria-hidden="true" />}
          {busy === 'fill' ? t('图片生成中…') : t('补齐群演图片')}
        </button>
      </div>
      {creating && (
        <form className="character-library__extra-form" onSubmit={event => { void create(event); }} aria-label={t('添加群演')}>
          <input value={name} onChange={event => setName(event.target.value)} placeholder={t('职能，如：茶馆伙计')} aria-label={t('群演名称')} required />
          <textarea
            value={description}
            onChange={event => setDescription(event.target.value)}
            placeholder={t('人数、服装、在做什么')}
            aria-label={t('群演描述')}
            rows={2}
          />
          <button type="submit" disabled={!name.trim() || Boolean(busy)}>
            {busy === 'create' ? t('添加中…') : t('添加')}
          </button>
        </form>
      )}
      {message && <p className="character-library__extras-message" role="status">{message}</p>}
    </div>
  );
}

/** 选中一位群演时的中间一栏：参考图大图 + 描述 + 出图 / 上传 / 删除。 */
export function CharacterExtraStage({
  extra,
  onChanged,
  onDeleted,
}: {
  extra: ElementItem;
  onChanged: () => void;
  onDeleted: (id: string) => void;
}) {
  const [busy, setBusy] = useState<'' | 'regenerate' | 'upload' | 'delete'>('');
  const [message, setMessage] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const image = extraThumbnail(extra);

  const run = async (kind: 'regenerate' | 'upload' | 'delete', work: () => Promise<string>) => {
    if (busy) return;
    setBusy(kind);
    setMessage('');
    try {
      setMessage(await work());
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setBusy('');
    }
  };

  const regenerate = () => {
    const question = image
      ? t('重新为群演“{0}”生成参考图？这是一次付费出图，旧图会被替换。', [extra.name])
      : t('为群演“{0}”生成参考图？这是一次付费出图。', [extra.name]);
    if (!window.confirm(question)) return;
    void run('regenerate', async () => {
      await apiRequest(`/api/elements/${extra.id}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ prompt: `保持 ${extra.name} 的身份、状态和视觉锚点，重新生成当前版本` }),
      });
      onChanged();
      return t('已生成“{0}”的参考图。', [extra.name]);
    });
  };

  const upload = (file: File | undefined) => {
    if (!file) return;
    void run('upload', async () => {
      const form = new FormData();
      form.append('slot', 'reference');
      form.append('file', file);
      await apiRequest(`/api/elements/${extra.id}/files`, { method: 'POST', body: form });
      onChanged();
      return t('已上传“{0}”的参考图。', [extra.name]);
    });
  };

  const remove = () => {
    if (!window.confirm(t('确定删除群演“{0}”吗？它的参考图也会一并删除，此操作不可撤销。', [extra.name]))) return;
    void run('delete', async () => {
      await apiRequest(`/api/elements/${extra.id}`, { method: 'DELETE' });
      onDeleted(extra.id);
      return '';
    });
  };

  return (
    <section className="character-extra-stage" aria-labelledby="character-extra-stage-title">
      <header className="character-extra-stage__head">
        <div>
          <span className="character-section-kicker">EXTRA</span>
          <h2 id="character-extra-stage-title">{extra.name}</h2>
          <small>{t('群演 · 没有台词的背景人物')}</small>
        </div>
      </header>
      <div className="character-extra-stage__body">
        <figure className="character-extra-stage__image">
          {image
            ? <img src={image} alt={t('群演“{0}”的参考图', [extra.name])} />
            : (
              <div className="character-extra-stage__placeholder" role="img" aria-label={t('还没有参考图')}>
                <UsersRound size={42} aria-hidden="true" />
                <span>{t('还没有参考图')}</span>
              </div>
            )}
        </figure>
        <div className="character-extra-stage__info">
          <p className="character-extra-stage__description">{extra.description || t('还没有描述：写清人数、服装、在做什么。')}</p>
          <div className="character-extra-stage__actions">
            <button type="button" className="is-accent" onClick={regenerate} disabled={Boolean(busy)}>
              {busy === 'regenerate' ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <WandSparkles size={16} aria-hidden="true" />}
              {busy === 'regenerate' ? t('生成中…') : image ? t('重新生成参考图') : t('生成参考图')}
            </button>
            <button type="button" onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}>
              <ImagePlus size={16} aria-hidden="true" /> {busy === 'upload' ? t('上传中…') : t('上传参考图')}
            </button>
            <button type="button" className="is-danger" onClick={remove} disabled={Boolean(busy)}>
              <Trash2 size={16} aria-hidden="true" /> {busy === 'delete' ? t('正在删除…') : t('删除群演')}
            </button>
            <input
              ref={fileInput}
              hidden
              type="file"
              accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
              onChange={event => {
                const file = event.target.files?.[0];
                event.target.value = '';
                upload(file);
              }}
            />
          </div>
          {message && <p className="character-extra-stage__message" role="status">{message}</p>}
        </div>
      </div>
    </section>
  );
}
