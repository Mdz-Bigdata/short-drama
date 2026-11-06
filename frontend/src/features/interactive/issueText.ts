import { t } from '../../i18n';
import type { StoryIssue } from './storyTypes';

/** The backend names problems by code so they read in the interface's language; its own message is the fallback. */
export function issueText(issue: StoryIssue): string {
  const params = issue.params ?? {};
  switch (issue.code) {
    case 'empty_story': return t('故事里还没有片段');
    case 'missing_start': return t('没有指定存在的开场片段');
    case 'no_ending': return t('故事里还没有结局');
    case 'no_reachable_ending': return t('从开场走不到任何结局');
    case 'unknown_variable': return t('「{segment}」用了不存在的变量 {variable}', params);
    case 'condition_type_mismatch': return t('「{segment}」的条件与变量 {variable} 的类型不符', params);
    case 'effect_type_mismatch': return t('「{segment}」对变量 {variable} 的效果类型不对', params);
    case 'ending_has_exits': return t('结局「{segment}」还连着出口，播放到结局时会被忽略', params);
    case 'dead_end': return t('「{segment}」没有任何出口，也不是结局', params);
    case 'choice_unconnected': return t('「{segment}」的选项「{text}」还没有连到任何片段', params);
    case 'choice_target_missing': return t('「{segment}」的选项「{text}」指向不存在的片段 {target}', params);
    case 'choice_text_empty': return t('「{segment}」有一个选项没有文字', params);
    case 'route_target_missing': return t('「{segment}」的自动路由没有连到存在的片段', params);
    case 'shadowed_edges': return t('「{segment}」有无条件路由，排在它后面的 {count} 个出口永远用不上', params);
    case 'timer_without_choices': return t('「{segment}」设了限时但没有选项', params);
    case 'timer_default_missing': return t('「{segment}」的限时没有默认选项', params);
    case 'timer_default_gated': return t('「{segment}」的限时默认选项带条件；不满足时会改走第一个可选项', params);
    case 'unreachable_segment':
      return params.reason === 'conditions'
        ? t('「{segment}」到不了：它的入口条件永远满足不了', params)
        : t('「{segment}」到不了：没有路径从开场走到这里', params);
    case 'impossible_condition': return t('「{segment}」的「{text}」条件永远不会成立', params);
    case 'cycle_no_exit': return t('这些片段绕成一个圈且没有出口：{segments}', params);
    case 'cannot_reach_ending': return t('从「{segment}」出发走不到任何结局', params);
    case 'stuck_state': return t('有的走法到了「{segment}」时所有选项都上了锁，只能停在那里', params);
    default: return issue.message;
  }
}
