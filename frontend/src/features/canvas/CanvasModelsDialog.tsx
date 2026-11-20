import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';

import { t } from '../../i18n';
import { fetchProjectModels, MODEL_CATEGORIES, saveProjectModels, type ModelCategory, type ProjectModels } from './canvasFilmApi';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function categoryLabel(category: ModelCategory) {
  if (category === 'text') return t('文本模型');
  if (category === 'image') return t('图像模型');
  if (category === 'video') return t('视频模型');
  return t('音频模型（配音）');
}

function categoryUse(category: ModelCategory) {
  if (category === 'text') return t('写剧本、拆镜头表、拍点规划等文字工具，以及流水线的编剧与分镜');
  if (category === 'image') return t('首帧、分镜图和图片工具');
  if (category === 'video') return t('视频节点和流水线的视频阶段');
  return t('配音节点、一键成片的配音和流水线的配音');
}

/**
 * The project's four models, set from the canvas. They are the project's own configuration: the pipeline's
 * stages and every canvas node that has not picked a model of its own use them.
 */
export function CanvasModelsDialog({ projectId, onSaved, onClose }: {
  projectId: string;
  /** The models changed: what the canvas offers per node should be read again. */
  onSaved: () => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ProjectModels | null>(null);
  const [draft, setDraft] = useState<Partial<Record<ModelCategory, string>>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  useEffect(() => {
    const abort = new AbortController();
    fetchProjectModels(projectId, abort.signal)
      .then(value => {
        setView(value);
        setDraft(Object.fromEntries(MODEL_CATEGORIES.map(category => [category, value.models[category].chosen])));
      })
      .catch(error => { if (!abort.signal.aborted) setProblem(messageOf(error, t('读取模型设置失败'))); });
    return () => abort.abort();
  }, [projectId]);

  const changed = view ? MODEL_CATEGORIES.filter(category => (draft[category] ?? '') !== view.models[category].chosen) : [];

  const save = async () => {
    if (!view || busy || !changed.length) return;
    setBusy(true);
    setProblem('');
    setSaved(false);
    try {
      const next = await saveProjectModels(projectId, Object.fromEntries(changed.map(category => [category, draft[category] ?? ''])));
      setView(next);
      setDraft(Object.fromEntries(MODEL_CATEGORIES.map(category => [category, next.models[category].chosen])));
      setSaved(true);
      onSaved();
    } catch (error) {
      setProblem(messageOf(error, t('保存模型设置失败')));
    } finally {
      setBusy(false);
    }
  };

  const title = t('项目模型');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog cn-models" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        <p className="cn-hint">{t('这是项目自己的模型设置：流水线各阶段和画布上没有单独选模型的节点都用它。只能选模型配置中心启用了的模型。')}</p>
        {!view && !problem && <p className="cn-hint"><Loader2 className="cn-spin" aria-hidden="true" /> {t('读取中…')}</p>}
        {view && (
          <>
            {view.running && <p className="cn-error" role="alert">{t('流水线正在执行某一步，等它结束再换模型。')}</p>}
            <div className="cn-models__rows">
              {MODEL_CATEGORIES.map(category => {
                const slot = view.models[category];
                const value = draft[category] ?? '';
                return (
                  <label key={category} className="cn-field">
                    <span>{categoryLabel(category)}</span>
                    <select
                      aria-label={categoryLabel(category)} value={value} disabled={view.running || busy || (!slot.choices.length && category !== 'audio')}
                      onChange={event => setDraft(current => ({ ...current, [category]: event.target.value }))}
                    >
                      {category !== 'video' && <option value="">{t('模型配置中心默认（{0}）', [slot.effective || t('未设置')])}</option>}
                      {/* What the project names but the centre does not enable: shown as it is, with what runs instead. */}
                      {value && !slot.choices.includes(value) && <option value={value}>{t('{0}（未启用，实际用 {1}）', [value, slot.effective || t('未设置')])}</option>}
                      {category === 'video' && !value && <option value="">{t('未设置')}</option>}
                      {slot.choices.map(model => <option key={model} value={model}>{model}</option>)}
                    </select>
                    <small className="cn-hint">
                      {categoryUse(category)}
                      {slot.choices.length ? '' : ` · ${t('模型配置中心还没有启用这一类模型')}`}
                    </small>
                  </label>
                );
              })}
            </div>
            <p className="cn-hint">
              {view.extras.music ? t('配乐和音效：ElevenLabs 可用。') : t('配乐和音效要用 ElevenLabs，模型配置中心还没有可用的密钥；一键成片可以先不加配乐。')}
            </p>
          </>
        )}
        {saved && <p className="cn-dialog__cost" role="status"><CheckCircle2 aria-hidden="true" /> {t('已保存，之后运行的节点用新模型。')}</p>}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{saved && !changed.length ? t('完成') : t('取消')}</button>
          <button type="button" className="cn-button is-primary" disabled={!view || view.running || busy || !changed.length} onClick={() => { void save(); }}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('保存')}
          </button>
        </footer>
      </div>
    </div>
  );
}
