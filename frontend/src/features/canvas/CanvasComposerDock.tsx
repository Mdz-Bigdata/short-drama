import { ChevronDown, ChevronUp, Loader2, Sparkles, X } from 'lucide-react';

import { t } from '../../i18n';
import { countCeiling, countOf, modelChoices, withParam, type DockPlacement } from './canvasComposer';
import { useCanvasActions } from './canvasContext';
import { nodeTitle, statusLabel } from './canvasLabels';
import type { CanvasNode, LatestRun } from './canvasTypes';
import type { RunQuote } from './useRunQuote';
import { CanvasBeefDockEditorButton } from './CanvasBeefDockEditorButton';

const PROMPT_MAX = 8000;

function promptLabel(node: CanvasNode) {
  return node.kind === 'audio_gen' ? t('生成栏：要合成的文本') : t('生成栏：提示词');
}

interface DockProps {
  node: CanvasNode;
  latest?: LatestRun;
  quote: RunQuote | null;
  placement: DockPlacement;
  collapsed: boolean;
  onToggle: () => void;
}

/**
 * The selected node's composer: its prompt with room to write, the model and parameters of this
 * kind, what the run would cost, and the button that runs it. It edits the same node the card
 * and the inspector edit; nothing is kept here.
 */
export function CanvasComposerDock({ node, latest, quote, placement, collapsed, onToggle }: DockProps) {
  const { options, patch, run, cancel } = useCanvasActions();
  const params = node.payload.params ?? {};
  const busy = latest?.status === 'queued' || latest?.status === 'running';
  const kind = options?.kinds[node.kind];
  const choices = modelChoices(node, options);
  const ceiling = countCeiling(node, options);
  const count = countOf(params, ceiling);
  const durations = options?.video_durations ?? [];
  const setParam = (key: string, value: unknown, fallback?: unknown, coalesce?: string) => patch(node.id, { params: withParam(params, key, value, fallback) }, coalesce);
  const title = t('生成栏：{0}', [nodeTitle(node)]);

  if (collapsed) {
    return (
      <button
        type="button" className="cn-dock cn-dock--collapsed" style={{ left: placement.left + placement.width / 2, top: placement.top }}
        onClick={onToggle} aria-label={t('展开生成栏')} title={t('展开生成栏')}
      >
        <Sparkles aria-hidden="true" /> {t('生成栏')} <ChevronDown aria-hidden="true" />
      </button>
    );
  }

  return (
    <section className="cn-dock" role="group" aria-label={title} style={{ left: placement.left, top: placement.top, width: placement.width }}>
      <textarea
        className="cn-dock__prompt" aria-label={promptLabel(node)} placeholder={node.kind === 'audio_gen' ? t('要合成的文本') : t('提示词')}
        value={String(node.payload.prompt ?? '')} maxLength={PROMPT_MAX}
        onChange={event => patch(node.id, { prompt: event.target.value }, `prompt:${node.id}`)}
        onKeyDown={event => {
          // ⌘/Ctrl + Enter runs from the keyboard; a bare Enter is a new line in the prompt.
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !busy && kind?.runnable !== false) {
            event.preventDefault();
            run([node.id]);
          }
        }}
      />
      <div className="cn-dock__row">
        {choices && (
          <label className="cn-dock__field">
            <span>{t('模型')}</span>
            <select aria-label={t('生成栏：模型')} value={params.model ?? ''} onChange={event => setParam('model', event.target.value)}>
              <option value="">{t('项目默认（{0}）', [choices.fallback || t('未设置')])}</option>
              {choices.models.map(model => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
        )}
        {node.kind === 'video_gen' && (
          <label className="cn-dock__field">
            <span>{t('时长（秒）')}</span>
            {durations.length > 0 ? (
              <select aria-label={t('生成栏：时长')} value={Number(params.durationSeconds ?? 5)} onChange={event => setParam('durationSeconds', Number(event.target.value))}>
                {[...new Set([...durations, Number(params.durationSeconds ?? 5)])].sort((a, b) => a - b).map(seconds => <option key={seconds} value={seconds}>{seconds}</option>)}
              </select>
            ) : (
              <input
                aria-label={t('生成栏：时长')} type="number" min={1} step={1} value={Number(params.durationSeconds ?? 5)}
                onChange={event => setParam('durationSeconds', Number(event.target.value) || 5, undefined, `duration:${node.id}`)}
              />
            )}
          </label>
        )}
        {node.kind === 'image_gen' && (
          <label className="cn-dock__field">
            <span>{t('尺寸')}</span>
            <input
              aria-label={t('生成栏：尺寸')} value={params.size ?? ''} placeholder="1024x1024" maxLength={16} pattern="[0-9]+x[0-9]+"
              onChange={event => setParam('size', event.target.value, undefined, `size:${node.id}`)}
            />
          </label>
        )}
        {node.kind === 'audio_gen' && (
          <label className="cn-dock__field">
            <span>{t('音频类型')}</span>
            <select aria-label={t('生成栏：音频类型')} value={params.mode ?? 'speech'} onChange={event => setParam('mode', event.target.value)}>
              <option value="speech">{t('配音')}</option>
              <option value="music" disabled={kind?.modes?.music === false}>{t('配乐')}</option>
              <option value="sfx" disabled={kind?.modes?.sfx === false}>{t('音效')}</option>
            </select>
          </label>
        )}
        {ceiling > 1 && (
          <label className="cn-dock__field cn-dock__field--count">
            <span>{t('数量')}</span>
            <select aria-label={t('生成栏：一次出几个')} value={count} onChange={event => setParam('count', Number(event.target.value), 1)}>
              {Array.from({ length: ceiling }, (_, index) => index + 1).map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        )}
        <span className="cn-grow" />
        {quote && <span className={`cn-dock__quote is-${quote.tone}`} role="status" title={quote.text}>{quote.text}</span>}
      </div>
      <div className="cn-dock__row cn-dock__foot">
        {latest && (
          <span className={`cn-status is-${latest.status}`} title={latest.error ?? undefined}>
            {statusLabel(latest.status)}{latest.versions ? ` ${latest.versions.done}/${latest.versions.total}` : ''}
          </span>
        )}
        {kind?.reason && node.kind !== 'video_gen' && <span className="cn-hint">{kind.reason}</span>}
        <span className="cn-grow" />
        {latest?.status === 'queued' && (
          <button type="button" className="cn-button is-quiet" onClick={() => cancel(latest)} aria-label={t('生成栏：取消排队')} title={t('取消排队')}><X aria-hidden="true" /></button>
        )}
        <CanvasBeefDockEditorButton node={node} />
        <button type="button" className="cn-button is-quiet" onClick={onToggle} aria-label={t('收起生成栏')} title={t('收起生成栏')}><ChevronUp aria-hidden="true" /></button>
        <button type="button" className="cn-button is-primary" disabled={busy || kind?.runnable === false} onClick={() => run([node.id])} title={t('⌘/Ctrl + Enter')}>
          {busy ? <Loader2 className="cn-spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />} {count > 1 ? t('生成 {0} 个', [count]) : t('生成')}
        </button>
      </div>
    </section>
  );
}
