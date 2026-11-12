import { t } from '../../i18n';
import './DeliveryChecklist.css';

/** 成片交付前验收的一条：哪一镜、哪一条规则、为什么（后端 delivery_check）。 */
export interface AcceptanceIssue {
  shot_uid: number | null;
  scene_id: string;
  shot_id: number | null;
  rule: string;
  detail: string;
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
};

/** 合成前把要进成片的镜头过一遍：只提示，不拦合成。 */
export function DeliveryChecklist({ issues }: { issues: AcceptanceIssue[] }) {
  return (
    <section className="delivery-check" aria-label={t('成片交付前验收')}>
      <h4>{t('交付前验收')}</h4>
      {issues.length === 0 ? (
        <p className="delivery-check__ok" role="status">{t('按现在的剪辑过了一遍，没发现要改的镜头。')}</p>
      ) : (
        <ul>
          {issues.map((issue, index) => (
            <li key={`${issue.rule}-${issue.shot_uid ?? 'all'}-${index}`}>
              <strong>{issue.scene_id ? `${issue.scene_id} ${t('第')}${issue.shot_id}${t('镜')}` : t('整条成片')}</strong>
              <span className="delivery-check__rule">{t(RULE_LABELS[issue.rule] ?? issue.rule)}</span>
              <span>{issue.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
