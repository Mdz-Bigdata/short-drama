/**
 * The one sentence the director page leads with: the plan's own theme, in Chinese.
 *
 * The plan opens with bookkeeping — a title, an "Artifact 交付" line listing deliverables by their
 * internal ids, tables of inputs — so "the first long line" picked that list, and stripping
 * Markdown emphasis also ate the underscores of `director_constitution`. The theme is what a
 * director's note should say; failing that, the first sentence of real Chinese prose.
 */

const FALLBACK = '以人物欲望为引擎，用镜头完成情绪递进，让每一次反转都在观众预期之前发生。';
const MAX_LENGTH = 156;

/** Every agent's deliverables by the names a reader knows them by (mirrors ARTIFACT_LABELS in agent_council.py). */
export const DELIVERABLE_LABELS: Record<string, string> = {
  director_constitution: '导演宪法', genre_audience_strategy: '题材与受众策略', series_narrative_arc: '全季叙事弧线',
  highlight_map: '高光地图', production_risk_register: '制作风险登记', director_approval: '导演审批',
  series_bible: '剧集圣经', episode_scripts: '分集剧本', character_arcs: '人物弧光', dialogue_sheet: '台词表',
  foreshadow_ledger: '伏笔账本', writer_compliance_pass: '编剧合规自检', character_bible: '角色圣经',
  five_view_turnarounds: '五视图设定', character_state_cards: '角色状态卡', costume_makeup_ledger: '服化账本',
  prop_ownership: '道具归属', voice_identity_brief: '声音身份说明', scene_bibles: '场景圣经',
  exact_nine_grid_storyboards: '九宫格分镜', shot_motion_contracts: '镜头运镜契约', continuity_ledger: '连续性账本',
  action_choreography: '动作设计', storyboard_qc: '分镜质检', visual_bible: '视觉圣经',
  style_palette_lighting_lock: '风格色板与布光锁定', negative_prompt_plan: '负面提示词方案', reference_binding_plan: '参考图绑定方案',
  generated_keyframes: '关键帧', video_route_plans: '视频路由方案', visual_qc: '视觉质检', voice_cards: '声卡',
  dialogue_timing: '台词时间轴', elevenlabs_job_plan: '配音任务计划', sfx_foley_cues: '音效与拟音提示', bgm_music_plan: '配乐方案',
  lipsync_plan: '口型同步方案', audio_mix_plan: '混音方案', audio_qc: '音频质检', edit_decision_list: '剪辑决策表',
  transition_plan: '转场方案', subtitle_package: '字幕包', mastered_timeline: '母版时间线', export_profiles: '导出规格',
  delivery_archive: '交付归档', final_qc: '成片终检', highlight_clips: '高光切片', cover_title_variants: '封面与标题备选',
  trailer_plan: '预告方案', platform_copy_tags: '平台文案与标签', ab_test_plan: 'A/B 测试方案', localization_package: '本地化素材包',
  rights_ai_disclosure: '版权与 AI 标识', campaign_kpis: '投放指标',
};

// English the planning model tends to mix in, and the Chinese a reader expects. Units and model terms
// (fps, mm, dB, LUT, AI) stay: they read the same in a Chinese crew's notes.
const PLAN_TERMS: Array<[RegExp, string]> = [
  [/\bArtifact\s*交付/g, '交付物'], [/\bArtifacts?\b/g, '交付物'],
  [/\bBLOCKED\b/g, '待补'], [/\bTBD\b/g, '待定'],
  [/\bPattern Interrupt\b/gi, '打破惯性'], [/\bCuriosity Gap\b/gi, '好奇缺口'],
  [/\bHooks?\b/g, '钩子'], [/\bWant\b/g, '外在目标'], [/\bNeed\b/g, '内在需求'],
  [/\bBGM\b/g, '背景音乐'], [/\bplatform\s*=\s*douyin\b/gi, '平台=抖音'], [/\bplatform\s*=\s*kuaishou\b/gi, '平台=快手'],
  [/\bplatform\s*=/gi, '平台='], [/\blanguage\s*=\s*zh-CN\b/gi, '语言=简体中文'], [/\blanguage\s*=/gi, '语言='],
  [/\bform\s*=\s*live_action\b/gi, '形式=真人实拍'], [/\bform\s*=\s*animation\b/gi, '形式=动画'], [/\bform\s*=/gi, '形式='],
];

/** A whole plan in the words a Chinese reader expects: deliverables, episodes and common terms translated. */
export function localizePlan(text: string): string {
  let result = text.replace(/`?\b([a-z]+(?:_[a-z]+)+)\b`?/g, (whole, id: string) => DELIVERABLE_LABELS[id] ?? whole);
  // EP01 / EP 12 / EP01-EP10 → 第1集 / 第12集 / 第1集-第10集
  result = result.replace(/\bEP\s*0*(\d{1,3})\b/g, (_whole, number: string) => `第${Number(number)}集`);
  for (const [pattern, replacement] of PLAN_TERMS) result = result.replace(pattern, replacement);
  return result;
}

// Labels a plan uses for its theme, most specific first.
const THEME_LABELS = ['一句话主题', '核心主题', '主题', '主旋律', '核心命题', '一句话卖点', 'Logline', 'logline'];

/** Replace known deliverable ids with their Chinese names; drop any other `snake_case` id left over. */
export function localizeIds(text: string): string {
  return text
    .replace(/`?([a-z]+(?:_[a-z]+)+)`?/g, (_whole, id: string) => DELIVERABLE_LABELS[id] ?? '')
    .replace(/\s*[（(]\s*[）)]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function plain(text: string): string {
  return localizeIds(text)
    .replace(/^\s*(?:#{1,6}|>|[-*•]+|\d+[.)、])\s*/, '')
    .replace(/\*\*|__|[*`【】]/g, '')
    .replace(/^["“「]|["”」]$/g, '')
    .trim();
}

function chineseShare(text: string): number {
  const letters = text.replace(/[\s\d\p{P}\p{S}]/gu, '');
  if (!letters) return 0;
  const han = letters.match(/\p{Script=Han}/gu)?.length ?? 0;
  return han / letters.length;
}

function clip(text: string): string {
  return text.length > MAX_LENGTH ? `${text.slice(0, MAX_LENGTH)}…` : text;
}

function themed(lines: string[]): string | null {
  for (const label of THEME_LABELS) {
    for (const line of lines) {
      // A table row: | **主题** | 假身份压不住真担当…… | 硬性要求 |
      if (line.trim().startsWith('|')) {
        const cells = line.split('|').map(cell => plain(cell)).filter(Boolean);
        if (cells.length >= 2 && cells[0].replace(/[:：]$/, '') === label && chineseShare(cells[1]) >= 0.5) return cells[1];
        continue;
      }
      // A labelled line: **主旋律 = 冒名者的每一次“装”，都被逼成真的。** / 主题：……
      const match = plain(line).match(new RegExp(`^${label}\\s*[=:：]\\s*(.+)$`));
      if (match && chineseShare(match[1]) >= 0.5) return match[1].trim();
    }
  }
  return null;
}

function firstProse(lines: string[]): string | null {
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || /^(#|\||---|```|>)/.test(trimmed) || /^\**\s*artifact/i.test(trimmed)) continue;
    const text = plain(trimmed);
    if (text.length < 16 || /^(总导演|策划方案|项目名称|类型|主题|交付)[:：]/.test(text)) continue;
    if (chineseShare(text) >= 0.6) return text;
  }
  return null;
}

export function findBrief(source: string): string {
  const lines = source.split('\n');
  const found = themed(lines) ?? firstProse(lines);
  return found ? clip(found) : FALLBACK;
}
