import { useId, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

import { scriptReadingView } from './storyboardPromptSummary';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';
import { t } from '../../i18n';

export function PromptScriptExcerpt({ detail }: { detail: StoryboardPromptDetail }) {
  const [expanded, setExpanded] = useState(false);
  const sourceId = useId();
  const view = scriptReadingView(detail);

  return (
    <div className="prompt-script">
      <div className="prompt-script__heading">
        <h3>{view.heading}</h3>
        <span>{view.label}</span>
      </div>
      <blockquote className="prompt-detail__script prompt-script__preview" data-testid="script-preview">
        {view.excerptParagraphs.length
          ? view.excerptParagraphs.slice(0, 3).map((paragraph, index) => <p key={index}>{paragraph}</p>)
          : <p>{t('未提供剧本原文')}</p>}
      </blockquote>
      {view.expandable && (
        <>
          <button
            className="prompt-script__toggle"
            type="button"
            aria-expanded={expanded}
            aria-controls={sourceId}
            onClick={() => setExpanded(value => !value)}
          >
            {expanded ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
            {expanded ? t('收起完整剧本原文') : t('展开完整剧本原文')}
          </button>
          {expanded && (
            <div id={sourceId} className="prompt-script__source" role="region" aria-label={t('完整剧本原文')} tabIndex={0}>
              {view.sourceParagraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
