import { Clock3, Film, Grid3X3, Layers3 } from 'lucide-react';

import { PromptFields, PromptSection } from './PromptPrimitives';
import { TIME_BEAT_PLANNING_RULES } from './promptRules';
import type { PromptValue, StoryboardPromptDetail } from './storyboardPromptTypes';
import { t } from '../../i18n';

export function PromptTimelineSections({ detail }: { detail: StoryboardPromptDetail }) {
  const failedChecks = detail.continuity_checks.filter(check => check.passed === false);
  const errorMessages = Array.from(new Set(
    failedChecks
      .filter(check => check.severity !== 'warning')
      .map(check => String(check.detail || check.code || '未提供具体失败原因')),
  ));
  const warningMessages = Array.from(new Set([
    ...failedChecks
      .filter(check => check.severity === 'warning')
      .map(check => String(check.detail || check.code || '未提供具体提示')),
    ...(detail.warnings || []),
  ]));
  const qualityStatus = detail.submission_ready === false || errorMessages.length > 0
    ? '需修正'
    : warningMessages.length > 0
      ? '通过（有提示）'
      : detail.submission_ready === true
        ? '通过'
        : '待检查';

  return (
    <>
      <PromptSection title={t('逐拍出图提示词')} icon={<Layers3 aria-hidden="true" />}>
        <div className="prompt-detail__requirements">
          <strong>{t('通用出图要求')}</strong>
          <p>{t('只生成一张独立完整画面。禁止宫格、拼贴、分屏、边框、编号、字幕、水印和无关文字。')}</p>
          <p>{t('保持角色外貌、服装、污渍、场景结构、摄影机轴线、光源方向和色彩系统一致。')}</p>
        </div>
        <div className="prompt-detail__stack">
          {detail.still_prompts.map((item, index) => (
            <article className="prompt-detail__prompt-card" key={index}>
              <header><h3>连续瞬间 {String(item.beat_index ?? index + 1)}</h3><span>{String(item.keyframe_seconds ?? 0)}s</span></header>
              <pre>{String(item.prompt || '')}</pre>
              <PromptFields value={{ exclusions: item.exclusions }} />
            </article>
          ))}
        </div>
      </PromptSection>

      <PromptSection title={t('分段运镜视频提示词')} icon={<Film aria-hidden="true" />}>
        <div className="prompt-detail__stack">
          {detail.video_segments.length === 0 && <p className="prompt-detail__muted">{t('单拍点镜头无需相邻关键帧连接视频。')}</p>}
          {detail.video_segments.map((item, index) => (
            <article className="prompt-detail__prompt-card" key={index}>
              <header><h3>视频片段 {String(item.segment_index ?? index + 1)}</h3><span>{String(item.start_seconds ?? 0)}s ～ {String(item.end_seconds ?? 0)}s</span></header>
              <pre>{String(item.prompt || '')}</pre>
              <PromptFields value={{ exclusions: item.exclusions }} />
            </article>
          ))}
        </div>
      </PromptSection>

      <details className="prompt-detail__advanced">
        <summary>{t('拍点规划与宫格合成')}</summary>
        <div className="prompt-detail__advanced-content">
          <PromptSection title={t('时间拍点规划规则')} icon={<Clock3 aria-hidden="true" />}>
            <ol className="prompt-detail__numbered-rules">{TIME_BEAT_PLANNING_RULES.map(rule => <li key={rule}>{rule}</li>)}</ol>
          </PromptSection>

          <PromptSection title={t('时间拍点')} icon={<Clock3 aria-hidden="true" />}>
            <div className="prompt-detail__stack">
              {detail.beats.map(beat => (
                <article className="prompt-detail__beat" key={beat.index}>
                  <header><strong>{beat.index}</strong><h3>{beat.core_event}</h3><span>{beat.start_seconds}s ～ {beat.end_seconds}s</span></header>
                  <PromptFields value={beat as unknown as Record<string, PromptValue>} omit={['index', 'page_number', 'page_slot', 'core_event', 'start_seconds', 'end_seconds']} />
                </article>
              ))}
            </div>
          </PromptSection>

          <PromptSection title={t('宫格合成说明')} icon={<Grid3X3 aria-hidden="true" />}>
            {detail.grid_pages.map((page, index) => (
              <article className="prompt-detail__prompt-card" key={index}>
                <header><h3>第 {String(page.page_number ?? index + 1)} 页 · 3×3</h3><span>{String(page.used_slots ?? 0)} 个拍点 / {String(page.empty_slots ?? 0)} 个留白</span></header>
                <pre>{String(page.composite_prompt || '')}</pre>
              </article>
            ))}
          </PromptSection>

          {/* 连续性检查是管线诊断信息，不混入可复制的提示词正文。 */}
        </div>
      </details>

      <details className="prompt-detail__advanced prompt-detail__quality" data-status={qualityStatus}>
        <summary>连续性检查 · {qualityStatus}</summary>
        <div className="prompt-detail__advanced-content">
          {qualityStatus === '通过' ? (
            <p className="prompt-detail__muted">{detail.continuity_checks.length} 项连续性检查全部通过。</p>
          ) : qualityStatus === '待检查' ? (
            <p className="prompt-detail__muted">{t('尚未提供连续性检查结果。')}</p>
          ) : (
            <div className="prompt-detail__checks">
              {errorMessages.map(message => (
                <p className="is-failed" key={message}><span>!</span>{message}</p>
              ))}
              {warningMessages.map(message => (
                <p className="is-warning" key={message}><span>i</span>{message}</p>
              ))}
              {qualityStatus === '需修正' && errorMessages.length === 0 && warningMessages.length === 0 && (
                <p className="is-failed"><span>!</span>{t('尚未提供具体检查结果。')}</p>
              )}
            </div>
          )}
        </div>
      </details>
    </>
  );
}
