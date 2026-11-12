import { useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import './DeliveryChecklist.css';

/** 成片交付前验收的一条：哪一镜、哪一条规则、为什么（后端 delivery_check）。 */
export interface AcceptanceIssue {
  shot_uid: number | null;
  scene_id: string;
  shot_id: number | null;
  rule: string;
  detail: string;
  /** 七层之一：内容 / 连续性 / 表演 / 阅读 / 技术 / 包装 / 授权。旧数据没有。 */
  layer?: string;
  /** must 必须修复 / suggest 建议优化 / manual 需人工确认。 */
  tier?: 'must' | 'suggest' | 'manual' | 'info';
  tier_label?: string;
  /** 授权层的一条：哪样素材（记授权说明时用）。 */
  rights_key?: string;
}

const RULE_LABELS: Record<string, string> = {
  too_short: '镜头太短',
  dialogue: '台词放不下',
  same_size: '景别没变化',
  light_flip: '光向换边',
  few_sizes: '景别太少',
  tone_flip: '色温跳变',
  prop_jump: '道具穿帮',
  posture_jump: '姿态跳变',
  gaze_mismatch: '视线没对上',
  dub_over_face: '配音盖了原口型',
  rights: '授权待确认',
};

/** 授权层的一条：记下这样素材的来源和授权范围，存好后这一条就不再列出。 */
function RightsNote<D>({ taskId, rightsKey, onTimeline }: { taskId: string; rightsKey: string; onTimeline: (data: D) => void }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      onTimeline(await apiRequest<D>(`/api/drama/${encodeURIComponent(taskId)}/rights/note`, {
        method: 'PUT', body: JSON.stringify({ key: rightsKey, note }),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('授权说明保存失败'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="delivery-check__rights">
      <input type="text" maxLength={300} value={note} disabled={busy} placeholder={t('来源与授权范围，如：已购商用授权，合同在共享盘')}
        aria-label={t('授权说明')} onChange={event => setNote(event.target.value)} />
      <button type="button" className="secondary-action" disabled={busy || !note.trim()} onClick={() => { void save(); }}>{t('记下')}</button>
      {error && <span role="alert">{error}</span>}
    </span>
  );
}

/**
 * 合成前把要进成片的镜头过一遍：只提示，不拦合成。按层分组，每条标上必须修复 / 建议优化 / 需人工确认；
 * 机器没查的层单独列成「未验证」——空的问题清单不等于全部通过。
 */
export function DeliveryChecklist<D = unknown>({ issues, taskId, onTimeline }: {
  issues: AcceptanceIssue[];
  /** 给了就能在授权层直接记授权说明；存好后用返回的剪辑台数据刷新。 */
  taskId?: string;
  onTimeline?: (data: D) => void;
}) {
  const problems = issues.filter(issue => issue.rule !== 'unverified' && issue.rule !== 'unit_cost');
  const unverified = issues.filter(issue => issue.rule === 'unverified');
  // 可用镜头单价：这一轮的账，放在最后一行。
  const unitCost = issues.find(issue => issue.rule === 'unit_cost');
  const layers = [...new Set(problems.map(issue => issue.layer ?? ''))];
  return (
    <section className="delivery-check" aria-label={t('成片交付前验收')}>
      <h4>{t('交付前验收')}</h4>
      {problems.length === 0 ? (
        <p className="delivery-check__ok" role="status">
          {unverified.length ? t('镜头层面没发现问题；下面几层机器没查，需要人看过才算通过。') : t('按现在的剪辑过了一遍，没发现要改的镜头。')}
        </p>
      ) : layers.map(layer => (
        <div className="delivery-check__layer" key={layer || 'other'}>
          {layer && <h5>{t(layer)}</h5>}
          <ul>
            {problems.filter(issue => (issue.layer ?? '') === layer).map((issue, index) => (
              <li key={`${issue.rule}-${issue.shot_uid ?? 'all'}-${index}`}>
                {issue.tier_label && <span className={`delivery-check__tier delivery-check__tier--${issue.tier ?? 'manual'}`}>{t(issue.tier_label)}</span>}
                <strong>{issue.scene_id ? `${issue.scene_id} ${t('第')}${issue.shot_id}${t('镜')}` : t('整条成片')}</strong>
                <span className="delivery-check__rule">{t(RULE_LABELS[issue.rule] ?? issue.rule)}</span>
                <span>{issue.detail}</span>
                {issue.rights_key && taskId && onTimeline && <RightsNote<D> taskId={taskId} rightsKey={issue.rights_key} onTimeline={onTimeline} />}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {unverified.length > 0 && (
        <div className="delivery-check__unverified">
          <h5>{t('未验证（需人工确认）')}</h5>
          <ul>
            {unverified.map(item => (
              <li key={`unverified-${item.layer}`}>
                <strong>{t(item.layer ?? '')}</strong>
                <span>{item.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {unitCost && <p className="delivery-check__cost">{unitCost.detail}</p>}
    </section>
  );
}
