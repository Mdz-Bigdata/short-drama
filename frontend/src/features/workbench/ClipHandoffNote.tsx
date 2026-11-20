import { useEffect, useState } from 'react';

import { t } from '../../i18n';
import { fetchEpisodeHandoff, type HandoffPair, type HandoffReport, type ShotRef } from './clipHandoffApi';
import { episodeNumberOf } from './shotVisual';
import './ClipHandoffNote.css';

const same = (ref: ShotRef, sceneId: string, shotId: number | string) => ref.scene_id === sceneId && String(ref.shot_id) === String(shotId);

function Cut({ title, pair }: { title: string; pair: HandoffPair }) {
  return (
    <li className={`clip-handoff__cut is-${pair.verdict}`}>
      <b>{title}</b> <span>{pair.label}</span>
      {(pair.tail || pair.head) && <small>{[pair.tail, pair.head].filter(Boolean).join('；')}</small>}
      {pair.findings.length > 0 && <ul>{pair.findings.map(item => <li key={item.code}>{item.text}</li>)}</ul>}
    </li>
  );
}

/**
 * 镜头衔接质检：这一镜和前后两镜在切点两边接不接得上——运动方向是否连续、结尾是否适合接下一镜、
 * 主体出画入画是否对得上。量的是已经生成的片子(本机 ffmpeg，不花钱)，结论只是提示。
 * 点一次「查衔接」之后，换镜头、换版本都会跟着重新读(量过的片段有缓存)。
 */
export function ClipHandoffNote({ taskId, sceneId, shotId, videoUrl }: { taskId: string; sceneId: string; shotId: number | string; videoUrl: string }) {
  const [asked, setAsked] = useState(false);
  const [report, setReport] = useState<HandoffReport | null>(null);
  const [failed, setFailed] = useState(false);
  const episode = episodeNumberOf(sceneId);

  useEffect(() => {
    if (!asked || !taskId || !videoUrl) return undefined;
    let live = true;
    fetchEpisodeHandoff(taskId, episode)
      .then(value => { if (live) { setReport(value); setFailed(false); } })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [asked, taskId, episode, videoUrl]);

  if (!videoUrl) return null;
  if (!asked) {
    return (
      <button type="button" className="secondary-action clip-handoff__ask" onClick={() => setAsked(true)}
        title={t('量一下这一镜和前后两镜接不接得上：运动方向、结尾落幅、出画入画；本机处理，免费')}>
        {t('查衔接')}
      </button>
    );
  }
  if (failed) return <p className="clip-handoff__note" role="status">{t('衔接质检暂时读不出来。')}</p>;
  if (!report || report.episode !== episode) return <p className="clip-handoff__note" role="status">{t('正在量这一集的衔接…')}</p>;
  const into = report.pairs.find(pair => same(pair.to, sceneId, shotId));
  const out = report.pairs.find(pair => same(pair.from, sceneId, shotId));
  if (!into && !out) return <p className="clip-handoff__note">{t('这一镜前后没有能比的片段。')}</p>;
  return (
    <section className="clip-handoff" aria-label={t('镜头衔接质检')}>
      <ul>
        {into && <Cut title={t('接上一镜')} pair={into} />}
        {out && <Cut title={t('接下一镜')} pair={out} />}
      </ul>
      <p className="clip-handoff__note">{t('按片子画面量的方向、落幅和出入画，只作提示；本集：{0}', [report.summary])}</p>
    </section>
  );
}
