import { CheckCircle2, Clock3, Film, Grid3X3, Layers3 } from 'lucide-react';

import { PromptFields, PromptSection } from './PromptPrimitives';
import { TIME_BEAT_PLANNING_RULES } from './promptRules';
import type { PromptValue, StoryboardPromptDetail } from './storyboardPromptTypes';

export function PromptTimelineSections({ detail }: { detail: StoryboardPromptDetail }) {
  return (
    <>
      <PromptSection title="时间拍点规划规则" icon={<Clock3 aria-hidden="true" />}>
        <ol className="prompt-detail__numbered-rules">{TIME_BEAT_PLANNING_RULES.map(rule => <li key={rule}>{rule}</li>)}</ol>
      </PromptSection>

      <PromptSection title="时间拍点" icon={<Clock3 aria-hidden="true" />}>
        <div className="prompt-detail__stack">
          {detail.beats.map(beat => (
            <article className="prompt-detail__beat" key={beat.index}>
              <header><strong>{beat.index}</strong><h3>{beat.core_event}</h3><span>{beat.start_seconds}s ～ {beat.end_seconds}s</span></header>
              <PromptFields value={beat as unknown as Record<string, PromptValue>} omit={['index', 'page_number', 'page_slot', 'core_event', 'start_seconds', 'end_seconds']} />
            </article>
          ))}
        </div>
      </PromptSection>

      <PromptSection title="逐拍出图提示词" icon={<Layers3 aria-hidden="true" />}>
        <div className="prompt-detail__requirements">
          <strong>通用出图要求</strong>
          <p>只生成一张独立完整画面。禁止宫格、拼贴、分屏、边框、编号、字幕、水印和无关文字。</p>
          <p>保持角色外貌、服装、污渍、场景结构、摄影机轴线、光源方向和色彩系统一致。</p>
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

      <PromptSection title="分段运镜视频提示词" icon={<Film aria-hidden="true" />}>
        <div className="prompt-detail__stack">
          {detail.video_segments.length === 0 && <p className="prompt-detail__muted">单拍点镜头无需相邻关键帧连接视频。</p>}
          {detail.video_segments.map((item, index) => (
            <article className="prompt-detail__prompt-card" key={index}>
              <header><h3>视频片段 {String(item.segment_index ?? index + 1)}</h3><span>{String(item.start_seconds ?? 0)}s ～ {String(item.end_seconds ?? 0)}s</span></header>
              <pre>{String(item.prompt || '')}</pre>
              <PromptFields value={{ exclusions: item.exclusions }} />
            </article>
          ))}
        </div>
      </PromptSection>

      <PromptSection title="宫格合成说明" icon={<Grid3X3 aria-hidden="true" />}>
        {detail.grid_pages.map((page, index) => (
          <article className="prompt-detail__prompt-card" key={index}>
            <header><h3>第 {String(page.page_number ?? index + 1)} 页 · 3×3</h3><span>{String(page.used_slots ?? 0)} 个拍点 / {String(page.empty_slots ?? 0)} 个留白</span></header>
            <pre>{String(page.composite_prompt || '')}</pre>
          </article>
        ))}
      </PromptSection>

      <PromptSection title="连续性自检" icon={<CheckCircle2 aria-hidden="true" />} meta={detail.submission_ready ? '可提交' : '需修正'}>
        <div className="prompt-detail__checks">
          {detail.continuity_checks.map((check, index) => (
            <p className={check.passed ? 'is-passed' : 'is-failed'} key={index}>
              <span>{check.passed ? '✓' : '!'}</span>{String(check.detail || check.code || '')}
            </p>
          ))}
        </div>
      </PromptSection>
    </>
  );
}
