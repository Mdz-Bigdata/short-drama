import { Wand2 } from 'lucide-react';

import { t } from '../../i18n';
import type { ReferenceLimits } from './canvasBeefApi';
import { checkReferences, type ReferenceProblem, type ReferenceRole, type RoleSuggestion } from './canvasBeefReferences';
import type { CanvasEdge, CanvasNode } from './canvasTypes';
import './CanvasBeef.css';

const ROLE_LABEL: Record<ReferenceRole, string> = {
  first_frame: '首帧', last_frame: '尾帧', ref_image: '参考图', ref_video: '参考视频', continue_from: '接着上一段', ref_audio: '参考音频',
};

function problemText(problem: ReferenceProblem): string {
  switch (problem.code) {
    case 'too_many_images': return t('参考图 {0} 张，超过上限 {1} 张', [problem.count ?? 0, problem.limit ?? 0]);
    case 'too_many_videos': return t('参考视频 {0} 段，超过上限 {1} 段', [problem.count ?? 0, problem.limit ?? 0]);
    case 'too_many_audios': return t('参考音频 {0} 段，超过上限 {1} 段', [problem.count ?? 0, problem.limit ?? 0]);
    case 'first_and_continue': return t('已经接着上一段，不能再指定首帧');
    case 'two_firsts': return t('有 {0} 张图都标成了首帧，只能有一张', [problem.count ?? 0]);
    case 'two_lasts': return t('有 {0} 张图都标成了尾帧，只能有一张', [problem.count ?? 0]);
    case 'last_without_first': return t('只有尾帧没有首帧，有的模型会忽略尾帧');
  }
}

export interface CanvasBeefReferencePanelProps {
  target: CanvasNode;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  limits: ReferenceLimits;
  /** The suggested roles; write them with applySuggestions onto the edges as they are when applied. */
  onApply: (suggestions: RoleSuggestion[]) => void;
}

/** Smart reference for a clip node: which connected picture should open or close the clip, and whether the references fit. */
export function CanvasBeefReferencePanel({ target, nodes, edges, limits, onApply }: CanvasBeefReferencePanelProps) {
  const check = checkReferences(target, nodes, edges, limits);
  if (!check.suggestions.length && !check.problems.length) return null;
  const label = (id: string) => {
    const node = nodes.find(item => item.id === id);
    return String(node?.payload.title || node?.payload.label || id);
  };
  return (
    <section className="canvas-beef-refs" aria-label={t('智能参考')}>
      {check.suggestions.length > 0 && (
        <>
          <strong><Wand2 size={13} aria-hidden="true" /> {t('智能参考建议')}</strong>
          <ul>
            {check.suggestions.map(item => (
              <li key={item.edgeId}>{t('「{0}」：{1} → {2}', [label(item.sourceId), t(ROLE_LABEL[item.from]), t(ROLE_LABEL[item.to])])}</li>
            ))}
          </ul>
          <button type="button" onClick={() => onApply(check.suggestions)}>{t('按建议设置')}</button>
        </>
      )}
      {check.problems.length > 0 && (
        <ul className="canvas-beef-refs__problems" role="alert">
          {check.problems.map(problem => <li key={problem.code}>{problemText(problem)}</li>)}
        </ul>
      )}
    </section>
  );
}
