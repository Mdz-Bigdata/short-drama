import { RotateCcw, Save } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';

import { t } from '../../i18n';
import {
  MENTION_KIND_LABELS,
  mentionKindClass,
  parseMentions,
  resolveMentions,
  splitMentions,
} from './promptMentions';
import type { MentionCandidate } from './mentionAutocomplete';
import { MentionMenu } from './MentionMenu';
import { useMentionCandidates } from './useMentionCandidates';
import { useMentionInput } from './useMentionInput';

interface Props {
  shotId: number;
  prompt: string;
  edited: boolean;
  mentionKinds: Record<string, string>;
  referenceNumbers: Record<string, number>;
  locked: boolean;
  saving: boolean;
  onSave: (prompt: string | null) => Promise<void> | void;
  /** 上次离开这个编辑器时还没保存的草稿；调用方按同一个 key 记着，换页签回来接着改。 */
  initialDraft?: string;
  onDraftChange?: (draft: string) => void;
  /** 有项目 id 就从后端读可 @ 的人物、场景、道具。 */
  taskId?: string;
  /** 调用方已经有候选就直接给；都没有时用 mentionKinds 里已登记的名字。 */
  mentionCandidates?: MentionCandidate[];
}

type View = 'text' | 'preview';

/**
 * 视频提示词编辑器：@[名字] 按资产类型着色，可改可存；「解析预览」显示发给模型前的样子。
 * 正在改的草稿在本组件里；调用方用「镜头 + 已保存文本」作 key，并按同一个 key 记着没保存的草稿，
 * 换页签、换镜头回来接着改。保存或恢复自动编译成功后，调用方要丢掉这一镜记着的草稿，
 * 否则服务端文本再变回原样时，已经保存过的旧草稿会当成「未保存」冒出来。
 */
export function VideoPromptEditor({ shotId, prompt, edited, mentionKinds, referenceNumbers, locked, saving, onSave, initialDraft, onDraftChange, taskId, mentionCandidates }: Props) {
  const [view, setView] = useState<View>('text');
  const [draft, setDraft] = useState(initialDraft ?? prompt);
  const highlight = useRef<HTMLPreElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const loaded = useMentionCandidates(mentionCandidates ? undefined : taskId);
  const fallbackCandidates = useMemo<MentionCandidate[]>(
    () => Object.entries(mentionKinds).map(([name, kind]) => ({ name, kind })),
    [mentionKinds],
  );
  const candidates = mentionCandidates ?? (taskId && loaded.items.length ? loaded.items : fallbackCandidates);
  const changeDraft = (next: string) => { setDraft(next); onDraftChange?.(next); };
  const mention = useMentionInput({ value: draft, onChange: changeDraft, candidates, inputRef: field, disabled: locked });

  const dirty = draft !== prompt;
  const mentions = useMemo(() => parseMentions(draft), [draft]);
  const resolved = useMemo(() => resolveMentions(draft, referenceNumbers), [draft, referenceNumbers]);
  const status = dirty ? t('未保存') : edited ? t('已人工修改') : t('已同步');

  return (
    <section className="video-prompt-editor" aria-label={`镜头 ${shotId} 视频提示词`}>
      <div className="video-prompt-editor__bar">
        <div className="video-prompt-editor__views" role="tablist" aria-label={t('提示词视图')}>
          {([['text', '文稿'], ['preview', '解析预览']] as Array<[View, string]>).map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={view === key}
              className={view === key ? 'is-active' : ''} onClick={() => setView(key)}>
              {t(label)}
            </button>
          ))}
        </div>
        <small className="video-prompt-editor__count">{draft.length} {t('字')}</small>
      </div>

      {view === 'text' ? (
        <div className="video-prompt-editor__field">
          <pre ref={highlight} className="video-prompt-editor__highlight" aria-hidden="true">
            {splitMentions(draft).map((part, index) => (
              part.mention
                ? <mark key={index} className={`video-prompt-mention ${mentionKindClass(mentionKinds[part.mention])}`}>{part.text}</mark>
                : <span key={index}>{part.text}</span>
            ))}
            {'\n'}
          </pre>
          <textarea
            ref={field}
            {...mention.inputProps}
            aria-label={t('视频提示词文稿')}
            value={draft}
            disabled={locked}
            spellCheck={false}
            onChange={event => changeDraft(event.target.value)}
            onKeyDown={event => { mention.onKeyDown(event); }}
            onScroll={event => {
              if (highlight.current) highlight.current.scrollTop = event.currentTarget.scrollTop;
            }}
          />
          <MentionMenu {...mention.menuProps} />
        </div>
      ) : (
        <div className="video-prompt-editor__preview" role="tabpanel">
          {mentions.length > 0 ? (
            <ul aria-label={t('引用的资产')}>
              {mentions.map(name => (
                <li key={name}>
                  <mark className={`video-prompt-mention ${mentionKindClass(mentionKinds[name])}`}>@[{name}]</mark>
                  <span>{MENTION_KIND_LABELS[mentionKinds[name] ?? ''] ?? t('未登记的资产')}</span>
                  <small>{referenceNumbers[name] ? `参考图 ${referenceNumbers[name]}` : t('无参考图，只保留名字')}</small>
                </li>
              ))}
            </ul>
          ) : (
            <p className="shot-workspace__hint">{t('提示词里没有 @[名字] 引用。')}</p>
          )}
          <h5>{t('发给视频模型的文本')}</h5>
          <pre>{resolved || t('待生成')}</pre>
        </div>
      )}

      <div className="video-prompt-editor__footer">
        <span className={`video-prompt-editor__status ${dirty ? 'is-dirty' : ''}`} role="status">● {status}</span>
        {edited && !dirty && (
          <button type="button" className="secondary-action" disabled={locked || saving} onClick={() => { void onSave(null); }}>
            <RotateCcw size={13} aria-hidden="true" /> {t('恢复自动编译')}
          </button>
        )}
        <button type="button" className="secondary-action" disabled={!dirty || locked || saving || !draft.trim()}
          onClick={() => { void onSave(draft); }}>
          <Save size={13} aria-hidden="true" /> {saving ? t('保存中…') : t('保存')}
        </button>
      </div>
    </section>
  );
}
