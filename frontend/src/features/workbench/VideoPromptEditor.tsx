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

interface Props {
  shotId: number;
  prompt: string;
  edited: boolean;
  mentionKinds: Record<string, string>;
  referenceNumbers: Record<string, number>;
  locked: boolean;
  saving: boolean;
  onSave: (prompt: string | null) => Promise<void> | void;
}

type View = 'text' | 'preview';

/**
 * 视频提示词编辑器：@[名字] 按资产类型着色，可改可存；「解析预览」显示发给模型前的样子。
 * 草稿只在本组件里；调用方用「镜头 + 已保存文本」作 key，切换镜头或保存后自然换成服务端的版本。
 */
export function VideoPromptEditor({ shotId, prompt, edited, mentionKinds, referenceNumbers, locked, saving, onSave }: Props) {
  const [view, setView] = useState<View>('text');
  const [draft, setDraft] = useState(prompt);
  const highlight = useRef<HTMLPreElement>(null);

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
            aria-label={t('视频提示词文稿')}
            value={draft}
            disabled={locked}
            spellCheck={false}
            onChange={event => setDraft(event.target.value)}
            onScroll={event => {
              if (highlight.current) highlight.current.scrollTop = event.currentTarget.scrollTop;
            }}
          />
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
