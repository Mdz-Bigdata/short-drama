import { useMemo } from 'react';

import { getLocale, t } from '../../i18n';
import { useCanvasActions } from './canvasContext';
import { CANVAS_TOOLS, engineLabel, groupLabel, toolOf, type ToolGroup, type ToolParam } from './canvasTools';
import type { CanvasNode, NodeOutput, NodeParams, StyleLook } from './canvasTypes';

const GROUPS: ToolGroup[] = ['image', 'video', 'skill'];

function styleName(look: StyleLook) {
  return look.names[getLocale()] ?? look.names.zh;
}

/** Forty-five looks at a glance; the swatch is a hint of the palette, not a preview of the picture. */
export function StyleWall({ styles, value, onPick }: { styles: StyleLook[]; value: string; onPick: (id: string) => void }) {
  const groups = useMemo(() => [...new Set(styles.map(look => look.group))], [styles]);
  return (
    <div className="cn-stylewall" role="radiogroup" aria-label={t('风格墙')}>
      {groups.map(group => (
        <section key={group}>
          <h4>{t(group)}</h4>
          <div className="cn-stylewall__grid">
            {styles.filter(look => look.group === group).map(look => (
              <button
                key={look.id} type="button" role="radio" aria-checked={value === look.id} title={look.prompt}
                className={value === look.id ? 'is-active' : ''} onClick={() => onPick(look.id)}
              >
                <i aria-hidden="true" style={{ background: `linear-gradient(135deg, ${look.swatch[0]}, ${look.swatch[1]})` }} />
                <span>{styleName(look)}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ParamField({ param, params, onChange }: { param: ToolParam; params: NodeParams; onChange: (key: string, value: string | number) => void }) {
  const held = params[param.key];
  if (param.type === 'select') {
    return (
      <label className="cn-toolparam">
        <span>{param.label()}</span>
        <select aria-label={param.label()} value={String(held ?? param.fallback)} onChange={event => onChange(param.key, event.target.value)}>
          {param.options.map(([value, label]) => <option key={value} value={value}>{label()}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="cn-toolparam">
      <span>{param.label()}</span>
      <input
        type="number" aria-label={param.label()} value={Number(held ?? param.fallback)} min={param.min} max={param.max} step={param.step}
        onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange(param.key, value); }}
      />
    </label>
  );
}

/** The word a text tool came up with, ready to be read, copied or wired on. */
function TextResult({ output, onLayOut }: { output: NodeOutput; onLayOut?: () => void }) {
  const download = () => {
    const url = URL.createObjectURL(new Blob([output.text ?? ''], { type: 'text/html' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'page.html';
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="cn-toolresult">
      {/* A generated page gets no scripts and no origin of its own: it cannot touch this app or its session. */}
      {output.html ? <iframe className="cn-htmlframe" title={t('网页预览')} sandbox="" srcDoc={output.text} /> : <pre tabIndex={0}>{output.text}</pre>}
      <div className="cn-row">
        <button type="button" className="cn-button is-quiet" onClick={() => { void navigator.clipboard?.writeText(output.text ?? ''); }}>{t('复制')}</button>
        {output.html && <button type="button" className="cn-button is-quiet" onClick={download}>{t('下载')}</button>}
        {onLayOut && output.beats?.length ? <button type="button" className="cn-button" onClick={onLayOut}>{t('铺成 {0} 个节点', [output.beats.length])}</button> : null}
      </div>
    </div>
  );
}

export function ToolBody({ node, output, media, prompt, runBar }: {
  node: CanvasNode;
  output: NodeOutput | null;
  media: React.ReactNode;
  prompt: (label: string) => React.ReactNode;
  runBar: React.ReactNode;
}) {
  const { options, patch, layOutBeats } = useCanvasActions();
  const tool = toolOf(node);
  const params = node.payload.params ?? {};
  const change = (key: string, value: string | number) => patch(node.id, { params: { ...params, [key]: value } }, `tool:${node.id}:${key}`);
  const engines = options?.tools?.engines;
  const available = !tool || !engines || (tool.engine === 'audio' ? engines.voice : engines[tool.engine]);
  return (
    <>
      <select
        className="cn-select" aria-label={t('工具')} value={tool?.id ?? ''}
        // A new tool starts clean: what the last one was asked to do does not carry over.
        onChange={event => patch(node.id, { params: { tool: event.target.value, ...(params.model ? { model: params.model } : {}) } })}
      >
        {GROUPS.map(group => (
          <optgroup key={group} label={groupLabel(group)}>
            {CANVAS_TOOLS.filter(item => item.group === group).map(item => <option key={item.id} value={item.id}>{item.label()}</option>)}
          </optgroup>
        ))}
      </select>
      {tool && <small className={`cn-engine is-${tool.engine}`}>{engineLabel(tool.engine)}</small>}
      {tool?.note && <p className="cn-hint">{tool.note()}</p>}
      {!available && <p className="cn-hint cn-warn">{tool?.engine === 'vision' ? t('没有配置多模态模型') : tool?.engine === 'audio' ? t('没有配置 ElevenLabs') : tool?.engine === 'local' ? t('服务器上没有 ffmpeg') : t('项目还没有选模型')}</p>}
      {output?.medium === 'text' ? <TextResult output={output} onLayOut={output.beats?.length ? () => layOutBeats(node.id, output.beats ?? []) : undefined} /> : media}
      {tool?.id === 'style_transfer' && <StyleWall styles={options?.tools?.styles ?? []} value={String(params.style ?? '')} onPick={id => change('style', id)} />}
      {tool?.params?.length ? <div className="cn-toolparams">{tool.params.map(param => <ParamField key={param.key} param={param} params={params} onChange={change} />)}</div> : null}
      {tool?.prompt && prompt(tool.prompt())}
      {runBar}
    </>
  );
}
