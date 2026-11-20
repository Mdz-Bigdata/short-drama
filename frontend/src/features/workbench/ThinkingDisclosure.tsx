import { Brain } from 'lucide-react';

import { t } from '../../i18n';
import './ThinkingDisclosure.css';

/**
 * The readable thinking a model returned with a reply, folded above it.
 *
 * Opening it changes nothing but this view. It is the model's own text: reference only, never a record that
 * something was done or permission to do it. When the model returned none, nothing is shown.
 */
export function ThinkingDisclosure({ text }: { text?: string }) {
  const thinking = (text ?? '').trim();
  if (!thinking) return null;
  return (
    <details className="thinking-disclosure">
      <summary><Brain size={13} aria-hidden="true" />{t('思考过程')}</summary>
      <div className="thinking-disclosure__body">{thinking}</div>
      <p className="thinking-disclosure__note">{t('由模型给出，仅供参考；不代表已经执行了什么，也不是授权。')}</p>
    </details>
  );
}
