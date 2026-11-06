import { useState } from 'react';

import { t } from '../../i18n';
import type { ShotPilot } from './shotVisual';

interface Props {
  pilot: ShotPilot;
  locked: boolean;
  /** Generate the rest; the clip tried here is reused. */
  onPass: () => void;
  onRedo: (problems: string[]) => void;
  onRetry: () => void;
}

/** The one clip made before the batch: look at it, then let the batch go or make it again. */
export function PilotShotCard({ pilot, locked, onPass, onRedo, onRetry }: Props) {
  const [problems, setProblems] = useState<string[]>([]);
  const toggle = (item: string) => setProblems(current => (current.includes(item) ? current.filter(name => name !== item) : [...current, item]));

  if (pilot.state === 'requested' || pilot.state === 'running') {
    return (
      <section className="shot-workspace__pilot is-running" aria-label={t('首镜试拍')} role="status">
        <header><strong>{t('正在试拍')}{pilot.label ? ` · ${pilot.label}` : ''}</strong></header>
        {pilot.reason && <p>{pilot.reason}</p>}
      </section>
    );
  }

  if (pilot.state === 'failed') {
    return (
      <section className="shot-workspace__pilot is-failed" aria-label={t('首镜试拍')}>
        <header><strong>{t('试拍没有出片')}{pilot.label ? ` · ${pilot.label}` : ''}</strong></header>
        {pilot.error && <p>{pilot.error}</p>}
        <div className="shot-workspace__pilot-actions">
          <button type="button" className="secondary-action" disabled={locked} onClick={onRetry}>{t('再试一次')}</button>
        </div>
      </section>
    );
  }

  return (
    <section className="shot-workspace__pilot is-ready" aria-label={t('首镜试拍')}>
      <header>
        <strong>{t('试拍好了，先看这一段')}{pilot.label ? ` · ${pilot.label}` : ''}</strong>
        {pilot.reason && <span>{pilot.reason}</span>}
      </header>
      <div className="shot-workspace__pilot-body">
        {pilot.video_url && <video src={pilot.video_url} controls loop preload="metadata" aria-label={t('试拍片段')} />}
        <div>
          <fieldset className="shot-workspace__pilot-checks">
            <legend>{t('哪里不对？没问题就不用勾')}</legend>
            {(pilot.checks ?? []).map(item => (
              <label key={item}>
                <input type="checkbox" checked={problems.includes(item)} onChange={() => toggle(item)} /> {t(item)}
              </label>
            ))}
          </fieldset>
          <div className="shot-workspace__pilot-actions">
            <button type="button" className="primary-action" disabled={locked || problems.length > 0} onClick={onPass}>
              {pilot.others_left ? t('通过，生成其余 {count} 镜', { count: pilot.others_left }) : t('通过')}
            </button>
            <button type="button" className="secondary-action" disabled={locked} onClick={() => onRedo(problems)}>{t('不行，重拍这一段')}</button>
          </div>
          {problems.length > 0 && <p>{t('勾了问题就先别放开整批。可以先改下面的运镜或提示词，再重拍。')}</p>}
        </div>
      </div>
    </section>
  );
}
