import { useEffect, useState } from 'react';

import { t } from '../../i18n';
import { diagnoseCamera, type CameraDiagnosis } from './canvasBeefApi';

/**
 * 「机位诊断」方式下，先把规则检查看出的问题摆出来：不调用模型、不花钱、不改提示词。
 * 四项按固定顺序查，最先查出问题的那一项是主因；下面附这条提示词情绪对应的机位取法。
 */
export function CanvasBeefCameraDiagnosis({ taskId, prompt, medium }: { taskId: string; prompt: string; medium: 'image' | 'video' }) {
  const [found, setFound] = useState<CameraDiagnosis | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    diagnoseCamera(taskId, prompt, medium, controller.signal)
      .then(data => { setFound(data); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [taskId, prompt, medium]);

  if (failed) return <p className="canvas-beef-diagnosis__note" role="status">{t('规则检查没有读出来，不影响下面的重写')}</p>;
  if (!found) return <p className="canvas-beef-diagnosis__note" role="status">{t('正在按规则检查这条提示词…')}</p>;
  const row = found.reference.emotions.find(item => item.label === found.emotion);
  return (
    <section className="canvas-beef-diagnosis" aria-label={t('规则检查')}>
      <strong>{t('规则检查先看出的问题（不调用模型）')}</strong>
      {found.findings.length === 0 ? (
        <p className="canvas-beef-diagnosis__note">{t('四项检查都没有查出明显问题：相机在哪、机位与情绪、运镜、矛盾与否定句')}</p>
      ) : (
        <ol>
          {found.findings.map((item, index) => (
            <li key={`${item.code}-${index}`}>
              <span className="canvas-beef-diagnosis__title">
                {item.title}{index === 0 && <em>{t('主因')}</em>}
              </span>
              <span>{item.detail}</span>
            </li>
          ))}
        </ol>
      )}
      {row && (
        <details>
          <summary>{t('「{0}」通常这样拍', [row.label])}</summary>
          <dl>
            {row.recipe.map(part => (
              <div key={part.dimension}><dt>{part.dimension}</dt><dd>{part.take}</dd></div>
            ))}
          </dl>
          <p className="canvas-beef-diagnosis__note">{row.why} {row.avoid}</p>
        </details>
      )}
      <details>
        <summary>{t('十二种情绪的机位对照')}</summary>
        <p className="canvas-beef-diagnosis__note">{found.reference.principle}</p>
        <ul className="canvas-beef-diagnosis__table">
          {found.reference.emotions.map(item => (
            <li key={item.id}><b>{item.label}</b>{item.recipe.map(part => part.take).join('；')}</li>
          ))}
        </ul>
        <p className="canvas-beef-diagnosis__note">
          {t('一场戏里情绪要有变化：')}{found.reference.turns.map(turn => `${turn.name}（${turn.how}）`).join('；')}
        </p>
      </details>
    </section>
  );
}
