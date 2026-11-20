import { useEffect, useId, useRef, useState } from 'react';
import { Palette } from 'lucide-react';

import { t } from '../../i18n';
import { mediaUrlOf } from '../workbench/stageSix';
import {
  defaultMoment, isNeutralGrade, lastMoment, neutralGrade, signed,
  type ColorSlider, type FinishingChanges, type FinishingView,
} from './finishingSettings';
import { clipKey, clipRef, type StudioClip } from './postProduction';
import './FilmFinishing.css';

/* What each option is called. The ids come from the backend's option tables; one it adds later shows by its id. */
const named = (labels: Record<string, string>, id: string) => labels[id] ?? id;
const animationName = (id: string) => named({ fade: t('淡入'), zoom: t('缓慢推近'), reveal: t('逐字出现') }, id);
const sizeName = (id: string) => named({ small: t('小'), medium: t('中'), large: t('大') }, id);
const colorName = (id: string) => named({ white: t('白'), pale_yellow: t('淡黄'), pale_cyan: t('淡青') }, id);
const positionName = (id: string) => named({ bottom: t('底部'), raised: t('偏上') }, id);
const outlineName = (id: string) => named({ none: t('无描边'), normal: t('标准'), bold: t('加粗') }, id);
const presetName = (id: string) => named({
  none: t('原片'), bright: t('明亮'), film: t('电影感'), warm: t('暖调'), cool: t('冷调'), vintage: t('复古'), mono: t('黑白'), custom: t('自定义'),
}, id);
const sliderName = (id: ColorSlider) => named({ brightness: t('亮度'), contrast: t('对比度'), saturation: t('饱和度'), warmth: t('冷暖') }, id);

const SAMPLE_SHADOW: Record<string, string> = {
  none: 'none',
  normal: '0 0 2px #000, 0 0 2px #000',
  bold: '0 0 3px #000, 0 0 3px #000, 0 0 3px #000',
};

interface Props {
  view: FinishingView;
  clips: StudioClip[];
  /** The basic switches these depend on: with one off, its group says so and still keeps what was chosen. */
  titleCard: boolean;
  subtitles: boolean;
  busy: boolean;
  /** One edit: only what changed, and what to call it in the notice. */
  onChange: (changes: FinishingChanges, label: string) => void;
}

