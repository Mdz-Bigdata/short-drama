import { useEffect, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { ApiError, apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { NO_GO_CHARS, NO_GO_ITEMS, noGoLines } from './storyNoGo';
import './StoryDirectionPicker.css';

/** 热点一句话的长度上限；与 backend/app/data/prompt/story_direction.json 的 trend_chars 一致。 */
const TREND_CHARS = 300;

export interface StoryDirection {
  title: string;
  logline: string;
  conflict: string;
  hook: string;
  appeal: string;
}

export interface StoryDirectionRequest {
  idea: string;
  creationMode: string;
  episodeCount: number;
  targetAudience?: { lean: string; age: string };
  scriptStructure?: string;
  llmModel: string;
}

/**
 * 立项前的两件事：让文本模型按这句想法提几个真正不一样的故事方向，挑一个(再点一次取消)；
 * 再写下「创作禁区」。挑中的方向和禁区随新建请求一起发出，总导演照着写方案，禁区同时告诉每一批分集规划。
 * 提方向会调用一次文本模型，所以只在点了按钮之后才发请求。
 * 想法框空着也能提：按创作类型和目标观众推荐几个题材不同的方向，挑中的那个写进想法框(onIdea)。
 */
export function StoryDirectionPicker({ request, value, onChange, noGo, onNoGoChange, onIdea }: {
  request: StoryDirectionRequest;
  value: StoryDirection | null;
  onChange: (next: StoryDirection | null) => void;
  noGo: string;
  onNoGoChange: (next: string) => void;
  /** 想法框还空着时挑了一个推荐方向：把它写进想法框，项目才有东西可立。 */
  onIdea?: (idea: string) => void;
}) {
  const [directions, setDirections] = useState<StoryDirection[]>([]);
  // 服务器给每个方向配的「想法」写法，下标与 directions 对齐。
  const [ideas, setIdeas] = useState<string[]>([]);
  // 上一次由本组件写进想法框的字：创作者没改过它，换挑一个方向时才跟着换。
  const written = useRef('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // 想借的热点或热梗：创作者自己写的一句话，只随「提方向」的请求发出，不存进项目。
  const [trend, setTrend] = useState('');
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => running.current?.abort(), []);

  const hasIdea = request.idea.trim().length >= 2;
  const hasModel = request.llmModel.trim() !== '';
  const ready = hasModel;
  const lines = noGoLines(noGo);

  const propose = async () => {
    running.current?.abort();
    const controller = new AbortController();
    running.current = controller;
    setBusy(true);
    setError('');
    try {
      const answer = await apiRequest<{ directions: StoryDirection[]; ideas?: string[] }>('/api/story-directions', {
        method: 'POST', signal: controller.signal, body: JSON.stringify({ ...request, storyNoGo: lines, ...(trend.trim() ? { trend: trend.trim() } : {}) }),
      });
      setDirections(answer.directions);
      setIdeas(answer.ideas ?? []);
      // The picked one stays picked only while it is still on offer.
      if (value && !answer.directions.some(item => item.title === value.title && item.logline === value.logline)) onChange(null);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof ApiError && reason.message ? reason.message : t('故事方向没有拿到，可以再试一次'));
    } finally {
      if (running.current === controller) {
        running.current = null;
        setBusy(false);
      }
    }
  };

  const choose = (item: StoryDirection, index: number, chosen: boolean) => {
    onChange(chosen ? null : item);
    if (chosen || !onIdea) return;
    const typed = request.idea.trim();
    // Only an empty box, or one still holding what the last pick wrote, is filled: the creator's own words are theirs.
    if (typed && typed !== written.current) return;
    const idea = (directions.length ? ideas[index] : '') || `${item.title}：${item.logline}`;
    written.current = idea.trim();
    onIdea(idea);
  };

  const shown = directions.length ? directions : value ? [value] : [];
  return (
    <div className="direction-picker">
      <div className="direction-picker__head">
        <span id="new-project-direction-label" className="direction-picker__title">{t('故事方向')}</span>
        <span className="direction-picker__note">{value ? t('已选：{0}（再点一次取消）', [value.title]) : t('不选由总导演定')}</span>
      </div>
      <div className="direction-picker__ask">
        <button type="button" className="capsule-btn" disabled={!ready || busy} onClick={() => { void propose(); }}>
          {busy && <LoaderCircle className="spin" size={14} aria-hidden="true" />}
          {busy ? t('正在想方向…') : directions.length ? t('换一批方向') : hasIdea ? t('先给我几个故事方向') : t('还没想法？给我推荐几个方向')}
        </button>
        <span className="direction-picker__note">
          {!ready ? t('还没有可用的文本模型，先到模型设置里启用一个')
            : hasIdea ? t('会用 {0} 调用一次文本模型', [request.llmModel])
              : t('不写想法也行：按创作类型和目标观众推荐几个题材不同的方向，挑中的会写进想法框。会用 {0} 调用一次文本模型', [request.llmModel])}
        </span>
      </div>
      <label className="direction-picker__nogo">
        <span className="direction-picker__title">{t('想借的热点（可不填）')}</span>
        <input
          type="text" value={trend} maxLength={TREND_CHARS} disabled={busy}
          placeholder={t('写一句最近的热点或热梗，比如「素人一句话怼哭评委」')} onChange={event => setTrend(event.target.value)}
        />
        <span className="direction-picker__note">{t('只借它的情绪和故事结构写成原创的人和事，不照搬真人真事；平台没有热榜数据，热点由你来写。')}</span>
      </label>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {shown.length > 0 && (
        <div className="direction-picker__cards" role="radiogroup" aria-labelledby="new-project-direction-label">
          {shown.map((item, index) => {
            const chosen = value?.title === item.title && value.logline === item.logline;
            return (
              <button
                key={`${item.title}-${item.logline}`} type="button" role="radio" aria-checked={chosen}
                className={`direction-picker__card${chosen ? ' is-active' : ''}`} onClick={() => choose(item, index, chosen)}
              >
                <strong>{item.title}</strong>
                <span>{item.logline}</span>
                {item.conflict && <span><em>{t('核心冲突')}</em>{item.conflict}</span>}
                {item.hook && <span><em>{t('开场钩子')}</em>{item.hook}</span>}
                {item.appeal && <span><em>{t('看点')}</em>{item.appeal}</span>}
              </button>
            );
          })}
        </div>
      )}
      <label className="direction-picker__nogo">
        <span className="direction-picker__title">{t('创作禁区（可不填）')}</span>
        <textarea
          value={noGo} rows={2} maxLength={NO_GO_ITEMS * (NO_GO_CHARS + 4)}
          placeholder={t('一行写一条不想要的东西，比如「不要失忆梗」')} onChange={event => onNoGoChange(event.target.value)}
        />
        <span className="direction-picker__note">
          {lines.length ? t('{0} 条，整部剧都不会出现', [lines.length]) : t('最多 {0} 条，每条 {1} 字以内', [NO_GO_ITEMS, NO_GO_CHARS])}
        </span>
      </label>
    </div>
  );
}
