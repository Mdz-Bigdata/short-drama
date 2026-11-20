import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Sparkles, X } from 'lucide-react';

import { t } from '../../i18n';
import { CLIP_ONLY_MODES, fetchOptimizerOptions, optimizePrompt, type OptimizeMode, type OptimizeResult, type OptimizerOptions } from './canvasBeefApi';
import { CanvasBeefCameraDiagnosis } from './CanvasBeefCameraDiagnosis';
import './CanvasBeef.css';

export interface CanvasBeefPromptOptimizerProps {
  taskId: string;
  prompt: string;
  medium: 'image' | 'video';
  targetModel?: string;
  /** Text of the node's connected text references (notes, character descriptions). */
  references?: string[];
  /** How many pictures are connected; the text model does not see them, they are only counted. */
  imageReferences?: number;
  /** A clip node's length in seconds, so a timed script can be made to fill it exactly. */
  durationSeconds?: number;
  /** Text models to offer; when absent the server's list is used. */
  textModels?: string[];
  /** The one chosen at first; when absent the project's own text model. */
  defaultTextModel?: string;
  onAdopt: (prompt: string) => void;
  onClose: () => void;
}

/** Turns a vague idea or a rough prompt into one a generation model can follow. Nothing changes until 采用. */
export function CanvasBeefPromptOptimizer({
  taskId, prompt, medium, targetModel = '', references = [], imageReferences = 0, durationSeconds, textModels, defaultTextModel, onAdopt, onClose,
}: CanvasBeefPromptOptimizerProps) {
  const [options, setOptions] = useState<OptimizerOptions | null>(null);
  const [mode, setMode] = useState<OptimizeMode>(prompt.trim().length > 40 ? 'refine' : 'expand');
  const [model, setModel] = useState('');
  const [note, setNote] = useState('');
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [edited, setEdited] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchOptimizerOptions(taskId, controller.signal)
      .then(data => { setOptions(data); setModel(defaultTextModel || data.default_text_model || data.text_models[0] || ''); })
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('优化选项加载失败')); });
    return () => { controller.abort(); running.current?.abort(); };
  }, [taskId, defaultTextModel]);

  const models = textModels?.length ? textModels : options?.text_models ?? [];
  const hasReferences = references.some(text => text.trim()) || imageReferences > 0;

  const run = async () => {
    running.current?.abort();
    const controller = new AbortController();
    running.current = controller;
    setBusy(true);
    setError('');
    try {
      const answer = await optimizePrompt(taskId, {
        prompt, medium, mode, targetModel, references, imageReferences, note, textModel: model, duration: durationSeconds,
      }, controller.signal);
      setResult(answer);
      setEdited(answer.prompt);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('优化没有完成，原提示词没有改动'));
    } finally {
      if (running.current === controller) {
        running.current = null;
        setBusy(false);
      }
    }
  };

  const cancel = () => {
    running.current?.abort();
    running.current = null;
    setBusy(false);
  };

  const list = (title: string, items: string[]) => items.length > 0 && (
    <div className="canvas-beef-optimizer__list"><strong>{title}</strong><ul>{items.map(item => <li key={item}>{item}</li>)}</ul></div>
  );

  return (
    <div className="canvas-beef-optimizer" role="dialog" aria-label={t('提示词优化')}>
      <header>
        <strong><Sparkles size={14} aria-hidden="true" /> {t('提示词优化')}</strong>
        <button type="button" onClick={() => { cancel(); onClose(); }} aria-label={t('关闭优化')}><X size={15} /></button>
      </header>
      <div className="canvas-beef-optimizer__modes" role="radiogroup" aria-label={t('优化方式')}>
        {(options?.modes ?? []).map(item => (
          <label key={item.id} className={mode === item.id ? 'is-chosen' : ''}>
            <input
              type="radio" name="canvas-beef-optimize-mode" value={item.id} checked={mode === item.id}
              disabled={(item.id === 'references' && !hasReferences) || (CLIP_ONLY_MODES.includes(item.id) && medium !== 'video')}
              onChange={() => setMode(item.id)}
            />
            {item.label}
          </label>
        ))}
      </div>
      {mode === 'camera' && prompt.trim() && <CanvasBeefCameraDiagnosis taskId={taskId} prompt={prompt} medium={medium} />}
      <label className="canvas-beef-field">
        {t('补充要求（可不填）')}
        <input value={note} maxLength={500} onChange={event => setNote(event.target.value)} />
      </label>
      {result && (
        <div className="canvas-beef-optimizer__result">
          <label className="canvas-beef-field">
            {t('优化后的提示词（可以再改）')}
            <textarea value={edited} onChange={event => setEdited(event.target.value)} rows={6} />
          </label>
          {result.structure_check && list(
            t('结构检查（按规则，不调用模型）'),
            result.structure_check.ok ? [result.structure_check.summary] : result.structure_check.problems,
          )}
          {list(t('规避项'), result.avoid)}
          {list(t('改了什么'), result.changes)}
          {list(t('按这些理解写的'), result.assumptions)}
          {result.alternatives.length > 0 && (
            <div className="canvas-beef-optimizer__list">
              <strong>{t('另一版')}</strong>
              {result.alternatives.map(item => (
                <button type="button" key={item} className="canvas-beef-optimizer__alt" onClick={() => setEdited(item)}>{item}</button>
              ))}
            </div>
          )}
        </div>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <footer>
        <label className="canvas-beef-field canvas-beef-field--inline">
          {t('用哪个文本模型')}
          <select value={model} onChange={event => setModel(event.target.value)} disabled={busy}>
            {models.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <span className="canvas-beef-spacer" />
        {busy ? (
          <button type="button" onClick={cancel}><LoaderCircle className="spin" size={14} /> {t('取消优化')}</button>
        ) : (
          <button type="button" onClick={() => void run()} disabled={!options}>{result ? t('再优化一次') : t('开始优化')}</button>
        )}
        <button type="button" className="is-primary" disabled={!result || !edited.trim() || busy} onClick={() => onAdopt(edited.trim())}>{t('采用')}</button>
      </footer>
    </div>
  );
}