/** 成片精修: the title card's frame and animation, the subtitle style, the film-wide grade and the ending card. */
export function FilmFinishing({ view, clips, titleCard, subtitles, busy, onChange }: Props) {
  const { value, options } = view;
  const ids = useId();
  const frame = useRef<HTMLVideoElement | null>(null);
  const [momentDraft, setMomentDraft] = useState<number | null>(null);
  const [gradeDraft, setGradeDraft] = useState<Partial<Record<ColorSlider, number>>>({});
  const [endingDraft, setEndingDraft] = useState<string | null>(null);

  const usable = clips.filter(clip => clip.video_url && clip.review.decision !== 'rejected');
  const background = value.title.background;
  const backgroundClip = background
    ? clips.find(clip => (background.shot_uid ? clip.shot_uid === background.shot_uid : clip.shot_id === background.shot_id)) ?? null
    : null;
  const moment = momentDraft ?? background?.at ?? 0;
  const frameUrl = backgroundClip ? mediaUrlOf(backgroundClip.video_url) : '';

  // The preview shows the moment the slider is on.
  useEffect(() => {
    const video = frame.current;
    if (video && frameUrl) video.currentTime = moment;
  }, [frameUrl, moment]);

  const pickBackground = (key: string) => {
    const clip = usable.find(item => String(clipKey(item)) === key);
    setMomentDraft(null);
    onChange({ title: { background: clip ? { ...clipRef(clip), at: defaultMoment(clip.duration) } : null } }, t('片名卡'));
  };
  const commitMoment = () => {
    if (momentDraft === null) return;
    if (backgroundClip && background && momentDraft !== background.at) {
      onChange({ title: { background: { ...clipRef(backgroundClip), at: momentDraft } } }, t('片名卡'));
    }
    setMomentDraft(null);
  };

  const commitGrade = (name: ColorSlider) => {
    const draft = gradeDraft[name];
    if (draft === undefined) return;
    if (draft !== value.color[name]) onChange({ color: { [name]: draft } }, t('全片调色'));
    setGradeDraft(current => {
      const rest = { ...current };
      delete rest[name];
      return rest;
    });
  };
  const neutral = isNeutralGrade(value.color, options.color.sliders) && Object.keys(gradeDraft).length === 0;
  const resetGrade = () => {
    setGradeDraft({});
    onChange({ color: neutralGrade(options.color.sliders) }, t('全片调色'));
  };

  const teaser = (view.ending_teaser ?? '').trim();
  const endingText = endingDraft ?? value.ending.text;
  const toggleEnding = () => {
    const enabled = !value.ending.enabled;
    // 第一次打开且还没写字：拿这一集的下集预告预填，之后随便改。
    onChange({ ending: { enabled, ...(enabled && !value.ending.text && teaser ? { text: teaser } : {}) } }, t('片尾卡'));
  };
  const commitEnding = () => {
    if (endingDraft === null) return;
    if (endingDraft.trim() !== value.ending.text) onChange({ ending: { text: endingDraft.trim() } }, t('片尾卡'));
    setEndingDraft(null);
  };

  const sampleColor = options.subtitle.colors.find(item => item.id === value.subtitle.color)?.rgb ?? [255, 255, 255];
  const sampleSize = 0.8 + 0.16 * Math.max(0, options.subtitle.sizes.indexOf(value.subtitle.size));
  const select = (key: keyof FinishingView['value']['subtitle'], label: string, choices: string[], name: (id: string) => string) => (
    <label className="ff-field">
      <span>{label}</span>
      <select value={value.subtitle[key]} disabled={busy} onChange={event => onChange({ subtitle: { [key]: event.target.value } }, t('字幕样式'))}>
        {choices.map(id => <option key={id} value={id}>{name(id)}</option>)}
      </select>
    </label>
  );

  return (
    <section className="pp-card ff" aria-labelledby={`${ids}-title`}>
      <h4 id={`${ids}-title`}><Palette aria-hidden="true" /> {t('成片精修')}</h4>

      <fieldset className="ff-group">
        <legend>{t('片名卡')}</legend>
        {!titleCard && <p className="pp-muted">{t('片名卡现在是关的，打开「片名卡与首尾淡入淡出」后这里的选择才用得上。')}</p>}
        <div className="ff-field">
          <span id={`${ids}-animation`}>{t('动效')}</span>
          <div className="pp-segment" role="radiogroup" aria-labelledby={`${ids}-animation`}>
            {options.title_animations.map(id => (
              <button key={id} type="button" role="radio" aria-checked={value.title.animation === id} disabled={busy}
                onClick={() => { if (value.title.animation !== id) onChange({ title: { animation: id } }, t('片名卡')); }}>
                {animationName(id)}
              </button>
            ))}
          </div>
        </div>
        <label className="ff-field">
          <span>{t('底图')}</span>
          <select value={backgroundClip ? String(clipKey(backgroundClip)) : ''} disabled={busy} onChange={event => pickBackground(event.target.value)}>
            <option value="">{t('默认深色底')}</option>
            {usable.map(clip => (
              <option key={clipKey(clip)} value={String(clipKey(clip))}>
                {clip.scene_id ? `${clip.scene_id} · ` : ''}{t('镜头 {0}', [clip.shot_id])}
              </option>
            ))}
          </select>
        </label>
        {backgroundClip && (
          <>
            <label className="pp-slider">
              <span>{t('取这一镜的第几秒')} <b>{t('{0} 秒', [moment.toFixed(1)])}</b></span>
              <input type="range" min={0} max={lastMoment(backgroundClip.duration)} step={0.1} value={moment} disabled={busy}
                onChange={event => setMomentDraft(Number(event.target.value))} onPointerUp={commitMoment} onKeyUp={commitMoment} onBlur={commitMoment} />
            </label>
            <video ref={frame} className="ff-frame" src={frameUrl} muted playsInline preload="metadata" tabIndex={-1}
              aria-label={t('片名卡底图预览')} />
            <p className="pp-muted">{t('合成时这一帧会略微压暗、虚化，片名压在上面。')}</p>
          </>
        )}
        {background && !backgroundClip && <p className="pp-muted">{t('原来选的那一镜已经不在时间线上，片名卡用回默认深色底。')}</p>}
        {!backgroundClip && value.title.animation === 'zoom' && <p className="pp-muted">{t('没选底图时，缓慢推近的是整张片名卡。')}</p>}
      </fieldset>

      <fieldset className="ff-group">
        <legend>{t('字幕样式')}</legend>
        {!subtitles && <p className="pp-muted">{t('嵌入字幕现在是关的，打开后这里的样式才用得上。')}</p>}
        <div className="ff-grid">
          {select('size', t('字号'), options.subtitle.sizes, sizeName)}
          {select('color', t('颜色'), options.subtitle.colors.map(item => item.id), colorName)}
          {select('position', t('位置'), options.subtitle.positions, positionName)}
          {select('outline', t('描边'), options.subtitle.outlines, outlineName)}
        </div>
        <p className={`ff-sample is-${value.subtitle.position}`} aria-hidden="true">
          <span style={{ color: `rgb(${sampleColor.join(', ')})`, fontSize: `${sampleSize}rem`, textShadow: SAMPLE_SHADOW[value.subtitle.outline] ?? 'none' }}>
            {t('字幕就是这个样子')}
          </span>
        </p>
        {value.subtitle.position === 'raised' && <p className="pp-muted">{t('偏上：给平台底部的按钮和文案让出位置。')}</p>}
      </fieldset>

      <fieldset className="ff-group">
        <legend>{t('全片调色')}</legend>
        <div className="ff-presets" role="group" aria-label={t('调色预设')}>
          {options.color.presets.map(preset => (
            <button key={preset.id} type="button" className="pp-ghost" aria-pressed={value.color.preset === preset.id} disabled={busy}
              onClick={() => { setGradeDraft({}); onChange({ color: { preset: preset.id } }, t('全片调色')); }}>
              {presetName(preset.id)}
            </button>
          ))}
        </div>
        {options.color.sliders.map(name => {
          const shown = gradeDraft[name] ?? value.color[name];
          return (
            <label key={name} className="pp-slider">
              <span>{sliderName(name)} <b>{signed(shown)}</b></span>
              <input type="range" min={-options.color.limit} max={options.color.limit} step={1} value={shown} disabled={busy}
                onChange={event => setGradeDraft(current => ({ ...current, [name]: Number(event.target.value) }))}
                onPointerUp={() => commitGrade(name)} onKeyUp={() => commitGrade(name)} onBlur={() => commitGrade(name)} />
            </label>
          );
        })}
        <div className="pp-row ff-reset">
          <span className="pp-muted">{presetName(value.color.preset)} · {t('只调镜头画面，片名卡、片尾卡和字幕不变。')}</span>
          <button type="button" className="pp-ghost" disabled={busy || neutral} onClick={resetGrade}>{t('重置')}</button>
        </div>
      </fieldset>

      <fieldset className="ff-group">
        <legend>{t('片尾卡')}</legend>
        <div className="ff-switch">
          <span>
            <strong>{t('最后一镜之后加一张片尾卡')}</strong>
            <small>{t('只显示你写的这一行字，约 {0} 秒', [options.ending.seconds])}</small>
          </span>
          <button type="button" role="switch" aria-checked={value.ending.enabled} aria-label={t('片尾卡')} className="pp-switch" disabled={busy}
            onClick={toggleEnding}><i aria-hidden="true" /></button>
        </div>
        <label className="ff-field ff-field--stack">
          <span>{t('片尾文字')}</span>
          <input type="text" value={endingText} maxLength={options.ending.max_chars} disabled={busy} placeholder={t('比如：明晚见')}
            onChange={event => setEndingDraft(event.target.value)} onBlur={commitEnding}
            onKeyDown={event => { if (event.key === 'Enter') commitEnding(); }} />
        </label>
        {teaser && endingText.trim() !== teaser && (
          <button type="button" className="pp-ghost ff-teaser" disabled={busy} title={teaser}
            onClick={() => { setEndingDraft(null); onChange({ ending: { text: teaser } }, t('片尾卡')); }}>
            {t('填入下集预告')}
          </button>
        )}
        {value.ending.enabled && !value.ending.text && <p className="pp-muted">{t('片尾卡开着但还没写字，写了才会出现。')}</p>}
      </fieldset>
    </section>
  );
}
