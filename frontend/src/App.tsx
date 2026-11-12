import { useState, useEffect, useMemo, useRef, useCallback, lazy, Suspense, type CSSProperties } from 'react';
import { 
  Film, Play, Pause, ChevronRight, Network, GitBranch, BrainCircuit, ListChecks, 
  HardDrive, Cpu, Monitor, Sliders,
  X, ArrowUp, Folder, ArrowRight, User,
  Upload, Bot, BookOpen, Plus, Zap, Clapperboard
} from 'lucide-react';
import { CONTENT_LANGUAGE_OPTIONS, CREATION_MODE_OPTIONS, EMPTY_AD_BRIEF, NARRATION_DELIVERY_OPTIONS, normalizeVideoReferenceMode, type AdBrief, type ContentLanguage, type CreationMode, type NarrationDelivery, type TaskConfig, type TaskResponse, type TaskSummary, type StageProgress } from './types';
import { CapabilityCenter } from './features/platform/CapabilityCenter';
import { PoetrySourcePicker } from './features/writer/PoetrySourcePicker';
import { tabOfKind, type ElementKind } from './features/elements/elementTypes';
import { NotificationBell } from './features/account/NotificationBell';
import { hasPermission } from './features/account/permissions';
import { FINANCE_PERMISSIONS } from './features/finance/financeFormat';
import type { ModelCategory } from './features/models/ModelConfigurationCenter';
import type { BreakdownSceneRef, SceneBoardStatus, StoryboardProgress, StoryboardShot } from './features/storyboard/StoryboardWorkspace';
import { storyboardActionFrom, type StoryboardViewAction } from './features/storyboard/storyboardActions';
import { chatCardsFrom, type ChatCard } from './features/workbench/chatCards';
import { ChatCardView } from './features/workbench/ChatCardView';
import { downloadStoryboardScene } from './features/storyboard/storyboardDownload';
import { AgentStageTabs } from './features/workbench/AgentStageTabs';
import { getScriptDisplayName } from './features/workbench/scriptTitle';
import { VideoReferenceModeSelect } from './features/workbench/VideoReferenceModeSelect';
import { NOVARA_AGENT_NAME, PRODUCT_TITLE } from './features/workbench/agentBrand';
import {
  DEFAULT_DIRECTOR_STYLE, DEFAULT_SHOT_STYLE, DIRECTOR_STYLES, FALLBACK_STYLE_PACK, FALLBACK_STYLE_PACKS,
  SHOT_STYLES, parseStylePacks, type StylePackOption,
} from './features/workbench/creationOptions';
import { WorkbenchResizeHandle } from './features/workbench/WorkbenchResizeHandle';
import { SLOW_CALL_MS, callElapsed, formatDuration, liveElapsed } from './features/workbench/stageProgress';
import { appendWorkflowHint, canAcceptTaskResponse, mergeWorkflowHistory, restoreWorkflowHistory, shouldPollWorkflow, workflowBoardTransition, workflowIntroMessage, type WorkflowChatMessage } from './features/workbench/workflowMessages';
import { WorkflowActions } from './features/workbench/WorkflowGuide';
import { ChatComposer } from './features/workbench/ChatComposer';
import { ChatHistory } from './features/workbench/ChatHistory';
import type { WriterDashboardResponse } from './features/writer/types';

// Every screen below sits behind navigation (a portal, a workbench stage or a
// modal), so it is loaded on demand instead of shipping in the first bundle.
const ElementLibraryPage = lazy(() => import('./features/elements/ElementLibraryPage').then(m => ({ default: m.ElementLibraryPage })));
const UserCenterPage = lazy(() => import('./features/account/UserCenterPage').then(m => ({ default: m.UserCenterPage })));
const FinanceConsolePage = lazy(() => import('./features/finance/FinanceConsolePage').then(m => ({ default: m.FinanceConsolePage })));
const BillingCenterPage = lazy(() => import('./features/billing/BillingCenterPage').then(m => ({ default: m.BillingCenterPage })));
const ModelConfigurationCenter = lazy(() => import('./features/models/ModelConfigurationCenter').then(m => ({ default: m.ModelConfigurationCenter })));
const ProjectSkillManager = lazy(() => import('./features/skills/ProjectSkillManager').then(m => ({ default: m.ProjectSkillManager })));
const StoryboardWorkspace = lazy(() => import('./features/storyboard/StoryboardWorkspace').then(m => ({ default: m.StoryboardWorkspace })));
const DirectorPlanningPage = lazy(() => import('./features/director/DirectorPlanningPage').then(m => ({ default: m.DirectorPlanningPage })));
const WriterAgentPageContainer = lazy(() => import('./features/writer/WriterAgentPageContainer').then(m => ({ default: m.WriterAgentPageContainer })));
const CharacterDesignerPageContainer = lazy(() => import('./features/character/CharacterDesignerPageContainer').then(m => ({ default: m.CharacterDesignerPageContainer })));
// 第 1、5、7 阶段的面板只在那几步出现，登录页与项目大厅不为它们付下载。
const StyleReferencePanel = lazy(() => import('./features/workbench/StyleReferencePanel').then(m => ({ default: m.StyleReferencePanel })));
const StageFivePreview = lazy(() => import('./features/workbench/StageFivePreview').then(m => ({ default: m.StageFivePreview })));
// 剪辑合成师：第 6、7 步(声音与成片)合成一页。
import { DISPLAY_STEPS, displayStep, isEditorStage, nextStageTab, previousStageTab, sameStageTab, stageLog } from './features/postproduction/editorStage';
import { filmsNeedingVoiceRender } from './features/postproduction/postProduction';
const PostProductionStudio = lazy(() => import('./features/postproduction/PostProductionStudio').then(m => ({ default: m.PostProductionStudio })));
const PublishPanel = lazy(() => import('./features/workbench/PublishPanel').then(m => ({ default: m.PublishPanel })));
const AcquisitionPanel = lazy(() => import('./features/workbench/AcquisitionPanel').then(m => ({ default: m.AcquisitionPanel })));
// 画布、互动剧与任务中心盖在工作台之上，只有打开时才下载。
const CanvasWorkspace = lazy(() => import('./features/canvas/CanvasWorkspace').then(m => ({ default: m.CanvasWorkspace })));
const InteractiveStoryWorkspace = lazy(() => import('./features/interactive/InteractiveStoryWorkspace').then(m => ({ default: m.InteractiveStoryWorkspace })));
const TaskCenter = lazy(() => import('./features/tasks/TaskCenter').then(m => ({ default: m.TaskCenter })));
const ProjectMemory = lazy(() => import('./features/memory/ProjectMemory').then(m => ({ default: m.ProjectMemory })));

function StageFallback() {
  return <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', padding: '40px' }}>{tr('正在载入…')}</div>;
}
import { API_BASE, apiRequest, notifyBillingRequired, onUnauthorized } from './api/client';
import { DEFAULT_CLIENT_CONFIG, parseClientConfig, type ClientConfig } from './api/clientConfig';
import { acceptLanguage, t as tr, useLocale } from './i18n';
import { LanguageSwitcher } from './i18n/LanguageSwitcher';
import { MarkdownDocument } from './features/writer/MarkdownDocument';
import { loadWebFonts } from './webFonts';

loadWebFonts();

type ChatMessage = WorkflowChatMessage;

interface CurrentUser {
  user_id: string;
  username: string;
  email?: string | null;
  phone?: string | null;
  role?: 'admin' | 'user';
  roles?: string[];
  permissions?: string[];
  status?: 'active' | 'suspended' | 'deleted';
  must_change_password?: boolean;
}

interface EpisodeItem {
  index: number;
  title: string;
  status: 'idle' | 'running' | 'completed' | 'failed';
  videoUrl?: string | null;
}

interface EpisodeCollectionState {
  taskId: string;
  sourceHash: string;
  items: EpisodeItem[];
}

// 轮询节奏（毫秒）：当前任务状态、制作中的分集列表、刚提交制作后的首次回查
const TASK_STATUS_POLL_MS = 1500;
// A dev-server reload or backend restart drops requests for ~20s. Keep polling
// through that window so the chat picks up the interrupted stage afterwards.
const TASK_STATUS_MAX_POLL_FAILURES = 40;
// 项目大厅列表：有项目在跑时跟随任务轮询节奏，否则慢速刷新
const LOBBY_IDLE_POLL_MS = 15000;
const EPISODE_LIST_POLL_MS = 8000;
const EPISODE_PRODUCE_RECHECK_MS = 5000;

// 下拉常用档位：小体量逐集递增，长剧按 10 集一档；实际可选范围由服务端下发的集数上下限裁剪
const EPISODE_COUNT_PRESETS = [
  1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150,
];
// 工作流内部共 8 个阶段(重跑命令按它校验)；给人看的是 7 步，第 6、7 阶段合成「剪辑合成师」一步。
const WORKFLOW_STAGE_COUNT = 8;

type EpisodeLimits = ClientConfig['episodeCount'];

function clampEpisodeCount(value: string | number, limits: EpisodeLimits) {
  const parsed = typeof value === 'number' ? value : parseInt(value, 10);
  if (!Number.isFinite(parsed)) return limits.min;
  return Math.min(limits.max, Math.max(limits.min, Math.trunc(parsed)));
}

function normalizeEpisodeSourceHash(value: unknown) {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return /^[a-f\d]{64}$/.test(normalized) ? normalized : '';
}

function stageKeyAtLeast(value: string, minimum: number) {
  const match = value.match(/^([0-9]+)(?:$|_)/);
  return Boolean(match && Number(match[1]) >= minimum && Number(match[1]) <= WORKFLOW_STAGE_COUNT);
}

function applyWriterDashboardToTask(
  task: TaskResponse,
  dashboard: WriterDashboardResponse,
): TaskResponse {
  const assets = Object.fromEntries(Object.entries(task.assets).filter(([key]) => (
    !stageKeyAtLeast(key, 3) && key !== '2_breakdown' && key !== '2_writer_dashboard'
  )));
  assets['2'] = dashboard.script;
  assets['2_writer_dashboard'] = dashboard;
  const logs = Object.fromEntries(Object.entries(task.logs).filter(([key]) => !stageKeyAtLeast(key, 2)));
  return {
    ...task,
    currentStage: 2,
    stageName: '编剧剧本创作',
    status: 'idle',
    config: {
      ...task.config,
      scriptContent: dashboard.script,
      scriptName: dashboard.scriptFileName || task.config.scriptName,
      episodeCount: dashboard.stats.totalEpisodes,
    },
    assets,
    logs,
    videoUrl: undefined,
    shortLink: undefined,
    prContent: undefined,
    stageProgress: null,
    failReason: null,
    workflow: undefined,
  };
}

interface ImportedSkill {
  name: string;
  description?: string;
  type?: string;
  path?: string;
  source?: string;
}

interface RecommendedTemplate {
  id: string;
  title: string;
  desc: string;
  prompt: string;
}

// 阶段3角色 DNA 锁定包结构化产物 (assets["3_dna"])：项目基准 + 假设 + 风险 + 角色档案/状态卡/视图锚点
// Ticks once a second while a stage runs, so its clocks move during a long model call.
function useNowWhile(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function StageProgressPanel({ progress, onOpenBilling }: { progress: StageProgress; onOpenBilling?: () => void }) {
  const now = useNowWhile(progress.status === 'running');
  const totalMs = liveElapsed(progress, now);
  const label = progress.stage_label || progress.stageLabel || tr('阶段{0}', [progress.stage]);
  const pct = Math.max(0, Math.min(100, Math.round(progress.percent || 0)));
  const isError = progress.status === 'error';
  const accent = isError ? 'var(--danger)' : progress.status === 'success' ? 'var(--success)' : 'var(--accent)';
  const calls = Array.isArray(progress.calls) ? progress.calls : [];
  const shownCalls = calls.slice(-8);
  return (
    <div style={{ padding: '12px 14px', background: 'var(--surface)', border: `1px solid ${isError ? 'rgba(var(--danger-rgb), 0.45)' : 'rgba(var(--accent-rgb), 0.25)'}`, borderRadius: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--ink)' }}>
          ⚙️ Stage {progress.stage} · {label}
        </span>
        <span style={{ fontSize: '0.82rem', fontWeight: 700, color: accent, fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
      </div>
      <div style={{ height: '6px', background: 'rgba(var(--accent-rgb), 0.176)', borderRadius: '999px', overflow: 'hidden', margin: '8px 0 10px' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: '999px', background: `linear-gradient(90deg, var(--accent), ${isError ? 'var(--danger)' : 'var(--accent)'})`, boxShadow: `0 0 8px ${accent}`, transition: 'width 0.8s ease' }} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {calls.length > shownCalls.length && (
          <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)' }}>{tr('… 前 {0} 步已完成', [calls.length - shownCalls.length])}</div>
        )}
        {shownCalls.map((call, i) => (
          <div key={`${call.name}-${i}`} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '0.72rem', lineHeight: '1.5', color: call.status === 'running' ? 'var(--ink)' : call.status === 'error' ? 'var(--danger)' : 'var(--text-muted)' }}>
            <span style={{ flexShrink: 0 }}>{call.status === 'running' ? '⏳' : call.status === 'error' ? '❌' : '✅'}</span>
            <span>{call.name}</span>
            {callElapsed(call, now) !== null && (
              <span style={{ marginLeft: 'auto', color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                {call.status === 'running' ? `${tr('已等待')} ` : ''}{formatDuration(callElapsed(call, now) ?? 0)}
              </span>
            )}
          </div>
        ))}
        {shownCalls.some(call => call.status === 'running' && (callElapsed(call, now) ?? 0) > SLOW_CALL_MS) && (
          <div role="status" style={{ fontSize: '0.68rem', lineHeight: '1.5', color: 'var(--neon-amber)' }}>
            {tr('模型响应较慢，仍在等待；超过总时限会自动放弃本次调用并换用备用凭据或模型。')}
          </div>
        )}
      </div>
      {totalMs !== null && (
        <div style={{ marginTop: '8px', textAlign: 'right', color: 'var(--text-dim)', fontSize: '0.66rem', fontVariantNumeric: 'tabular-nums' }}>
          {tr('累计耗时 {0}', [formatDuration(totalMs)])}
        </div>
      )}
      {isError && progress.error && (
        <div style={{ marginTop: '8px', fontSize: '0.74rem', lineHeight: '1.6', color: 'var(--danger)', background: 'rgba(var(--danger-rgb), 0.08)', border: '1px solid rgba(var(--danger-rgb), 0.3)', borderRadius: '6px', padding: '8px 10px' }}>
          {progress.error}
          {onOpenBilling && /积分不足|升级套餐/.test(progress.error) && (
            <button type="button" className="billing-required__action" onClick={onOpenBilling}>{tr('去充值')}</button>
          )}
        </div>
      )}
    </div>
  );
}

// 身份视图角度标签：固定人物关键视觉信息 (正面 0° / 侧面 90° / 背面 180° / 正脸 0° / 3-4 侧脸 45°)
// 数字演员卡片式设定集查看器：一张大图 + 底部缩略图条，点击缩略图切换主图
type GlobalModelDefaults = Record<ModelCategory, string>;

const EMPTY_GLOBAL_MODEL_DEFAULTS: GlobalModelDefaults = {
  text: '', image: '', video: '', audio: '',
};

let messageSequence = 0;
const nextMessageId = () => `message-${++messageSequence}`;

/** 各集的标题（剧本规划）与成片状态（逐集归档），给第 5 阶段左栏的分集卡。 */
function episodeMetaOf(assets: Record<string, unknown>): Array<{ number: number; title?: string; filmDone?: boolean }> {
  const written = (assets['2_screenwriting'] as { episodes?: Record<string, { plan?: { title?: string } }> } | undefined)?.episodes ?? {};
  const cycle = (assets['episode_cycle'] as { episodes?: Record<string, { film?: { final_video_url?: string | null } }> } | undefined)?.episodes ?? {};
  const numbers = new Set([...Object.keys(written), ...Object.keys(cycle)].map(Number).filter(Number.isFinite));
  return [...numbers].sort((a, b) => a - b).map(number => ({
    number,
    title: (written[String(number)]?.plan?.title ?? '').replace(/^第\s*\d+\s*集\s*/, '').trim() || undefined,
    filmDone: Boolean(cycle[String(number)]?.film?.final_video_url),
  }));
}

/** 一条片段属于第几集：与服务端 episode_cycle.episode_of 同一规则，显式集号优先，否则看场号。 */
function episodeOfClip(clip: { episode?: unknown; scene_id?: unknown }): number {
  if (typeof clip.episode === 'number' && Number.isInteger(clip.episode) && clip.episode > 0) return clip.episode;
  const match = /E(\d{1,3})/i.exec(String(clip.scene_id ?? ''));
  return match ? Math.max(1, Math.min(200, Number(match[1]))) : 1;
}

/**
 * 重跑分镜前要不要先问一句、问什么；没有会丢的东西就返回 null。
 * 服务端会清掉后面阶段的产物，逐集制作时只清当前集的片段、音频与剪辑，别的集和各集成片都留着。
 */
function storyboardRerunWarning(assets: Record<string, unknown>): string | null {
  const holds = (pattern: RegExp) => Object.entries(assets).some(([key, value]) => Boolean(value) && pattern.test(key));
  const records = (assets['episode_cycle'] as { episodes?: Record<string, { audio?: unknown; timeline?: unknown; film?: { final_video_url?: string | null } }> } | undefined)?.episodes;
  const listed = ((assets['4_progress'] as StoryboardProgress | undefined)?.episodes ?? [])
    .map(episode => episode.number)
    .filter((number): number is number => Number.isInteger(number));
  const numbers = [...new Set(listed.length
    ? listed
    : Object.keys((assets['4_scene_boards'] as Record<string, unknown> | undefined) ?? {}).map(sceneId => episodeOfClip({ scene_id: sceneId })))]
    .sort((a, b) => a - b);
  if (!assets['episode_cycle'] || numbers.length < 2) {
    return holds(/^[5-8](?:$|_)/)
      ? tr('重跑分镜阶段只补画未完成或已退回的场次，已完成的分镜页会保留；但第 5 阶段及之后已生成的视频、音频与成片会被清除。继续吗？')
      : null;
  }
  // 当前集：第一个还没有成片的集。
  const current = numbers.find(number => !records?.[String(number)]?.film?.final_video_url);
  if (current !== undefined) {
    const clips = Array.isArray(assets['5']) ? assets['5'] as Array<{ episode?: unknown; scene_id?: unknown } | null> : [];
    const record = records?.[String(current)];
    const ownWork = Boolean(record?.audio) || Boolean(record?.timeline)
      || clips.some(clip => !(clip && clip.scene_id && episodeOfClip(clip) !== current));
    if (ownWork) return tr('重跑分镜阶段只补画未完成或已退回的场次，已完成的分镜页会保留；但第 {0} 集已生成的视频、音频与剪辑会被清除，其他各集的视频和成片都保留。继续吗？', [current]);
  }
  return holds(/^8(?:$|_)/)
    ? tr('重跑分镜阶段只补画未完成或已退回的场次，已完成的分镜页会保留；各集成片都保留，但已生成的宣发内容会被清除。继续吗？')
    : null;
}

/** 大厅卡片上的状态名与色调：失败、中断、停止各说各的，不都写成「已暂停」。 */
function projectStatusView(status: TaskSummary['status']): { label: string; tone: 'idle' | 'running' | 'completed' | 'review' | 'failed' } {
  switch (status) {
    case 'running': return { label: tr('运行中'), tone: 'running' };
    case 'completed': return { label: tr('已完成'), tone: 'completed' };
    case 'awaiting_quality_review': return { label: tr('待质检'), tone: 'review' };
    case 'quality_failed': return { label: tr('质检未过'), tone: 'failed' };
    case 'awaiting_council_review': return { label: tr('待评审'), tone: 'review' };
    case 'council_quality_failed': return { label: tr('评审未过'), tone: 'failed' };
    case 'failed': return { label: tr('生成失败'), tone: 'failed' };
    case 'interrupted': return { label: tr('已中断'), tone: 'failed' };
    case 'stopped': return { label: tr('已停止'), tone: 'idle' };
    default: return { label: tr('已暂停'), tone: 'idle' };
  }
}

export default function App() {
  // The whole shell re-renders when the interface language changes (src/i18n).
  useLocale();
  // 用户身份认证状态
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authChecked, setAuthChecked] = useState<boolean>(false);
  // 本地开发时后端引导创建的管理员登录名；生产环境或未启用引导时后端不下发
  const [bootstrapAdminLogin, setBootstrapAdminLogin] = useState<string | null>(null);
  // 与服务端共用的限制（密码长度、验证码、集数范围、剧本上传），随会话接口下发
  const [clientConfig, setClientConfig] = useState<ClientConfig>(DEFAULT_CLIENT_CONFIG);
  // 账户可用创作积分；未取到时不显示，不拿假数字占位
  const [walletPoints, setWalletPoints] = useState<string | null>(null);
  const [stylePacks, setStylePacks] = useState<readonly StylePackOption[]>(FALLBACK_STYLE_PACKS);
  const [showUserMenu, setShowUserMenu] = useState<boolean>(false);
  const [activePortal, setActivePortal] = useState<'home' | 'user' | 'billing' | 'finance' | ElementKind>('home');
  const [billingNotice, setBillingNotice] = useState('');
  // 换页就收起：提示说的是刚才那个操作。
  useEffect(() => {
    const handle = window.setTimeout(() => setBillingNotice(''), 0);
    return () => window.clearTimeout(handle);
  }, [activePortal]);
  useEffect(() => {
    const show = (event: Event) => setBillingNotice((event as CustomEvent<string>).detail);
    window.addEventListener('billing-required', show);
    return () => window.removeEventListener('billing-required', show);
  }, []);

  // 会话失效后统一回到登录态，避免工作台面板各自吞掉 401 空转重试。
  const resetToSignedOut = useCallback(() => {
    setCurrentUser(null);
    setWalletPoints(null);
    setHasEnabledGlobalModel(false);
    setGlobalModelDefaults(EMPTY_GLOBAL_MODEL_DEFAULTS);
    setAuthChecked(true);
  }, []);

  // 功能面板共用 api/client 的 apiRequest，它在 401 时广播到这里。
  useEffect(() => onUnauthorized(resetToSignedOut), [resetToSignedOut]);

  // 统一的网络请求拦截器，确保附带 HttpOnly Cookie 并在 401 时拦截至登录态
  const apiFetch = async (url: string, options: RequestInit = {}) => {
    options.credentials = 'include';
    options.headers = { 'Accept-Language': acceptLanguage(), ...(options.headers as Record<string, string> | undefined) };
    const response = await fetch(url, options);
    if (response.status === 401) {
      resetToSignedOut();
      throw new Error(tr('未登录或登录已过期'));
    }
    if (response.status === 402) {
      const body = await response.clone().json().catch(() => ({})) as { detail?: string };
      notifyBillingRequired(body.detail || tr('积分不足'));
    }
    return response;
  };

  // 登录/注册表单的状态管理
  const [authTab, setAuthTab] = useState<'login_pwd' | 'login_code' | 'register'>('login_pwd');
  const [authForm, setAuthForm] = useState({
    loginId: '',
    password: '',
    email: '',
    phone: '',
    code: ''
  });
  const [authError, setAuthError] = useState<string>('');
  const [authSuccess, setAuthSuccess] = useState<string>('');
  const [codeCountdown, setCodeCountdown] = useState<number>(0);
  const [mockVerificationCode, setMockVerificationCode] = useState<string>('');

  // 发送验证码并按服务端的冷却时间启动倒计时；生产环境永不回显验证码。
  const handleSendVerificationCode = async () => {
    const loginId = authForm.loginId.trim();
    if (!loginId) {
      setAuthError(tr('请输入邮箱或手机号'));
      return;
    }
    setAuthError('');
    setAuthSuccess('');
    
    try {
      const res = await fetch(`${API_BASE}/api/auth/send_code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login_id: loginId }),
        credentials: 'include'
      });
      
      if (res.ok) {
        const data = await res.json();
        const developmentCode = typeof data.development_code === 'string' ? data.development_code : '';
        setMockVerificationCode(developmentCode);
        setAuthSuccess(developmentCode
          ? tr('验证码发送成功（本地开发码：{0}）', [developmentCode])
          : tr('验证码发送成功，请查看短信或邮件。'));
        setCodeCountdown(typeof data.cooldown_seconds === 'number' && data.cooldown_seconds > 0
          ? Math.ceil(data.cooldown_seconds)
          : clientConfig.verificationCode.cooldownSeconds);
        const timer = setInterval(() => {
          setCodeCountdown(prev => {
            if (prev <= 1) {
              clearInterval(timer);
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      } else {
        const err = await res.json();
        setAuthError(err.detail || tr('验证码发送失败'));
      }
    } catch {
      setAuthError(tr('无法连接至后端，请先确保后端运行中。'));
    }
  };

  // 账号登录与注册表单提交
  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError('');
    setAuthSuccess('');
    
    try {
      if (authTab === 'login_pwd') {
        if (!authForm.loginId.trim() || !authForm.password.trim()) {
          setAuthError(tr('请输入账号和密码'));
          return;
        }
        const res = await fetch(`${API_BASE}/api/auth/login_password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ login_id: authForm.loginId, password: authForm.password }),
          credentials: 'include'
        });
        
        if (res.ok) {
          const data = await res.json();
          setCurrentUser(data.user);
          void refreshModelConfigurationStatus();
          void refreshAccountResources();
          if (data.user.must_change_password) setActivePortal('user');
          setAuthForm({ loginId: '', password: '', email: '', phone: '', code: '' });
          fetchHistoryTasks();
          fetchImportedSkills();
        } else {
          const err = await res.json();
          setAuthError(err.detail || tr('登录失败，账号或密码错误'));
        }
      } else if (authTab === 'login_code') {
        if (!authForm.loginId.trim() || !authForm.code.trim()) {
          setAuthError(tr('请输入手机/邮箱及验证码'));
          return;
        }
        const res = await fetch(`${API_BASE}/api/auth/login_code`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ login_id: authForm.loginId, code: authForm.code }),
          credentials: 'include'
        });
        
        if (res.ok) {
          const data = await res.json();
          setCurrentUser(data.user);
          void refreshModelConfigurationStatus();
          void refreshAccountResources();
          if (data.user.must_change_password) setActivePortal('user');
          setAuthForm({ loginId: '', password: '', email: '', phone: '', code: '' });
          setMockVerificationCode('');
          fetchHistoryTasks();
          fetchImportedSkills();
        } else {
          const err = await res.json();
          setAuthError(err.detail || tr('登录失败，验证码错误或已失效'));
        }
      } else if (authTab === 'register') {
        if (!authForm.email.trim() && !authForm.phone.trim()) {
          setAuthError(tr('邮箱与手机号至少需填写一项'));
          return;
        }
        if (!authForm.password || authForm.password.length < clientConfig.passwordMinLength) {
          setAuthError(tr('密码长度不能少于 {0} 位', [clientConfig.passwordMinLength]));
          return;
        }
        
        const res = await fetch(`${API_BASE}/api/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: authForm.email.trim() || null,
            phone: authForm.phone.trim() || null,
            password: authForm.password
          }),
          credentials: 'include'
        });
        
        if (res.ok) {
          setAuthSuccess(tr('恭喜您注册成功！已自动为您填入登录项，请输入密码进行登录。'));
          setAuthTab('login_pwd');
          setAuthForm(prev => ({
            ...prev,
            loginId: authForm.email.trim() || authForm.phone.trim() || ''
          }));
        } else {
          const err = await res.json();
          setAuthError(err.detail || tr('注册失败，手机号或邮箱可能已被占用'));
        }
      }
    } catch {
      setAuthError(tr('连接服务器失败，请确认后端已正常启动。'));
    }
  };

  // 登出系统并清理状态
  const handleLogout = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include'
      });
      if (res.ok) {
        setCurrentUser(null);
        setHasEnabledGlobalModel(false);
        setGlobalModelDefaults(EMPTY_GLOBAL_MODEL_DEFAULTS);
        setTaskId('');
        setTaskData(null);
        // 同一个标签页换人登录时，不让上一个账号的项目、对话和积分先闪出来。
        setHistoryTasks([]);
        setHistoryLoaded(false);
        setChatMessages([]);
        setLobbyIdea('');
        setChatInput('');
        setWalletPoints(null);
        setErrorMessage('');
        setShowUserMenu(false);
      } else {
        setShowUserMenu(false);
        setErrorMessage(tr('退出登录失败，请重试。'));
      }
    } catch (e) {
      console.error('退出登录失败', e);
      setShowUserMenu(false);
      setErrorMessage(tr('退出登录失败，请重试。'));
    }
  };

  // 配置状态
  const [config, setConfig] = useState<TaskConfig>({
    titleSuggestion: '',
    directorStyle: DEFAULT_DIRECTOR_STYLE,
    shotStyle: DEFAULT_SHOT_STYLE,
    llmModel: '',
    imageModel: '',
    videoModel: '',
    ttsModel: '',
    videoReferenceMode: 'auto',
    oneClick: false,
    episodeCount: DEFAULT_CLIENT_CONFIG.episodeCount.default
  });

  // 界面交互状态
  const [taskId, setTaskIdState] = useState<string>('');
  const selectedTaskIdRef = useRef('');
  const selectionVersionRef = useRef(0);
  const setTaskId = (id: string) => {
    ++selectionVersionRef.current;
    selectedTaskIdRef.current = id;
    setTaskIdState(id);
  };
  const [taskData, setTaskData] = useState<TaskResponse | null>(null);
  const scriptDisplayName = useMemo(() => getScriptDisplayName(
    taskData?.config,
    taskData?.assets["2"] ?? taskData?.config.scriptContent,
    // The compiled dashboard carries the analysed drama name, so the header shows
    // the screenplay's title instead of the chat prompt the project was created from.
    (taskData?.assets["2_writer_dashboard"] as { title?: string } | undefined)?.title,
  ), [taskData]);
  // The background screenplay's status: the writer board refetches when the episodes land.
  const scriptDetailStatus = String((taskData?.assets["2_detail"] as { status?: string } | undefined)?.status || '');
  // 创作看板与人物关系在编剧阶段中途就落到任务上(角色、关系先出，账本和剧本随后)：数目一变就重新拉看板。
  const castBreakdown = taskData?.assets["2_breakdown"] as { roles?: unknown[]; relationships?: unknown[] } | undefined;
  const castSignature = `${castBreakdown?.roles?.length || 0}/${castBreakdown?.relationships?.length || 0}`;
  const taskDataRef = useRef<TaskResponse | null>(null);
  const [uploadedScript, setUploadedScript] = useState<File | null>(null);
  const [scriptContent, setScriptContent] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeTabStage, setActiveTabStage] = useState<number>(1);
  // 助手在对话里要求打开的分镜视图(场景 + 视图)，交给分镜看板执行。
  const [storyboardViewAction, setStoryboardViewAction] = useState<StoryboardViewAction | null>(null);
  // 从编剧统计跳到角色 agent 时，预选中的资产 Tab（数字演员 / 拍摄场地）
  const [characterAssetKind, setCharacterAssetKind] = useState<ElementKind>('actor');
  // 侧栏卡片「打开角色页」要直接弹出那个角色的捏脸窗；角色页报回当前看着的是谁，告诉助手。
  const [sculptRequest, setSculptRequest] = useState<{ name: string; nonce: number } | null>(null);
  const [focusedCharacter, setFocusedCharacter] = useState<string | null>(null);
  const [cardBusy, setCardBusy] = useState(false);
  const [historyTasks, setHistoryTasks] = useState<TaskSummary[]>([]);
  // 项目列表读到过一次才算数：没读到之前不说「还没有项目」。
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [isPolling, setIsPolling] = useState<boolean>(false);
  // 阶段执行进度快照 (用于检测 running -> success/error 转变，驱动对话面板状态气泡)
  const progressRef = useRef<{ stage: number; status: string } | null>(null);
  const statusRequestRef = useRef(0);
  const appliedStatusRequestRef = useRef(0);
  const statusPollFailuresRef = useRef(0);
  // 上一次轮询应用到界面上的状态正文与对象：内容没变就不换对象，整个工作台不重渲染。
  const lastStatusRef = useRef<{ body: string; data: TaskResponse } | null>(null);
  const restoreChatRef = useRef<string | null>(null);
  const chatRequestRef = useRef<{ taskId: string } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>('');
  
  // 气泡控制
  const [activePopover, setActivePopover] = useState<'none' | 'skill' | 'element' | 'sidebarSkill' | 'poetry'>('none');
  const [showModelConfiguration, setShowModelConfiguration] = useState(false);
  const [projectOverlay, setProjectOverlay] = useState<'canvas' | 'interactive' | 'tasks' | 'memory' | null>(null);
  const [hasEnabledGlobalModel, setHasEnabledGlobalModel] = useState(false);
  const [globalModelDefaults, setGlobalModelDefaults] = useState<GlobalModelDefaults>(EMPTY_GLOBAL_MODEL_DEFAULTS);
  const [showProjectSkillManager, setShowProjectSkillManager] = useState(false);
  
  // 对话流状态
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState<string>('');
  const chatInputRef = useRef('');
  // 大厅的创意输入单独存：建好项目后不会原样躺进项目里的对话框，项目里没发完的话也不会跑回大厅。
  const [lobbyIdea, setLobbyIdea] = useState<string>('');
  const [chatSending, setChatSending] = useState(false);

  // 新项目创建模态窗及 Skills 区状态
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  useEffect(() => {
    if (!showCreateModal) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowCreateModal(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showCreateModal]);
  const [newProjectName, setNewProjectName] = useState<string>('');
  // 创建没成功的原因写在弹窗里：人还在弹窗里，填过的内容都在。
  const [createError, setCreateError] = useState<string>('');
  // 卡片操作失败的那句话。它显示在项目大厅里：人这时在看卡片，创意输入框上方那条在视线之外。
  const [cardActionError, setCardActionError] = useState<string>('');
  const [newProjectDirectorStyle, setNewProjectDirectorStyle] = useState<string>(DEFAULT_DIRECTOR_STYLE);
  const [newProjectStylePack, setNewProjectStylePack] = useState<string>(FALLBACK_STYLE_PACK);
  const [newProjectShotStyle, setNewProjectShotStyle] = useState<string>(DEFAULT_SHOT_STYLE);
  const [newProjectNarrationDelivery, setNewProjectNarrationDelivery] = useState<NarrationDelivery>('use_tts');
  const [newProjectCreationMode, setNewProjectCreationMode] = useState<CreationMode>('drama');
  const [newProjectAdBrief, setNewProjectAdBrief] = useState<AdBrief>(EMPTY_AD_BRIEF);
  const [newProjectContentLanguage, setNewProjectContentLanguage] = useState<ContentLanguage>('zh');
  const [newProjectOneClick, setNewProjectOneClick] = useState<boolean>(true); // 成片方式：true=一键成片 / false=分步引导
  const [newProjectEpisodes, setNewProjectEpisodes] = useState<number>(DEFAULT_CLIENT_CONFIG.episodeCount.default); // 一次性生成的剧本集数
  const [newProjectEpisodesCustom, setNewProjectEpisodesCustom] = useState<boolean>(false); // 集数改为手动填写
  const [episodeState, setEpisodeState] = useState<EpisodeCollectionState>({
    taskId: '',
    sourceHash: '',
    items: [],
  }); // 分集制作清单与其所属剧本版本
  const episodes = episodeState.taskId === taskId ? episodeState.items : [];
  const episodesSourceHash = episodeState.taskId === taskId ? episodeState.sourceHash : '';
  const [episodesBusy, setEpisodesBusy] = useState<boolean>(false);
  const [showSkillsGrid, setShowSkillsGrid] = useState<boolean>(true);

  // 导入 Skill 模态窗及输入状态
  const [showImportSkillModal, setShowImportSkillModal] = useState<boolean>(false);
  const [importSkillType, setImportSkillType] = useState<'github' | 'clawhub' | 'npx' | 'zip'>('github');
  const [importSkillUrl, setImportSkillUrl] = useState<string>('');
  const [importSkillPackage, setImportSkillPackage] = useState<string>('');
  const [importSkillFile, setImportSkillFile] = useState<File | null>(null);
  const [importedSkills, setImportedSkills] = useState<ImportedSkill[]>([]);
  const [recommendedTemplates, setRecommendedTemplates] = useState<RecommendedTemplate[]>([
    { id: '1', title: '⚔️ 国风新武侠决战', desc: '无极剑宗传人突围逆袭破强敌', prompt: '请帮我生成一个武侠决战短剧，走完整个流程。' },
    { id: '2', title: '🚗 智能车载科技爽剧', desc: '火山方舟大模型反击资本垄断', prompt: '请生成一个车载科技中控发布会短剧，走完流程。' },
    { id: '3', title: '🐺 欧美狼人出海短剧', desc: 'Rejected Mate & Silver Wolf Queen', prompt: '请帮我生成一个欧美狼人出海短剧，走完流程。' },
    { id: '4', title: '🏮 民俗恐怖纸人抬棺', desc: '扎纸铺深夜禁忌，纸人列队出巡', prompt: '请帮我生成一个民俗恐怖纸人抬棺短剧，走完流程。' },
    { id: '5', title: '⚡ 废柴弟子逆天成魔', desc: '清虚仙尊欲剥仙骨，魔皇血脉觉醒', prompt: '请帮我生成一个废柴弟子成魔修仙短剧，走完流程。' },
    { id: '6', title: '⚖️ 金牌律师正义反扑', desc: '行贿伪证当庭拆穿，豪门大少收押', prompt: '请帮我生成一个金牌律师庭审翻盘短剧，走完流程。' }
  ]);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const episodeRequestGenerationRef = useRef(0);
  const workbenchRef = useRef<HTMLDivElement | null>(null);
  const chatSidebarRef = useRef<HTMLDivElement | null>(null);
  const [chatSidebarWidth, setChatSidebarWidth] = useState<number | null>(null);

  // 登录后才有的账户数据：积分余额与可选的画面风格锁。任一项取不到都保持现状，不影响主流程。
  async function refreshAccountResources() {
    void apiRequest<{ points?: string | number }>('/api/billing/wallet')
      .then(wallet => setWalletPoints(wallet.points === undefined ? null : String(wallet.points)))
      .catch(() => undefined);
    void apiRequest<unknown>('/api/production/style-packs')
      .then(catalog => {
        const parsed = parseStylePacks(catalog);
        if (!parsed) return;
        setStylePacks(parsed.packs);
        setNewProjectStylePack(current => (parsed.packs.some(pack => pack.id === current) ? current : parsed.defaultId));
      })
      .catch(() => undefined);
  }

  async function refreshModelConfigurationStatus() {
    try {
      const response = await fetch(`${API_BASE}/api/model-configurations`, {
        method: 'GET', credentials: 'include'
      });
      if (!response.ok) return;
      const data = await response.json() as {
        summary?: Partial<Record<ModelCategory, number>>;
        global_status?: {
          configured: boolean;
          enabled_model_ids: Partial<Record<ModelCategory, string[]>>;
          default_model_ids: Partial<Record<ModelCategory, string | null>>;
        };
      };
      const configured = data.global_status?.configured ?? Object.values(data.summary ?? {}).some(count => (count ?? 0) > 0);
      const defaults = data.global_status?.default_model_ids;
      const nextDefaults: GlobalModelDefaults = {
        text: defaults?.text ?? '',
        image: defaults?.image ?? '',
        video: defaults?.video ?? '',
        audio: defaults?.audio ?? '',
      };
      const enabledModelIds = data.global_status?.enabled_model_ids;
      const selectGlobalModel = (current: string, category: ModelCategory) => {
        const enabled = enabledModelIds?.[category] ?? [];
        if (!current) return nextDefaults[category];
        return enabled.length > 0 && !enabled.includes(current) ? nextDefaults[category] : current;
      };
      setHasEnabledGlobalModel(configured);
      setGlobalModelDefaults(nextDefaults);
      setConfig(current => ({
        ...current,
        llmModel: selectGlobalModel(current.llmModel, 'text'),
        imageModel: selectGlobalModel(current.imageModel, 'image'),
        videoModel: selectGlobalModel(current.videoModel, 'video'),
        ttsModel: selectGlobalModel(current.ttsModel, 'audio'),
      }));
    } catch {
      // 保留当前状态，短暂网络故障不应把已配置误报为未配置。
    }
  }

  useEffect(() => {
    taskDataRef.current = taskData;
  }, [taskData]);

  useEffect(() => {
    chatInputRef.current = chatInput;
  }, [chatInput]);

  // 挂载时检查一次会话登录态，成功后再拉取任务和Skills。
  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/auth/session`, {
      method: 'GET', credentials: 'include'
    }).then(async res => {
      if (res.ok && active) {
        const data = await res.json();
        setBootstrapAdminLogin(typeof data.bootstrap_admin_login === 'string' ? data.bootstrap_admin_login : null);
        const nextClientConfig = parseClientConfig(data.client_config);
        setClientConfig(nextClientConfig);
        setNewProjectEpisodes(nextClientConfig.episodeCount.default);
        if (data.authenticated && data.user) {
          setCurrentUser(data.user);
          void refreshModelConfigurationStatus();
          void refreshAccountResources();
          if (data.user.must_change_password) setActivePortal('user');
          void fetchHistoryTasks();
          void fetchImportedSkills();
        }
      }
    }).catch(() => undefined).finally(() => {
      if (active) setAuthChecked(true);
    });
    return () => { active = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- one-time session bootstrap

  // 获取所有已导入的技能列表
  async function fetchImportedSkills() {
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/skills`);
      if (res.ok) {
        const data = await res.json();
        setImportedSkills(data);
      }
    } catch (e) {
      console.error('加载导入Skills失败', e);
    }
  }

  // 触发 E2E 技能导入 API
  const handleImportSkill = async () => {
    const formData = new FormData();
    formData.append('import_type', importSkillType);
    
    if (importSkillType === 'github' || importSkillType === 'clawhub') {
      if (!importSkillUrl.trim()) {
        alert(tr('请输入 Git 仓库或 Clawhub 的克隆 URL！'));
        return;
      }
      formData.append('url', importSkillUrl.trim());
    } else if (importSkillType === 'npx') {
      if (!importSkillPackage.trim()) {
        alert(tr('请输入 NPX 包名！'));
        return;
      }
      formData.append('package_name', importSkillPackage.trim());
    } else if (importSkillType === 'zip') {
      if (!importSkillFile) {
        alert(tr('请选择需要上传的本地 ZIP 技能压缩包！'));
        return;
      }
      formData.append('file', importSkillFile);
    }
    
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/import_skill`, {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        alert(tr('🎉 技能包导入成功: {0}', [data.skillName]));
        
        // 自动高亮并选中当前新导入的技能作为运镜模板名
        updateConfigAndSync({ shotStyle: data.skillName });
        
        // 刷新列表并关闭弹窗
        fetchImportedSkills();
        setShowImportSkillModal(false);
        setImportSkillUrl('');
        setImportSkillPackage('');
        setImportSkillFile(null);
      } else {
        const err = await res.json();
        alert(tr('导入失败: {0}', [err.detail || tr('接口解析错误')]));
      }
    } catch {
      alert(tr('无法连接至后端，请先确保后端启动运行中。'));
    }
  };

  // 物理删除指定已导入的 Skill 技能包
  const handleDeleteSkill = async (skillName: string) => {
    if (!window.confirm(tr('确定要物理删除技能包 "{0}" 吗？此操作不可逆！', [skillName]))) {
      return;
    }
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/skills/${skillName}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        alert(tr('技能包删除成功！'));
        fetchImportedSkills();
        if (config.shotStyle === skillName) {
          updateConfigAndSync({ shotStyle: DEFAULT_SHOT_STYLE });
        }
      } else {
        const err = await res.json();
        alert(tr('删除失败: {0}', [err.detail || tr('接口错误')]));
      }
    } catch {
      alert(tr('删除失败，无法连接至后端。'));
    }
  };

  // 物理删除指定任务记录
  const handleDeleteTask = async (targetTaskId: string) => {
    if (!window.confirm(tr("确定要物理删除该短剧生成项目吗？该操作不可逆且将清除所有已生成视频与音频资产！"))) {
      return;
    }
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${targetTaskId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        // 卡片从大厅消失就是反馈，不再弹框拦一下。
        setHistoryTasks(prev => prev.filter(task => task.taskId !== targetTaskId));
        fetchHistoryTasks();
        // 如果删除的是当前选中的项目，重置工作区状态
        if (taskId === targetTaskId) {
          setTaskId('');
          setTaskData(null);
          setChatMessages([]);
          setIsPolling(false);
        }
      } else {
        const err = await res.json();
        alert(tr('删除失败: {0}', [err.detail || tr('接口解析错误')]));
      }
    } catch {
      alert(tr('物理删除失败，无法连接至后端。'));
    }
  };

  // 处理手动剧本文件上传
  const handleScriptUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setErrorMessage('');
    if (file.size > clientConfig.scriptUpload.maxBytes) {
      // 超限文件不必先传完再被服务端拒绝
      setErrorMessage(tr('剧本文件不能超过 {0}MB', [Math.floor(clientConfig.scriptUpload.maxBytes / (1024 * 1024))]));
      e.target.value = '';
      return;
    }
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await apiFetch(`${API_BASE}/api/drama/parse_script`, {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        setUploadedScript(file);
        setScriptContent(data.content);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || tr('解析剧本文件失败，请确保格式正确。'));
      }
    } catch {
      setErrorMessage(tr('无法连接至后端解析剧本，请检查服务。'));
    }
  };




  // 轮询监控后台当前任务。后台标签页不轮询：任务列表响应可达 1 MB 以上，
  // 隐藏时轮询纯属浪费带宽与电量，重新可见时立即补一次。
  useEffect(() => {
    const shouldPoll = () => isPolling && taskId && !document.hidden;

    const start = () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (!shouldPoll()) return;
      pollIntervalRef.current = setInterval(() => { fetchTaskStatus(taskId); }, TASK_STATUS_POLL_MS);
    };
    const stop = () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
        return;
      }
      if (isPolling && taskId) fetchTaskStatus(taskId);
      start();
    };

    start();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      stop();
    };
  }, [isPolling, taskId]); // eslint-disable-line react-hooks/exhaustive-deps -- polling callback reads current refs

  // 登录后在大厅定时轮询拉取所有任务 (当不在工作台内时)
  // Derive a STABLE boolean: fetchHistoryTasks replaces historyTasks with a new
  // array every tick, so depending on the array itself would reset the timer on
  // every response.
  const hasRunningTask = historyTasks.some(task => task.status === 'running');
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    const stop = () => {
      if (interval) clearInterval(interval);
      interval = null;
    };
    const start = () => {
      stop();
      if (!currentUser || taskId || document.hidden) return;
      // The listing ships every task with all of its assets, so only poll fast
      // while something is actually progressing.
      interval = setInterval(() => { fetchHistoryTasks(); }, hasRunningTask ? TASK_STATUS_POLL_MS : LOBBY_IDLE_POLL_MS);
    };
    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
        return;
      }
      if (currentUser && !taskId) fetchHistoryTasks();
      start();
    };

    start();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      stop();
    };
  }, [currentUser, taskId, hasRunningTask]); // eslint-disable-line react-hooks/exhaustive-deps -- lobby refresh follows authentication, selected task and whether work is in flight

  // 拉取历史列表
  async function fetchHistoryTasks() {
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/list`);
      if (res.ok) {
        const data = await res.json();
        // A non-array body (error envelope, proxy page) must not crash the
        // whole workbench when the history list is rendered.
        setHistoryTasks(Array.isArray(data) ? data : []);
        setHistoryLoaded(true);
      }
    } catch (e) {
      console.error('加载历史任务失败', e);
    }
  }

  // 拉取单条任务状态并联动更新聊天气泡
  async function fetchTaskStatus(id: string) {
    const request = ++statusRequestRef.current;
    const selection = selectionVersionRef.current;
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${id}/status`);
      if (res.ok) {
        const data: TaskResponse = await res.json();
        if (request < appliedStatusRequestRef.current || selection !== selectionVersionRef.current || !canAcceptTaskResponse(selectedTaskIdRef.current, data.taskId)) return;
        appliedStatusRequestRef.current = request;
        statusPollFailuresRef.current = 0;
        // 运行中每 1.5 秒轮询一次，绝大多数回包和上一次一字不差：这时界面上的对象原样保留，
        // 不触发整个工作台重渲染。界面上若是本地刚改过的对象（不是上次回包），照常用回包覆盖。
        const body = JSON.stringify(data);
        const last = lastStatusRef.current;
        if (last && last.body === body && taskDataRef.current === last.data && restoreChatRef.current !== id) return;
        const previous = taskDataRef.current;
        const boardStage = workflowBoardTransition(previous, data);
        setTaskData(data);
        taskDataRef.current = data;
        lastStatusRef.current = { body, data };

        // 阶段开始执行时打开该阶段看板；阶段结束（完成、失败或中断）后停在这一步的
        // 看板等待审核，用户说「继续」后才进入下一步。执行过程中不打扰用户手动翻看。
        if (boardStage) {
          setActiveTabStage(boardStage);
        }

        // The server distinguishes a completed run from a completed stage (for
        // example, one finished episode is not the entire storyboard stage).
        const sp = data.stageProgress;
        const prevSp = progressRef.current;
        const restore = restoreChatRef.current === id;
        if (restore) restoreChatRef.current = null;
        const showHint = restore || data.workflow?.mode !== 'running' || !prevSp || sp?.stage !== prevSp.stage;
        setChatMessages(prev => {
          const restored = restore ? restoreWorkflowHistory(data) : null;
          // 打开一个还没有对话记录的项目（老项目、或刚创建就刷新）时，先交代
          // 八个 Agent 的整条流程和当前位置，用户不会从半路醒来。
          const intro = restored && !restored.length ? workflowIntroMessage(data) : null;
          const messages = restored ? (intro ? [intro] : restored) : mergeWorkflowHistory(prev, data);
          // Durable transitions include stages completed between two polls.
          // Do not repeat the same transition as a second live hint bubble.
          const receivedHistory = !restore && messages.length > prev.length;
          return showHint && !receivedHistory ? appendWorkflowHint(messages, data) : messages;
        });
        progressRef.current = sp ? { stage: sp.stage, status: sp.status } : null;
        setIsPolling(shouldPollWorkflow(data));
        if (!shouldPollWorkflow(data)) fetchHistoryTasks();
      }
    } catch (e) {
      if (request < appliedStatusRequestRef.current || selection !== selectionVersionRef.current || selectedTaskIdRef.current !== id) return;
      console.error('获取状态失败', e);
      // While polling, an unreachable backend is usually restarting: keep trying.
      statusPollFailuresRef.current += 1;
      if (pollIntervalRef.current && statusPollFailuresRef.current < TASK_STATUS_MAX_POLL_FAILURES) return;
      statusPollFailuresRef.current = 0;
      setIsPolling(false);
      setErrorMessage(tr('流程状态暂时同步失败。请发送「进度」重新查询；不会自动跳到下一阶段。'));
    }
  }

  async function startCreatedWorkflow(createdTask: TaskResponse, oneClick: boolean) {
    const selection = selectionVersionRef.current;
    const requestToken = { taskId: createdTask.taskId };
    chatRequestRef.current = requestToken;
    setChatSending(true);
    try {
      const response = await apiFetch(`${API_BASE}/api/drama/${createdTask.taskId}/assistant`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: oneClick ? '一键成片' : '继续' }),
      });
      const result = await response.json();
      if (chatRequestRef.current !== requestToken || selection !== selectionVersionRef.current || !canAcceptTaskResponse(selectedTaskIdRef.current, createdTask.taskId)) return;
      if (!response.ok) {
        setErrorMessage(result.detail || tr('项目已创建，但流程尚未启动。请发送「进度」查看。'));
        return;
      }
      const updated: TaskResponse = result.task;
      appliedStatusRequestRef.current = ++statusRequestRef.current;
      setTaskData(updated);
      taskDataRef.current = updated;
      progressRef.current = updated.stageProgress ? { stage: updated.stageProgress.stage, status: updated.stageProgress.status } : null;
      setIsPolling(shouldPollWorkflow(updated));
      setChatMessages(prev => updated.chatHistory?.length
        ? mergeWorkflowHistory(prev.filter(message => message.id !== '2'), updated)
        : [...prev.filter(message => message.id !== '2'), { id: nextMessageId(), sender: 'ai', text: result.reply }]);
    } finally {
      if (chatRequestRef.current === requestToken) {
        chatRequestRef.current = null;
        if (selection === selectionVersionRef.current) setChatSending(false);
      }
    }
  }

  // 初始化创建短剧任务
  const initDramaProject = async (text: string) => {
    let titleText = text.trim();
    if (!titleText) {
      if (uploadedScript) {
        const idx = uploadedScript.name.lastIndexOf('.');
        titleText = idx !== -1 ? uploadedScript.name.substring(0, idx) : uploadedScript.name;
      } else {
        return;
      }
    }
    
    setErrorMessage('');
    const currentConfig = { 
      ...config, 
      titleSuggestion: titleText,
      scriptContent: scriptContent || undefined,
      scriptName: uploadedScript ? uploadedScript.name : undefined
    };
    
    const displayMsg = uploadedScript 
      ? tr('📖 已手动载入剧本《{0}》生成短剧。', [uploadedScript.name]) + (text.trim() ? tr('\n附加要求：{0}', [text.trim()]) : '')
      : titleText;
      
    // 初始化聊天流
    setChatMessages([
      { id: '1', sender: 'user', text: displayMsg },
      { id: '2', sender: 'ai', text: tr('正在创建项目。创建后，我会从总导演开始，按顺序陪您完成八大 Agent 流程。') }
    ]);

    try {
      const res = await apiFetch(`${API_BASE}/api/drama/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskId(data.taskId);
        setTaskData(data);
        taskDataRef.current = data;
        setUploadedScript(null);
        setScriptContent('');
        setLobbyIdea('');
        setActiveTabStage(1);
        await startCreatedWorkflow(data, currentConfig.oneClick);
        fetchHistoryTasks();
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || tr('创建任务失败'));
      }
    } catch {
      setErrorMessage(tr('无法连接至后端，请先在终端运行 `./start.sh` 启动系统。'));
    }
  };

  // 步骤式单步生成
  const handleNextStage = async () => {
    if (!taskData?.workflow || taskData.workflow.next_stage === null || taskData.workflow.mode === 'running') return;
    await sendChatInstruction('继续');
  };

  // —— 分集制作 (item 6: 剧本一次多集，视频逐集制作) ——
  const fetchEpisodes = async (tid: string) => {
    const requestGeneration = episodeRequestGenerationRef.current;
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${tid}/episodes`);
      if (res.ok) {
        const data = await res.json();
        const eps = data.episodes || [];
        const sourceHash = normalizeEpisodeSourceHash(data.sourceHash);
        if (requestGeneration !== episodeRequestGenerationRef.current) return;
        setEpisodeState(current => current.taskId === tid
          ? { taskId: tid, sourceHash, items: eps }
          : current);
        // 有正在制作的集则继续轮询
        if (eps.some((episode: EpisodeItem) => episode.status === 'running')) {
          setTimeout(() => fetchEpisodes(tid), EPISODE_LIST_POLL_MS);
        }
      }
    } catch (e) { console.error(e); }
  };

  const handlePlanEpisodes = async () => {
    if (!taskId) return;
    setEpisodesBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${taskId}/episodes/plan`, { method: 'POST' });
      if (res.ok) {
        await fetchEpisodes(taskId);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || tr('分集失败 (请先完成阶段1-2剧本)'));
      }
    } catch {
      setErrorMessage(tr('分集请求失败'));
    } finally {
      setEpisodesBusy(false);
    }
  };

  const handleProduceEpisode = async (idx: number) => {
    if (!taskId) return;
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${taskId}/episodes/${idx}/produce`, { method: 'POST' });
      if (res.ok) {
        setEpisodeState(current => current.taskId === taskId
          ? {
            ...current,
            items: current.items.map(episode => episode.index === idx
              ? { ...episode, status: 'running' }
              : episode),
          }
          : current);
        setTimeout(() => fetchEpisodes(taskId), EPISODE_PRODUCE_RECHECK_MS);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || tr('第{0}集制作启动失败', [idx]));
      }
    } catch {
      setErrorMessage(tr('第{0}集制作请求失败', [idx]));
    }
  };

  const handleWriterScriptSaved = (dashboard: WriterDashboardResponse) => {
    if (taskDataRef.current?.taskId !== taskId) return;
    episodeRequestGenerationRef.current += 1;
    setEpisodeState({
      taskId,
      sourceHash: normalizeEpisodeSourceHash(dashboard.sourceHash),
      items: dashboard.episodes.map(episode => ({ ...episode })),
    });
    setTaskData(current => current && current.taskId === taskId
      ? applyWriterDashboardToTask(current, dashboard)
      : current);
    void fetchTaskStatus(taskId);
  };

  // 发送对话指引微调或生成
  // 告诉助手界面上现在打开的是什么：哪一步、哪一场、哪个角色。助手据此理解「这一场」「她」指谁。
  const assistantContext = () => {
    const context: Record<string, string | number> = { stage: activeTabStage };
    if (activeTabStage === 4 && storyboardViewAction?.sceneId) {
      context.scene_id = storyboardViewAction.sceneId;
      context.view = storyboardViewAction.view;
    }
    if (activeTabStage === 3 && focusedCharacter) context.character = focusedCharacter;
    return context;
  };

  const openCharacterFromCard = (name: string) => {
    setCharacterAssetKind('actor');
    setActiveTabStage(3);
    setSculptRequest({ name, nonce: Date.now() });
  };

  const openStageFromCard = (sceneId: string) => {
    setActiveTabStage(4);
    setStoryboardViewAction({ sceneId, view: 'desk', nonce: Date.now() });
  };

  // 卡片上的「撤销这一步」直接回到那一步之前，不经过模型、不花钱；撤完刷新项目。
  const undoFromCard = async (url: string, body: Record<string, unknown>, done: string) => {
    if (!taskId || cardBusy) return;
    const requestTaskId = taskId;
    setCardBusy(true);
    setErrorMessage('');
    try {
      const res = await apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (selectedTaskIdRef.current !== requestTaskId) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setErrorMessage((err as { detail?: string }).detail || tr('撤销失败'));
        return;
      }
      setChatMessages(prev => [...prev, { id: nextMessageId(), sender: 'ai', text: done }]);
      await fetchTaskStatus(requestTaskId);
    } catch {
      if (selectedTaskIdRef.current === requestTaskId) setErrorMessage(tr('撤销失败，请检查后端网络连接。'));
    } finally {
      setCardBusy(false);
    }
  };

  const undoStageFromCard = (sceneId: string, snapshotId: string) => void undoFromCard(
    `${API_BASE}/api/drama/${taskId}/director-desk/scenes/${encodeURIComponent(sceneId)}/director/restore`,
    { snapshot_id: snapshotId },
    tr('已撤销 {0} 的这一步舞台改动。', [sceneId]),
  );

  const undoFaceFromCard = (name: string, snapshotId: string) => void undoFromCard(
    `${API_BASE}/api/drama/${taskId}/characters/${encodeURIComponent(name)}/face-sculpt/revert`,
    { snapshot_id: snapshotId },
    tr('已撤销「{0}」的这一步捏脸。', [name]),
  );

  // 用户最后一句话之后的助手回复：只有它们带的提议还能确认，再早的已经被处理或作废了。
  const lastUserIndex = chatMessages.map(message => message.sender).lastIndexOf('user');
  const openReplyIds = new Set(chatMessages.slice(lastUserIndex + 1).filter(message => message.sender === 'ai').map(message => message.id));

  const sendChatInstruction = async (text: string) => {
    if (!text.trim() || text.trim() === '/' || !taskId || chatRequestRef.current?.taskId === taskId) return;
    const requestTaskId = taskId;
    const selection = selectionVersionRef.current;
    const requestToken = { taskId: requestTaskId };
    chatRequestRef.current = requestToken;
    setChatSending(true);
    setErrorMessage('');
    // 按钮发的指令(继续、重跑)不是输入框里那段话：输入框里写到一半的内容留着不动。
    const fromComposer = chatInput === text || chatInput.trimStart().startsWith('/');
    const draft = chatInput;
    if (fromComposer) {
      setChatInput('');
      chatInputRef.current = '';
    }
    const userMessageId = nextMessageId();
    const pendingId = nextMessageId();
    const knownEntries = new Set((taskDataRef.current?.chatHistory ?? []).map(entry => entry.id));
    // 没发出去：撤掉这条气泡和等待气泡，把输入框里原来的文字还回去，改完可以直接重发。
    // 等的时候输入框里又写了别的，就留着这条气泡：两段话都还在屏幕上。
    const returnUnsent = () => {
      const typedSince = fromComposer && chatInputRef.current !== '';
      setChatMessages(prev => prev.filter(m => m.id !== pendingId && (typedSince || m.id !== userMessageId)));
      if (fromComposer && !typedSince) setChatInput(draft);
    };

    // 添加用户发送的文本气泡
    setChatMessages(prev => [
      ...prev,
      { id: userMessageId, sender: 'user', text: text }
    ]);

    setChatMessages(prev => [
      ...prev,
      { id: pendingId, sender: 'ai', text: tr('🧠 正在理解您的指令...') }
    ]);

    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${requestTaskId}/assistant`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, context: assistantContext() })
      });
      if (res.ok) {
        const data: { reply: string; action: string; stage: number | null; task: TaskResponse; tool_calls?: unknown; proposal?: unknown } = await res.json();
        if (chatRequestRef.current !== requestToken || selection !== selectionVersionRef.current || !canAcceptTaskResponse(selectedTaskIdRef.current, data.task.taskId)) return;
        appliedStatusRequestRef.current = ++statusRequestRef.current;
        restoreChatRef.current = null;
        setTaskData(data.task);
        taskDataRef.current = data.task;

        // 替换等待气泡为助手回复
        setChatMessages(prev => {
          const withoutPending = prev.filter(m => m.id !== pendingId);
          if (!data.task.chatHistory?.length) {
            const cards = chatCardsFrom(data.tool_calls, data.proposal);
            return [
              ...withoutPending,
              { id: nextMessageId(), sender: 'ai', text: data.reply, ...(cards.length ? { cards } : {}) },
            ];
          }
          return mergeWorkflowHistory(withoutPending.filter(m => m.id !== userMessageId), data.task);
        });

        // 助手在界面上打开了某场的视图：切到分镜看板并把动作交给看板；下载直接触发，不必再点按钮。
        const storyboardAction = storyboardActionFrom(data.tool_calls, Date.now());
        if (storyboardAction) {
          setActiveTabStage(4);
          if (storyboardAction.view === 'download') {
            void downloadStoryboardScene(requestTaskId, storyboardAction.sceneId, `${storyboardAction.sceneId}-时序分镜`);
            setStoryboardViewAction({ ...storyboardAction, view: 'board' });
          } else {
            setStoryboardViewAction(storyboardAction);
          }
        }

        // 执行类动作：切换看板标签并开启轮询，进度卡实时展示调用过程与百分比
        if (data.action === 'run_stage' || data.action === 'run_all') {
          if (data.stage) setActiveTabStage(data.stage);
          if (data.task.stageProgress) {
            progressRef.current = { stage: data.task.stageProgress.stage, status: data.task.stageProgress.status };
          }
        }
        setIsPolling(shouldPollWorkflow(data.task));
        fetchHistoryTasks();
      } else {
        const err = await res.json();
        if (chatRequestRef.current !== requestToken || selection !== selectionVersionRef.current || selectedTaskIdRef.current !== requestTaskId) return;
        // 服务端先把这句话记进对话再处理，被拒绝时它多半已经存下了。以服务端的记录为准：
        // 存下了就只留存下的那条气泡，不把文字还回输入框，否则重发会在对话里记两遍。
        await fetchTaskStatus(requestTaskId);
        if (chatRequestRef.current !== requestToken || selection !== selectionVersionRef.current || selectedTaskIdRef.current !== requestTaskId) return;
        const recorded = (taskDataRef.current?.chatHistory ?? []).some(entry => (
          entry.role === 'user' && entry.content === text.trim() && !knownEntries.has(entry.id)
        ));
        if (recorded) setChatMessages(prev => prev.filter(m => m.id !== pendingId && m.id !== userMessageId));
        else returnUnsent();
        // 积分不足由顶部的充值提示说明，这里不再重复一条。
        if (res.status !== 402) setErrorMessage(err.detail || tr('发送指令失败'));
      }
    } catch {
      if (chatRequestRef.current !== requestToken || selection !== selectionVersionRef.current || selectedTaskIdRef.current !== requestTaskId) return;
      setErrorMessage(tr('发送消息失败，请检查后端网络连接。'));
      returnUnsent();
    } finally {
      if (chatRequestRef.current === requestToken) {
        chatRequestRef.current = null;
        if (selection === selectionVersionRef.current && selectedTaskIdRef.current === requestTaskId) setChatSending(false);
      }
    }
  };

  // 载入已有项目
  const handleLoadTask = (task: TaskSummary) => {
    setErrorMessage('');
    setTaskId(task.taskId);
    restoreChatRef.current = task.taskId;
    chatRequestRef.current = null;
    setChatSending(false);
    taskDataRef.current = { ...task, assets: {}, logs: {} };
    // The lobby row carries no assets; show the shell immediately and pull the
    // full project (scripts, storyboards, logs) right after.
    setTaskData({ ...task, assets: {}, logs: {} });
    void fetchTaskStatus(task.taskId);
    setActiveTabStage(task.currentStage > 0 ? task.currentStage : 1);
    setIsPolling(task.status === 'running');
    episodeRequestGenerationRef.current += 1;
    setEpisodeState({ taskId: task.taskId, sourceHash: '', items: [] });
    fetchEpisodes(task.taskId); // 载入已有的分集制作清单

    // 同步配置状态，以便工作台侧边栏能够高亮匹配该项目的实际模型配置
    if (task.config) {
      setConfig({
        titleSuggestion: task.config.titleSuggestion || '',
        scriptName: task.config.scriptName,
        scriptContent: task.config.scriptContent,
        directorStyle: task.config.directorStyle || DEFAULT_DIRECTOR_STYLE,
        shotStyle: task.config.shotStyle || DEFAULT_SHOT_STYLE,
        llmModel: task.config.llmModel || globalModelDefaults.text,
        imageModel: task.config.imageModel || globalModelDefaults.image,
        videoModel: task.config.videoModel || globalModelDefaults.video,
        ttsModel: task.config.ttsModel || globalModelDefaults.audio,
        videoReferenceMode: normalizeVideoReferenceMode(task.config.videoReferenceMode),
        oneClick: task.config.oneClick || false,
        episodeCount: task.config.episodeCount || clientConfig.episodeCount.default
      });
    }
    
    // The summary intentionally omits assets. Do not infer completion or the
    // next stage until the full authoritative workflow and history arrive.
    setChatMessages([
      { id: 'loading-history', sender: 'ai', text: tr('正在为您恢复《{0}》的对话和八大 Agent 流程进度…', [task.config.titleSuggestion]) }
    ]);
    progressRef.current = task.stageProgress ? { stage: task.stageProgress.stage, status: task.stageProgress.status } : null;
  };

  // 统一的配置同步方法，如果在工作台内，还会自动向后端请求更新配置以应用在下一步执行中
  const updateConfigAndSync = async (newConfig: Partial<TaskConfig>) => {
    const updated = { ...config, ...newConfig };
    setConfig(updated);
    if (taskId) {
      try {
        const res = await apiFetch(`${API_BASE}/api/drama/${taskId}/update_config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updated)
        });
        if (res.ok) {
          const data = await res.json();
          setTaskData(data);
        } else {
          // 改模型被拒(如阶段运行中)时要说出来，不能让界面显示新模型、项目却还在用旧的。
          const detail = await res.json().then(body => (typeof body?.detail === 'string' ? body.detail : ''), () => '');
          setConfig(config);
          alert(detail || tr('同步配置失败（HTTP {0}）', [res.status]));
        }
      } catch (e) {
        console.error('同步配置到后端失败', e);
        alert(tr('同步配置到后端失败，请稍后重试'));
      }
    }
  };

  // 大厅项目卡片的暂停 / 恢复：没成功就把原因说出来，卡片状态不变不能当作没点到
  const runCardAction = async (id: string, action: 'pause' | 'resume') => {
    const fallback = action === 'pause' ? tr('暂停项目失败，请稍后重试。') : tr('恢复项目失败，请稍后重试。');
    setErrorMessage('');
    try {
      const res = await apiFetch(`${API_BASE}/api/drama/${id}/${action}`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchHistoryTasks();
        return;
      }
      const err = await res.json().catch(() => null);
      const reason = typeof err?.detail === 'string' && err.detail ? err.detail : fallback;
      setCardActionError(reason);
      setErrorMessage(reason);
    } catch (e) {
      console.error(action === 'pause' ? '暂停任务失败' : '恢复任务失败', e);
      setCardActionError(fallback);
      setErrorMessage(fallback);
    }
  };

  // 大厅项目卡片暂停操作
  const handleCardPause = (id: string) => runCardAction(id, 'pause');

  // 大厅项目卡片恢复一键成片操作
  const handleCardResume = (id: string) => runCardAction(id, 'resume');

  // 没建成：弹窗重新打开，原因写在里面，填过的内容原样留着，改完可以直接再点创建
  const reopenCreateModal = (reason: string) => {
    setCreateError(reason);
    setShowCreateModal(true);
  };

  // 磨砂玻璃 Modal 弹窗确认创建真实短剧项目
  const handleConfirmCreate = async () => {
    if (!newProjectName.trim()) {
      setCreateError(tr("请输入短剧选题名称！"));
      return;
    }
    setErrorMessage('');
    setCreateError('');
    setShowCreateModal(false);
    
    // 初始化工作台聊天提示
    setChatMessages([
      { id: '1', sender: 'user', text: newProjectName },
      { id: '2', sender: 'ai', text: tr('正在创建项目。创建后，我会从总导演开始，按顺序陪您完成八大 Agent 流程。') }
    ]);

    const currentConfig = {
      titleSuggestion: newProjectName,
      directorStyle: newProjectDirectorStyle,
      stylePack: newProjectStylePack,
      shotStyle: newProjectShotStyle,
      llmModel: config.llmModel,
      imageModel: config.imageModel,
      videoModel: config.videoModel,
      ttsModel: config.ttsModel,
      videoReferenceMode: config.videoReferenceMode,
      narrationDelivery: newProjectNarrationDelivery,
      creationMode: newProjectCreationMode,
      contentLanguage: newProjectContentLanguage,
      ...(newProjectCreationMode === 'ad' ? { adBrief: newProjectAdBrief } : {}),
      poetrySources: config.poetrySources ?? [],
      episodeCount: clampEpisodeCount(newProjectEpisodes, clientConfig.episodeCount), // 一次性生成的剧本集数 (视频按集逐集制作)
      oneClick: newProjectOneClick // 由新建弹窗的「成片方式」选择决定：一键成片 / 分步引导
    };

    try {
      const res = await apiFetch(`${API_BASE}/api/drama/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskId(data.taskId);
        setTaskData(data);
        taskDataRef.current = data;
        setActiveTabStage(1);
        await startCreatedWorkflow(data, newProjectOneClick);
        fetchHistoryTasks();
        setNewProjectName(''); // 清空输入
      } else {
        const err = await res.json().catch(() => null);
        reopenCreateModal(typeof err?.detail === 'string' && err.detail ? err.detail : tr('创建项目失败'));
      }
    } catch {
      reopenCreateModal(tr('无法连接至后端，请先确保后端运行中。'));
    }
  };

  if (!authChecked) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-dark)',
        color: 'var(--text-dim)',
        fontFamily: 'inherit'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <div className="loading-spinner" />
          <span style={{ fontSize: '0.95rem', letterSpacing: '1px' }}>{tr('正在加载 AI 协同系统会话...')}</span>
        </div>
      </div>
    );
  }

  if (authChecked && !currentUser) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(circle at 50% -20%, var(--surface) 0%, var(--bg-dark) 100%)',
        padding: '20px',
        position: 'relative',
        overflow: 'hidden'
      }}>
        {/* 背景动态流光感装饰球 */}
        <div style={{ position: 'absolute', width: '300px', height: '300px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(var(--accent-rgb), 0.12) 0%, transparent 70%)', top: '-10%', left: '-5%', filter: 'blur(30px)' }} />
        <div style={{ position: 'absolute', width: '400px', height: '400px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(255, 51, 102, 0.08) 0%, transparent 70%)', bottom: '-10%', right: '-5%', filter: 'blur(40px)' }} />

        {/* 仅 AUTH_EXPOSE_MOCK_CODE=1 的本地开发环境显示；生产环境无此字段。 */}
        {mockVerificationCode && (
          <div className="glass-panel" style={{
            position: 'absolute',
            top: '24px',
            right: '24px',
            border: '1px solid rgba(var(--accent-rgb), 0.4)',
            boxShadow: '0 0 15px rgba(var(--accent-rgb), 0.2)',
            zIndex: 99999,
            padding: '12px 18px',
            borderRadius: '12px',
            background: 'rgba(var(--surface-rgb), 0.95)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            animation: 'ping 1.5s ease-in-out infinite alternate'
          }}>
            <span style={{ color: 'var(--neon-cyan)', fontSize: '0.85rem', fontWeight: 600 }}>{tr('💡 [演示通道] 验证码为:')}</span>
            <strong style={{ fontSize: '1.05rem', color: 'var(--ink)', letterSpacing: '2px', fontFamily: 'monospace' }}>{mockVerificationCode}</strong>
          </div>
        )}

        <div className="glass-panel" style={{
          width: '100%',
          maxWidth: '440px',
          padding: '32px',
          border: '1px solid rgba(var(--accent-rgb), 0.176)',
          boxShadow: '0 25px 50px -12px rgba(var(--shadow-rgb), 0.275)',
          background: 'rgba(var(--surface-rgb), 0.55)',
          backdropFilter: 'blur(30px)',
          WebkitBackdropFilter: 'blur(30px)',
          borderRadius: '24px',
          position: 'relative',
          zIndex: 10
        }}>
          {/* 系统头部 Logo 与名称 */}
          <div style={{ textAlign: 'center', marginBottom: '28px' }}>
            <h2 style={{ fontSize: '1.8rem', fontWeight: 700, letterSpacing: '2px', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', marginBottom: '8px' }}>
              {PRODUCT_TITLE}
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{tr('工业级 AI 短剧多智能体协同成片平台')}</p>
            <div style={{ marginTop: '10px' }}><LanguageSwitcher /></div>
          </div>

          {/* 表单切换 Tab 栏 */}
          <div style={{ display: 'flex', borderBottom: '1px solid rgba(var(--accent-rgb), 0.132)', marginBottom: '24px', paddingBottom: '2px' }}>
            <button
              onClick={() => { setAuthTab('login_pwd'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'login_pwd' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              {tr('密码登录')}
            </button>
            <button
              onClick={() => { setAuthTab('login_code'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'login_code' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              {tr('验证码登录')}
            </button>
            <button
              onClick={() => { setAuthTab('register'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'register' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              {tr('快速注册')}
            </button>
          </div>

          {/* 统一提示信息反馈 */}
          {authError && (
            <div style={{ background: 'rgba(211, 18, 18, 0.12)', border: '1px solid var(--neon-red)', color: 'var(--danger)', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
              ⚠️ {authError}
            </div>
          )}
          {authSuccess && (
            <div style={{ background: 'rgba(16, 185, 129, 0.12)', border: '1px solid var(--neon-green)', color: '#1cca7a', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
              ✓ {authSuccess}
            </div>
          )}

          {/* 登录注册表单主体 */}
          <form onSubmit={handleAuthSubmit}>
            {authTab === 'login_pwd' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('账号 (手机号或邮箱)')}</label>
                  <input
                    type="text"
                    required
                    placeholder={tr('请输入绑定的手机号或邮箱')}
                    value={authForm.loginId}
                    onChange={e => setAuthForm({ ...authForm, loginId: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('密码')}</label>
                  <input
                    type="password"
                    required
                    placeholder={tr('请输入您的密码')}
                    value={authForm.password}
                    onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
              </div>
            )}

            {authTab === 'login_code' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('手机号或邮箱')}</label>
                  <input
                    type="text"
                    required
                    placeholder={tr('请输入绑定的手机号或邮箱')}
                    value={authForm.loginId}
                    onChange={e => setAuthForm({ ...authForm, loginId: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('{0}位验证码', [clientConfig.verificationCode.length])}</label>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <input
                      type="text"
                      required
                      maxLength={clientConfig.verificationCode.length}
                      placeholder={tr('验证码')}
                      value={authForm.code}
                      onChange={e => setAuthForm({ ...authForm, code: e.target.value })}
                      style={{ flex: 1, padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none', textAlign: 'center', letterSpacing: '2px', fontFamily: 'monospace' }}
                    />
                    <button
                      type="button"
                      disabled={codeCountdown > 0}
                      onClick={handleSendVerificationCode}
                      className="capsule-btn"
                      style={{ padding: '0 16px', fontSize: '0.75rem', whiteSpace: 'nowrap', minWidth: '110px', justifyContent: 'center' }}
                    >
                      {codeCountdown > 0 ? tr('{0}s 重发', [codeCountdown]) : tr('获取验证码')}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {authTab === 'register' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('注册邮箱 (选填)')}</label>
                  <input
                    type="email"
                    placeholder={tr('请输入注册邮箱')}
                    value={authForm.email}
                    onChange={e => setAuthForm({ ...authForm, email: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('注册手机号 (选填)')}</label>
                  <input
                    type="text"
                    placeholder={tr('请输入注册手机号')}
                    value={authForm.phone}
                    onChange={e => setAuthForm({ ...authForm, phone: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>{tr('登录密码')}</label>
                  <input
                    type="password"
                    required
                    placeholder={tr('设置登录密码，不少于{0}位', [clientConfig.passwordMinLength])}
                    value={authForm.password}
                    onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
              </div>
            )}

            <button
              type="submit"
              className="cyber-btn"
              style={{
                width: '100%',
                marginTop: '28px',
                padding: '12px',
                borderRadius: '8px',
                background: 'linear-gradient(135deg, var(--accent), var(--accent-2))',
                color: 'var(--ink)',
                fontWeight: 600,
                fontSize: '0.9rem',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                boxShadow: '0 4px 15px rgba(var(--accent-rgb), 0.15)'
              }}
            >
              {authTab === 'register' ? tr('提交注册') : tr('立即登录')}
            </button>
          </form>

          {/* 安全提示：仅本地开发且后端启用了管理员引导时显示 */}
          {bootstrapAdminLogin && (
            <div style={{ marginTop: '20px', borderTop: '1px solid rgba(var(--accent-rgb), 0.088)', paddingTop: '14px', fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div>{tr('🔐 本地默认管理员：')}<strong>{bootstrapAdminLogin}</strong></div>
              <div>{tr('登录配置位于后端 `.env`；首次登录必须修改。生产环境禁止使用开发默认密码。')}</div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // 素材库里也有扣积分的生成，所以这条提示不只挂在工作台。
  const billingNoticeBar = billingNotice && (
    <div className="billing-required" role="alert">
      <span>{billingNotice}</span>
      {/积分不足|升级套餐/.test(billingNotice) && (
        <button type="button" className="billing-required__action" onClick={() => { setBillingNotice(''); setActivePortal('billing'); }}>{tr('去充值')}</button>
      )}
      <button type="button" className="billing-required__action" onClick={() => setBillingNotice('')}>{tr('关闭')}</button>
    </div>
  );

  if (currentUser && activePortal === 'user') {
    return <Suspense fallback={<StageFallback />}><UserCenterPage onBack={() => setActivePortal('home')} onUserChange={setCurrentUser} passwordMinLength={clientConfig.passwordMinLength} /></Suspense>;
  }

  if (currentUser && activePortal === 'finance') {
    return <Suspense fallback={<StageFallback />}><FinanceConsolePage user={currentUser} onBack={() => setActivePortal('home')} /></Suspense>;
  }
  if (currentUser && activePortal === 'billing') {
    return <Suspense fallback={<StageFallback />}><BillingCenterPage inProject={taskId !== ''} onBack={() => setActivePortal('home')} /></Suspense>;
  }

  if (currentUser && ['actor', 'scene', 'prop', 'effect', 'extra', 'vehicle', 'stunt', 'set_dressing'].includes(activePortal)) {
    // 车辆、商品并在拍摄道具页里(elementTypes 的 TAB_MEMBERS)：从旧入口打开车辆也落到拍摄道具页。
    return <>{billingNoticeBar}<Suspense fallback={<StageFallback />}><ElementLibraryPage initialKind={tabOfKind(activePortal as ElementKind)} onBack={() => setActivePortal('home')} /></Suspense></>;
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {billingNoticeBar}
      


      {/* 1. 未进入项目：主配置大厅 (截图 1, 2) */}
      {taskId === '' ? (
        <div className="lobby">
          
          {/* 顶栏：左侧品牌，右侧通知、积分与账号 */}
          <header className="lobby-header">
            <div className="lobby-brand">
              <span className="lobby-brand__mark"><Clapperboard size={16} aria-hidden="true" /></span>
              <span className="lobby-brand__name">{PRODUCT_TITLE}</span>
              <span className="lobby-brand__tag">{tr('AI 短剧协同成片')}</span>
            </div>
            <div className="lobby-header__actions">
            <NotificationBell onOpenBilling={() => setActivePortal('billing')} onOpenFinance={() => setActivePortal('finance')} />
            {walletPoints !== null && (
              <span title={tr('可用创作积分')} className="lobby-credits">
                <Zap size={13} aria-hidden="true" /> {tr('{0} 积分', [walletPoints])}
              </span>
            )}
            <div
              className="lobby-account"
              onMouseEnter={() => setShowUserMenu(true)}
              onMouseLeave={() => setShowUserMenu(false)}
              onKeyDown={e => {
                if (e.key !== 'Escape') return;
                setShowUserMenu(false);
                // 菜单项随菜单一起消失，焦点交还给头像，键盘用户不用从页首重新找。
                e.currentTarget.querySelector<HTMLButtonElement>('.lobby-avatar')?.focus();
              }}
              onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setShowUserMenu(false); }}
            >
              <button
                type="button"
                className="lobby-avatar"
                aria-haspopup="menu"
                aria-expanded={showUserMenu}
                aria-label={tr('账号菜单')}
                onClick={() => setShowUserMenu(true)}
              >
                <User size={16} color="var(--on-accent)" />
              </button>
              
              {showUserMenu && currentUser && (
                <div className="glass-panel account-menu">
                  <div className="account-menu__name">
                    👤 {currentUser.username || tr('当前用户')}
                  </div>
                  <div className="account-menu__id">
                    {currentUser.email || currentUser.phone || tr('未绑定账号')}
                  </div>
                  <button className="account-menu-action" onClick={() => { setActivePortal('user'); setShowUserMenu(false); }}>
                    {tr('用户中心')}
                  </button>
                  <button className="account-menu-action" onClick={() => { setActivePortal('billing'); setShowUserMenu(false); }}>
                    {tr('会员与支付')}
                  </button>
                  {FINANCE_PERMISSIONS.some(permission => hasPermission(currentUser, permission)) && (
                    <button className="account-menu-action" onClick={() => { setActivePortal('finance'); setShowUserMenu(false); }}>
                      {tr('财务后台')}
                    </button>
                  )}
                  <button onClick={handleLogout} className="account-menu-action is-danger">
                    {tr('退出登录')}
                  </button>
                  <div style={{ marginTop: '8px' }}><LanguageSwitcher /></div>
                </div>
              )}
            </div>
            </div>
          </header>

          {/* 标题 */}
          <div className="hero">
            <h2 className="hero-title">
              {tr('{0} - 你的专属AI视频创作Agent', [PRODUCT_TITLE])}
            </h2>
            <p className="hero-sub">
              {tr('把品味和习惯写进Skill，让精力回归创意')}
            </p>
          </div>

          {/* 核心创意输入框 (带气泡) */}
          <div style={{ position: 'relative', width: '100%' }}>
            {errorMessage && errorMessage !== cardActionError && (
              <div className="error-banner">
                ⚠️ {errorMessage}
              </div>
            )}
            <div className="creative-input-card">
              <textarea 
                className="creative-textarea"
                placeholder={uploadedScript ? `已加载手动剧本《${uploadedScript.name}》，共 ${scriptContent.length} 字。\n您可在此输入特定导演风格或视觉修改意见，或直接点击发送生成短剧。` : "由一个想法或故事开始..."}
                value={lobbyIdea}
                onChange={e => setLobbyIdea(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    initDramaProject(lobbyIdea);
                  }
                }}
              />
              
              <div className="creative-toolbar">
                {/* 左下角三个胶囊按钮 */}
                <div className="creative-toolbar__tools">
                  
                  {/* 模型选择按钮 */}
                  <button 
                    type="button" 
                    className={`capsule-btn ${showModelConfiguration ? 'active' : ''}`}
                    onClick={() => { setActivePopover('none'); setShowModelConfiguration(true); }}
                  >
                    <Cpu size={14} /> {tr('模型: {0}', [hasEnabledGlobalModel ? tr('已配置') : tr('未配置')])}
                  </button>

                  {/* Skill 选择按钮 */}
                  <button 
                    type="button" 
                    className={`capsule-btn ${showProjectSkillManager ? 'active' : ''}`}
                    onClick={() => { setActivePopover('none'); setShowProjectSkillManager(true); }}
                  >
                    <Sliders size={14} /> {tr('Skill: 项目管理')}
                  </button>

                  <button
                    type="button"
                    className={`capsule-btn ${activePopover === 'element' ? 'active' : ''}`}
                    onClick={() => setActivePopover(activePopover === 'element' ? 'none' : 'element')}
                    aria-haspopup="menu"
                    aria-expanded={activePopover === 'element'}
                  ><Folder size={14} /> {tr('元素')}</button>

                  <button
                    type="button"
                    className={`capsule-btn ${activePopover === 'poetry' || (config.poetrySources?.length ?? 0) > 0 ? 'active' : ''}`}
                    onClick={() => setActivePopover(activePopover === 'poetry' ? 'none' : 'poetry')}
                    aria-expanded={activePopover === 'poetry'}
                  ><BookOpen size={14} /> {(config.poetrySources?.length ?? 0) > 0 ? tr('诗词取材 {0}', [String(config.poetrySources?.length)]) : tr('诗词取材')}</button>

                  {activePopover === 'poetry' && (
                    <PoetrySourcePicker value={config.poetrySources ?? []} onChange={next => setConfig({ ...config, poetrySources: next })} />
                  )}

                  {activePopover === 'element' && (
                    <div className="element-menu" role="menu" aria-label={tr('选择元素类型')}>
                      {([
                        ['actor', tr('演员'), tr('设定集与表演身份锚点')],
                        ['scene', tr('场景'), tr('空间、时段、天气和灯光；置景也在这里')],
                        ['prop', tr('道具'), tr('归属、位置和状态连续性；车辆、商品也在这里')],
                        ['effect', tr('特效'), tr('时间、目标和结束状态；特技也在这里')],
                        ['extra', tr('群演'), tr('没有台词的背景人物')],
                      ] as Array<[ElementKind, string, string]>).map(([value, label, hint]) => (
                        <button key={value} type="button" role="menuitem" onClick={() => { setActivePortal(value); setActivePopover('none'); }}>
                          <span>{label}</span><small>{hint}</small><ChevronRight size={15} />
                        </button>
                      ))}
                    </div>
                  )}

                  <button 
                    type="button" 
                    className={`capsule-btn ${uploadedScript ? 'active' : ''}`}
                    onClick={() => fileInputRef.current?.click()}
                    style={{ position: 'relative' }}
                    title={uploadedScript ? tr('已加载手动剧本，点击可重新上传') : tr('上传手动剧本并一键生成短剧')}
                  >
                    <Upload size={14} /> {uploadedScript ? tr('已选剧本: {0}', [`${uploadedScript.name.substring(0, 10)}${uploadedScript.name.length > 10 ? '...' : ''}`]) : tr('上传剧本')}
                    {uploadedScript && (
                      <span 
                        onClick={(e) => {
                          e.stopPropagation();
                          setUploadedScript(null);
                          setScriptContent('');
                          if (fileInputRef.current) fileInputRef.current.value = '';
                        }} 
                        style={{ marginLeft: '6px', color: 'var(--neon-red)', cursor: 'pointer', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center' }}
                        title={tr('清除剧本并切换回普通选题模式')}
                      >
                        <X size={10} />
                      </span>
                    )}
                  </button>
                  <input 
                    type="file" 
                    ref={fileInputRef} 
                    style={{ display: 'none' }} 
                    accept={clientConfig.scriptUpload.extensions.join(',')}
                    onChange={handleScriptUpload}
                  />

                  {/* Skill 选择气泡弹窗 */}
                  {activePopover === 'skill' && (
                    <div className="popover-window" style={{ bottom: '45px', left: '120px', width: '300px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.132)', paddingBottom: '6px' }}>
                        <h4 style={{ fontSize: '0.9rem', margin: 0 }}>{tr('内置与导入 Skills')}</h4>
                        <button 
                          onClick={() => { setShowImportSkillModal(true); setActivePopover('none'); }}
                          style={{ background: 'transparent', border: 'none', color: 'var(--neon-cyan)', fontSize: '0.75rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '2px' }}
                        >
                          {tr('+ 导入外部Skill')}
                        </button>
                      </div>
                      <div 
                        onClick={() => {
                          updateConfigAndSync({ shotStyle: 'cinematic', directorStyle: 'cyberpunk' });
                          setActivePopover('none');
                        }}
                        className={`model-list-item ${config.shotStyle === 'cinematic' ? 'selected' : ''}`}
                      >
                        <div><strong>{tr('AI 短剧一站式生成')}</strong></div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{tr('内置36运镜及100+质检')}</span>
                      </div>
                      <div 
                        onClick={() => {
                          updateConfigAndSync({ shotStyle: 'standard', directorStyle: 'realistic' });
                          setActivePopover('none');
                        }}
                        className={`model-list-item ${config.shotStyle === 'standard' ? 'selected' : ''}`}
                      >
                        <div><strong>{tr('剧情短片生成')}</strong></div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{tr('经典正反打文戏对切')}</span>
                      </div>

                      {importedSkills.map(s => (
                        <div 
                          key={s.name}
                          onClick={() => {
                            updateConfigAndSync({ shotStyle: s.name });
                            setActivePopover('none');
                          }}
                          className={`model-list-item ${config.shotStyle === s.name ? 'selected' : ''}`}
                          style={{ position: 'relative', paddingRight: '32px' }}
                        >
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteSkill(s.name);
                            }}
                            style={{
                              position: 'absolute',
                              top: '50%',
                              right: '8px',
                              transform: 'translateY(-50%)',
                              background: 'transparent',
                              border: 'none',
                              color: 'rgba(var(--accent-rgb), 0.88)',
                              cursor: 'pointer',
                              padding: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              zIndex: 10
                            }}
                            title={tr('物理删除该技能包')}
                          >
                            <X size={12} />
                          </button>
                          <div><strong>{s.name}</strong> <span style={{ fontSize: '0.65rem', padding: '1px 4px', background: 'var(--neon-green)', color: 'var(--on-accent)', borderRadius: '4px', marginLeft: '4px', fontWeight: 'bold' }}>{tr('已导入')}</span></div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{s.description}</span>
                        </div>
                      ))}
                    </div>
                  )}

                </div>

                {/* 右下角圆形发送按钮 */}
                <button 
                  onClick={() => initDramaProject(lobbyIdea)}
                  className="cyber-btn creative-send"
                  aria-label={tr('开始创作')}
                >
                  <ArrowUp size={18} color="var(--on-accent)" />
                </button>

              </div>
            </div>

          </div>

          {/* 热门 Skills 卡片横列 */}
          {showSkillsGrid && (
            <div className="skills-section">
              <div className="skills-head">
                <span className="skills-head__label">
                  {tr('🔥 推荐创作 Skills (点击快速填入选题)')}
                </span>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  <button 
                    onClick={() => setShowProjectSkillManager(true)}
                    className="skills-head__manage"
                  >
                    {tr('+ 管理项目 Skill')}
                  </button>
                  <button 
                    onClick={() => setShowSkillsGrid(false)} 
                    className="skills-head__hide"
                    title={tr('关闭推荐')}
                  >
                    <X size={14} /> {tr('隐藏')}
                  </button>
                </div>
              </div>
              <div className="skills-grid">
                {recommendedTemplates.map(item => (
                  <div 
                    key={item.id}
                    className="skill-card" 
                    style={{ position: 'relative' }}
                    onClick={() => {
                      setLobbyIdea(item.prompt);
                      setConfig({ ...config, titleSuggestion: item.prompt });
                    }}
                  >
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRecommendedTemplates(prev => prev.filter(t => t.id !== item.id));
                      }}
                      className="skill-card__remove"
                      title={tr('删除该模版')}
                      aria-label={tr('删除该模版')}
                    >
                      <X size={10} />
                    </button>
                    <strong className="skill-card__title">{tr(item.title)}</strong>
                    <span className="skill-card__desc">{tr(item.desc)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 项目大厅：先看自己的项目，再看平台能力 */}
          <section className="project-lobby" aria-labelledby="project-lobby-title">
            <div className="project-lobby__head">
              <h3 id="project-lobby-title"><HardDrive size={18} aria-hidden="true" /> {tr('断点续传项目大厅')}</h3>
              <span className="project-lobby__count">{historyTasks.length} {tr('个项目')}</span>
              <button
                type="button"
                className="project-lobby__new"
                onClick={() => {
                  setNewProjectName('');
                  setCreateError('');
                  setShowCreateModal(true);
                }}
              >
                <Plus size={15} aria-hidden="true" /> {tr('创建新项目')}
              </button>
            </div>

            {errorMessage && errorMessage === cardActionError && (
              <div className="error-banner error-banner--pinned" role="alert">
                <span>{errorMessage}</span>
                <button type="button" aria-label={tr('关闭提示')} title={tr('关闭提示')} onClick={() => setErrorMessage('')}>
                  <X size={14} aria-hidden="true" />
                </button>
              </div>
            )}

            {historyLoaded && historyTasks.length === 0 ? (
              <div className="project-lobby__empty">
                <Film size={28} aria-hidden="true" />
                <strong>{tr('还没有项目')}</strong>
                <span>{tr('在上方输入一个想法，或点击「创建新项目」开始第一部短剧。')}</span>
              </div>
            ) : (
              <div className="project-grid">
                {historyTasks.map(task => {
                  const isRunning = task.status === 'running';
                  const isCompleted = task.status === 'completed';
                  const isIdle = task.status === 'idle' || task.status === 'paused';
                  const { label: statusLabel, tone } = projectStatusView(task.status);

                  // 进度百分比
                  const progressPct = Math.min(Math.round((displayStep(task.currentStage) / DISPLAY_STEPS) * 100), 100);

                  return (
                    <div
                      key={task.taskId}
                      onClick={() => handleLoadTask(task)}
                      onKeyDown={e => {
                        if (e.target !== e.currentTarget) return;
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleLoadTask(task);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      className={`glass-panel project-card is-${tone}`}
                    >
                      <button
                        type="button"
                        className="project-card__delete"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteTask(task.taskId);
                        }}
                        title={tr('删除任务项目')}
                        aria-label={tr('删除任务项目')}
                      >
                        <X size={12} />
                      </button>

                      <div className="project-card__head">
                        <span className="project-card__title" title={task.config.titleSuggestion}>
                          {task.config.titleSuggestion}
                        </span>
                        <span className="project-card__status">{statusLabel}</span>
                      </div>

                      <p className="project-card__meta">
                        {isCompleted ? (
                          <span>{tr('🎉 已完成一键成片 (100%)')}</span>
                        ) : (
                          <span>
                            {tr('当前进度: 第 {0}/{1} 步 ({2})', [displayStep(task.currentStage), DISPLAY_STEPS, task.stageName])}
                            {isRunning ? (
                              <span className="is-live"> {tr('- 正在生成...')}</span>
                            ) : (
                              <span> - {statusLabel}</span>
                            )}
                          </span>
                        )}
                      </p>

                      <div className="project-card__bar" aria-hidden="true">
                        <div className="project-card__bar-fill" style={{ width: `${progressPct}%` }} />
                      </div>

                      <div className="project-card__foot">
                        <div className="project-card__ops">
                          {isRunning && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleCardPause(task.taskId);
                              }}
                              className="capsule-btn is-danger"
                            >
                              <Pause size={10} /> {tr('暂停')}
                            </button>
                          )}
                          {isIdle && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleCardResume(task.taskId);
                              }}
                              className="capsule-btn is-accent"
                            >
                              <Play size={10} /> {tr('恢复')}
                            </button>
                          )}
                        </div>

                        <span className="capsule-btn project-card__open" aria-hidden="true">
                          {tr('加载断点')} <ArrowRight size={10} />
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <CapabilityCenter canManage={hasPermission(currentUser, 'capability:manage')} />

          {/* 磨砂玻璃真·创建新项目 Modal 弹窗 */}
          {showCreateModal && (
            <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
              <div
                className="glass-panel create-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="create-modal-title"
                onClick={e => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="create-modal__close"
                  onClick={() => setShowCreateModal(false)}
                  aria-label={tr('关闭')}
                >
                  <X size={18} />
                </button>

                <h3 id="create-modal-title" className="create-modal__title">
                  {tr('🎬 创建全新短剧制作项目')}
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('创意大纲/选题名称')}</label>
                    <input 
                      type="text" 
                      placeholder={tr('例如：重生之我在火山方舟当车载配件巨头')}
                      value={newProjectName}
                      onChange={e => { setNewProjectName(e.target.value); setCreateError(''); }}
                      style={{ width: '100%', padding: '10px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.9rem' }}
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('导演风格')}</label>
                      <select 
                        value={newProjectDirectorStyle}
                        onChange={e => setNewProjectDirectorStyle(e.target.value)}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {DIRECTOR_STYLES.map(style => (
                          <option key={style.id} value={style.id}>{tr(style.label)}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('画面风格锁')}</label>
                      <select
                        value={newProjectStylePack}
                        onChange={e => setNewProjectStylePack(e.target.value)}
                        title={tr('全片统一的画面质感：分镜图、首尾帧与每一镜视频提示词都按它编译')}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {stylePacks.map(pack => (
                          <option key={pack.id} value={pack.id}>{pack.name}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('运镜风格')}</label>
                      <select 
                        value={newProjectShotStyle}
                        onChange={e => setNewProjectShotStyle(e.target.value)}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {SHOT_STYLES.map(style => (
                          <option key={style.id} value={style.id}>{tr(style.label)}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="new-project-content-language" style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('剧本语言')}</label>
                      <select
                        id="new-project-content-language"
                        value={newProjectContentLanguage}
                        onChange={e => setNewProjectContentLanguage(e.target.value as ContentLanguage)}
                        title={tr('标题、台词、旁白、正文与画面描述都用这种语言写；界面语言另在右上角切换')}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {CONTENT_LANGUAGE_OPTIONS.map(option => (
                          <option key={option.id} value={option.id}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="new-project-creation-mode" style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('创作类型')}</label>
                      <select
                        id="new-project-creation-mode"
                        value={newProjectCreationMode}
                        onChange={e => setNewProjectCreationMode(e.target.value as CreationMode)}
                        title={tr(CREATION_MODE_OPTIONS.find(option => option.id === newProjectCreationMode)?.hint ?? '')}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {CREATION_MODE_OPTIONS.map(option => (
                          <option key={option.id} value={option.id}>{tr(option.label)}</option>
                        ))}
                      </select>
                    </div>
                    {newProjectCreationMode === 'ad' && (
                      <div style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }} aria-label={tr('广告简报')}>
                        {([
                          ['product', tr('产品'), tr('如：静音吹风机')],
                          ['sellingPoints', tr('卖点'), tr('如：三分钟速干，45 分贝')],
                          ['audience', tr('目标人群'), tr('如：合租年轻人')],
                          ['callToAction', tr('行动号召'), tr('如：立即下单')],
                        ] as const).map(([key, label, placeholder]) => (
                          <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            {label}
                            <input
                              aria-label={tr('广告{0}', [label])}
                              value={newProjectAdBrief[key]}
                              placeholder={placeholder}
                              onChange={e => setNewProjectAdBrief(current => ({ ...current, [key]: e.target.value }))}
                              style={{ padding: '8px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.8rem' }}
                            />
                          </label>
                        ))}
                      </div>
                    )}
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('旁白交付')}</label>
                      <select
                        value={newProjectNarrationDelivery}
                        onChange={e => setNewProjectNarrationDelivery(e.target.value as NarrationDelivery)}
                        title={tr(NARRATION_DELIVERY_OPTIONS.find(option => option.id === newProjectNarrationDelivery)?.hint ?? '')}
                        style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      >
                        {NARRATION_DELIVERY_OPTIONS.map(option => (
                          <option key={option.id} value={option.id}>{tr(option.label)}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <VideoReferenceModeSelect
                    value={config.videoReferenceMode}
                    onChange={videoReferenceMode => void updateConfigAndSync({ videoReferenceMode })}
                  />
                </div>

                {/* 成片方式 + 集数 (item 3 两种成片方式 / item 6 选择指定集数) */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginTop: '14px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('成片方式')}</label>
                    <select
                      value={newProjectOneClick ? 'one_click' : 'guided'}
                      onChange={e => setNewProjectOneClick(e.target.value === 'one_click')}
                      style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                    >
                      <option value="one_click">{tr('⚡ 一键成片 (后台连续生成全部 8 步)')}</option>
                      <option value="guided">{tr('🧭 一步一步引导 (逐步生成，可对话微调)')}</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>{tr('剧本集数 (一次生成，视频逐集制作)')}</label>
                    <select
                      value={newProjectEpisodesCustom ? 'custom' : String(newProjectEpisodes)}
                      onChange={e => {
                        if (e.target.value === 'custom') {
                          setNewProjectEpisodesCustom(true); // 切到手动填写，保留当前集数作为初始值
                          return;
                        }
                        setNewProjectEpisodesCustom(false);
                        setNewProjectEpisodes(parseInt(e.target.value, 10));
                      }}
                      style={{ width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                    >
                      {EPISODE_COUNT_PRESETS
                        .filter(n => n >= clientConfig.episodeCount.min && n <= clientConfig.episodeCount.max)
                        .map(n => (
                          <option key={n} value={n}>{tr('{0} 集', [n])}</option>
                        ))}
                      <option value="custom">{tr('✏️ 手动填写集数…')}</option>
                    </select>
                    {newProjectEpisodesCustom && (
                      <input
                        type="number"
                        min={clientConfig.episodeCount.min}
                        max={clientConfig.episodeCount.max}
                        value={newProjectEpisodes}
                        onChange={e => setNewProjectEpisodes(clampEpisodeCount(e.target.value, clientConfig.episodeCount))}
                        placeholder={tr('{0}-{1} 集', [clientConfig.episodeCount.min, clientConfig.episodeCount.max])}
                        style={{ width: '100%', marginTop: '8px', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' }}
                      />
                    )}
                  </div>
                </div>

                {createError && <div className="error-banner" role="alert" style={{ margin: '18px 0 0' }}>{createError}</div>}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '18px' }}>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="capsule-btn"
                    style={{ padding: '8px 16px' }}
                  >
                    {tr('取消')}
                  </button>
                  <button
                    onClick={handleConfirmCreate}
                    className="cyber-btn create-modal__submit"
                  >
                    {tr('立即创建项目')}
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      ) : ( // 2. 已进入项目：双栏工作区大厅 (截图 3)
        <div
          ref={workbenchRef}
          className={`workbench-layout ${activeTabStage === 4 && taskData?.assets["4"] ? 'storyboard-mode' : ''}`}
          style={chatSidebarWidth === null ? undefined : ({
            '--workbench-sidebar-width': `${chatSidebarWidth}px`,
          } as CSSProperties)}
        >
          
          {/* 左侧：核心资产产出看版 (70% 宽) */}
          <div id="workbench-asset-viewer" className="asset-viewer">
            
            {/* 顶部二级导航条 */}
            <div className="asset-stage-nav">
              <div className="asset-stage-nav__identity">
                <Film size={22} color="var(--neon-cyan)" />
                <h2>
                  {tr('《{0}》 - 看板展示大厅', [scriptDisplayName])}
                </h2>
              </div>
              <div className="asset-stage-nav__tools" role="group" aria-label={tr('项目工具')}>
                <button type="button" title={tr('节点画布')} onClick={() => setProjectOverlay('canvas')}><Network size={14} aria-hidden="true" /><span>{tr('节点画布')}</span></button>
                <button type="button" title={tr('互动剧')} onClick={() => setProjectOverlay('interactive')}><GitBranch size={14} aria-hidden="true" /><span>{tr('互动剧')}</span></button>
                <button type="button" title={tr('任务中心')} onClick={() => setProjectOverlay('tasks')}><ListChecks size={14} aria-hidden="true" /><span>{tr('任务中心')}</span></button>
                <button type="button" title={tr('项目记忆')} onClick={() => setProjectOverlay('memory')}><BrainCircuit size={14} aria-hidden="true" /><span>{tr('项目记忆')}</span></button>
              </div>
              <AgentStageTabs activeStage={activeTabStage} onChange={setActiveTabStage} />
            </div>

            {/* 当选择的阶段尚无资产时，展示 Novara Slate */}
            <Suspense fallback={<StageFallback />}>
            {activeTabStage === 4 && taskData?.assets["4"] ? (
              <StoryboardWorkspace
                title={taskData.config.titleSuggestion}
                shots={taskData.assets["4"] as StoryboardShot[]}
                taskId={taskId}
                gridUrl={taskData.assets["4_grid"] as string | undefined}
                prompt={taskData.assets["4_grid_prompt"] as string | undefined}
                promptDetail={taskData.assets["4_prompt_detail"]}
                sceneBoards={taskData.assets["4_scene_boards"] as Record<string, SceneBoardStatus> | undefined}
                progress={taskData.assets["4_progress"] as StoryboardProgress | undefined}
                breakdownScenes={(taskData.assets["2_breakdown"] as { scenes?: BreakdownSceneRef[] } | undefined)?.scenes}
                onRefresh={() => { void fetchTaskStatus(taskId); }}
                onRegenerate={() => {
                  // The server drops later stages' output on a storyboard rerun: say what goes before it happens.
                  const warning = storyboardRerunWarning(taskData.assets);
                  if (warning && !window.confirm(warning)) return;
                  void sendChatInstruction('重跑第 4 阶段');
                }}
                externalAction={storyboardViewAction}
                onContinue={() => setActiveTabStage(5)}
              />
            ) : activeTabStage === 1 ? (
              <>
                <DirectorPlanningPage
                  title={taskData?.config.titleSuggestion}
                  directorStyle={taskData?.config.directorStyle}
                  shotStyle={taskData?.config.shotStyle}
                  asset={taskData?.assets["1"]}
                />
                {taskId && <Suspense fallback={null}><StyleReferencePanel taskId={taskId} /></Suspense>}
              </>
            ) : activeTabStage === 2 ? (
              <WriterAgentPageContainer
                taskId={taskId}
                refreshKey={`${taskData?.currentStage}:${taskData?.status}:${Boolean(taskData?.assets["2_writer_dashboard"])}:${scriptDetailStatus}:${castSignature}`}
                displayTitle={scriptDisplayName}
                title={taskData?.config.titleSuggestion}
                fallbackBreakdown={taskData?.assets["2_breakdown"]}
                fallbackScript={taskData?.assets["2"]}
                requestedEpisodeCount={taskData?.config.episodeCount || 0}
                episodes={episodes}
                episodesSourceHash={episodesSourceHash}
                episodesBusy={episodesBusy}
                onPlanEpisodes={() => { void handlePlanEpisodes(); }}
                onProduceEpisode={(episodeIndex) => { void handleProduceEpisode(episodeIndex); }}
                onScriptSaved={handleWriterScriptSaved}
                onOpenScenes={() => { setCharacterAssetKind('scene'); setActiveTabStage(3); }}
                onOpenActors={() => { setCharacterAssetKind('actor'); setActiveTabStage(3); }}
                scriptDetail={taskData?.assets["2_detail"]}
              />
            ) : activeTabStage === 3 ? (
              <CharacterDesignerPageContainer
                key={`${taskId}:${characterAssetKind}`}
                taskId={taskId}
                initialAssetKind={characterAssetKind}
                refreshKey={`${taskData?.currentStage}:${taskData?.status}:${Boolean(taskData?.assets["3_character_dashboard"])}`}
                title={taskData?.config.titleSuggestion}
                fallbackCharacters={taskData?.assets["3_characters"]}
                fallbackSheets={taskData?.assets["3_sheets"]}
                fallbackDna={taskData?.assets["3_dna"]}
                fallbackRaw={taskData?.assets["3"]}
                onRefresh={() => { void fetchTaskStatus(taskId); }}
                onRegenerate={() => { void sendChatInstruction('重跑第 3 阶段'); }}
                onContinue={() => setActiveTabStage(4)}
                sculptRequest={sculptRequest}
                onFocusCharacter={setFocusedCharacter}
              />
            ) : !taskData?.assets[activeTabStage.toString()] && !(activeTabStage === 5 && taskData?.assets["4"])
              && !(isEditorStage(activeTabStage) && (taskData?.assets["6"] || taskData?.assets["7"])) ? (
              taskData?.status === 'running' && taskData.stageProgress?.status === 'running' && sameStageTab(taskData.stageProgress.stage, activeTabStage) ? (
                <div className="stage-empty">
                  <h3>{tr('这一步正在生成')}</h3>
                  <p>{tr('产物出来后会显示在这里，下面是实时进度。')}</p>
                  <div className="stage-empty__progress">
                    <StageProgressPanel progress={taskData.stageProgress} onOpenBilling={() => setActivePortal('billing')} />
                  </div>
                </div>
              ) : (
                <div className="stage-empty">
                  <Film className="stage-empty__icon" size={64} aria-hidden="true" />
                  <h3>{tr('这一步还没有产物')}</h3>
                  <p>{taskData?.workflow?.actions.length
                    ? tr('点下面的按钮继续，或在右侧聊天框里说出你的要求。')
                    : tr('在右侧聊天框里说出你的要求，或发送「继续」推进流程。')}</p>
                  <WorkflowActions workflow={taskData?.workflow} busy={chatSending}
                    onAction={message => { void (message === '继续' ? handleNextStage() : sendChatInstruction(message)); }} />
                </div>
              )
            ) : ( // 步骤资产高保真呈现
              <div className="stage-asset-stack">
                
                <div
                  className={`glass-panel stage-asset-preview${activeTabStage === 5 ? ' stage-asset-preview--visual' : ''}`}
                  role="region"
                  aria-label={tr('Stage {0} 阶段资产预览', [activeTabStage])}
                >
                  {!isEditorStage(activeTabStage) && (
                    <div className="stage-preview-head">
                      <span className="stage-preview-head__icon"><Monitor size={16} /></span>
                      <span className="stage-preview-head__title">{tr('Stage {0} 阶段资产预览', [activeTabStage])}</span>
                    </div>
                  )}

                  {/* 5: 视觉总监生成 */}
                  {activeTabStage === 5 && (
                    <Suspense fallback={<StageFallback />}>
                      <StageFivePreview
                        asset={taskData.assets["5"]}
                        videoModel={taskData.config.videoModel || config.videoModel}
                        imageModel={taskData.config.imageModel || config.imageModel}
                        taskId={taskId}
                        episodes={episodeMetaOf(taskData.assets)}
                        refreshKey={`${taskData.currentStage}:${taskData.status}`}
                        onRerun={() => { void sendChatInstruction('重跑第 5 阶段'); }}
                        onVideoModelChange={(model: string) => {
                          setConfig(current => ({ ...current, videoModel: model }));
                          setTaskData(current => (current ? { ...current, config: { ...current.config, videoModel: model } } : current));
                        }}
                      />
                    </Suspense>
                  )}

                  {/* 6–7: 剪辑合成师 —— 声音与成片一页：原声优先、配乐、基础设定、成片版本与重新合成 */}
                  {isEditorStage(activeTabStage) && (
                    <>
                      {taskData.status === 'running' && taskData.stageProgress?.status === 'running' && isEditorStage(taskData.stageProgress.stage) && (
                        <div className="stage-empty__progress">
                          <StageProgressPanel progress={taskData.stageProgress} onOpenBilling={() => setActivePortal('billing')} />
                        </div>
                      )}
                      <Suspense fallback={<StageFallback />}>
                        <PostProductionStudio
                          taskId={taskId}
                          filmUrl={taskData.assets["7"] ? (taskData.videoUrl || taskData.assets["7"]?.final_video_url) : null}
                          // 同一路径重新合成后地址不变：带上合成时间，播放器才会换成新片
                          filmKey={String(taskData.assets["7"]?.rendered_at ?? taskData.assets["7"]?.timeline_revision ?? '')}
                          episode={taskData.assets["7"]?.episode ?? taskData.assets["6"]?.episode ?? null}
                          sound={taskData.assets["6"] ?? null}
                          audioModel={taskData.config.ttsModel || config.ttsModel}
                          refreshKey={`${taskData.currentStage}:${taskData.status}:${taskData.stageProgress?.stage ?? ''}`}
                          running={taskData.status === 'running'}
                          voiceRerender={filmsNeedingVoiceRender(taskData.assets as Record<string, unknown>)}
                          onRegenerateSound={() => { void sendChatInstruction('重跑第 6 阶段'); }}
                          onCompose={() => { void handleNextStage(); }}
                          onRendered={() => { void fetchTaskStatus(taskId); }}
                        />
                      </Suspense>
                    </>
                  )}

                  {/* 8: 宣发 Agent */}
                  {activeTabStage === 8 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div className="glass-panel" style={{ background: 'var(--surface)', padding: '12px' }}>
                        <span style={{ color: 'var(--neon-cyan)', fontSize: '0.8rem', display: 'block', marginBottom: '4px' }}>{tr('宣发大字标题')}</span>
                        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                          {(() => {
                            const titleMatch = taskData.prContent?.match(/🔥 抖音爆款大字标题：([^\n]+)/);
                            return titleMatch ? titleMatch[1] : taskData.config.titleSuggestion;
                          })()}
                        </span>
                      </div>
                      <div className="glass-panel" style={{ background: 'var(--surface)', padding: '12px' }}>
                        <span style={{ color: 'var(--neon-cyan)', fontSize: '0.8rem', display: 'block', marginBottom: '4px' }}>{tr('引流文案')}</span>
                        <p style={{ fontSize: '0.8rem', lineHeight: '1.4' }}>
                          {(() => {
                            const bodyMatch = taskData.prContent?.match(/📌 黄金引流文案：‘([^’]+)’/);
                            return bodyMatch ? bodyMatch[1] : (taskData.prContent || tr('暂无文案'));
                          })()}
                        </p>
                      </div>
                      <div style={{ fontSize: '0.85rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>{tr('短发布链接:')} </span>
                        <a href={taskData.shortLink} target="_blank" rel="noreferrer" style={{ color: 'var(--neon-cyan)' }}>{taskData.shortLink}</a>
                      </div>
                      {/* 分享至社媒：选平台，准备各平台上架物料（不自动发布） */}
                      {taskId && <Suspense fallback={<StageFallback />}><PublishPanel taskId={taskId} /></Suspense>}
                      {/* 自动获客：已发布作品的评论与私信 → 线索 → 由人确认的回复 → 跟进 */}
                      {taskId && <Suspense fallback={<StageFallback />}><AcquisitionPanel taskId={taskId} /></Suspense>}
                    </div>
                  )}

                  {/* 统一卡片底部推进/下一步按钮栏 */}
                  {taskData && (
                    <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid rgba(var(--accent-rgb), 0.11)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      {activeTabStage > 1 ? (
                        <button 
                          type="button"
                          onClick={() => setActiveTabStage(previousStageTab(activeTabStage))}
                          className="capsule-btn"
                          style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                        >
                          {tr('← 上一步资产')}
                        </button>
                      ) : <div />}

                      <div style={{ display: 'flex', gap: '10px' }}>
                        {nextStageTab(activeTabStage) <= taskData.currentStage ? (
                          <button 
                            type="button"
                            onClick={() => setActiveTabStage(nextStageTab(activeTabStage))}
                            className="capsule-btn"
                            style={{ borderColor: 'var(--neon-cyan)', color: 'var(--neon-cyan)', fontSize: '0.75rem', padding: '5px 12px' }}
                          >
                            {tr('查看下一步资产 →')}
                          </button>
                        ) : <WorkflowActions workflow={taskData.workflow} busy={chatSending}
                          onAction={message => { void (message === '继续' ? handleNextStage() : sendChatInstruction(message)); }} />}
                      </div>
                    </div>
                  )}

                </div>

                {/* 质检监控底栏 */}
                <section className="glass-panel qc-panel" aria-label={tr('质检报告')}>
                  <header className="qc-panel__head">
                    <span className="qc-panel__badge">QC</span>
                    <span>{tr('100+项质检校验（一致性检查清单）一致性 Hooks 报告')}</span>
                  </header>
                  <div className="qc-panel__body">
                    {stageLog(taskData.logs, activeTabStage)
                      ? <MarkdownDocument source={stageLog(taskData.logs, activeTabStage)} ariaLabel={tr('质检报告')} />
                      : <p className="qc-panel__empty">{tr('本阶段的质检报告生成后会显示在这里。')}</p>}
                  </div>
                </section>

              </div>

            )}
            </Suspense>

          </div>

          <WorkbenchResizeHandle
            containerRef={workbenchRef}
            sidebarRef={chatSidebarRef}
            sidebarWidth={chatSidebarWidth}
            onResize={setChatSidebarWidth}
          />

          {/* 右侧：对话与工作流控制侧边栏 (30% 宽) (截图 3) */}
          <div id="workbench-chat-sidebar" ref={chatSidebarRef} className="chat-sidebar">
            
            {/* 顶栏 */}
            <div className="chat-sidebar__header">
              <span>
                <Bot aria-hidden="true" />
                {NOVARA_AGENT_NAME}
              </span>
              <button 
                onClick={() => {
                  setTaskId('');
                  setTaskData(null);
                  setErrorMessage('');
                  // 没发出去的半句话属于这个项目，不带到下一个项目的输入框里。
                  setChatInput('');
                }}
                aria-label={tr('关闭项目工作台')}
              >
                <X size={18} />
              </button>
            </div>

            {/* 对话消息流区域 */}
            <ChatHistory key={taskId}>
              {chatMessages.map(msg => (
                <div key={msg.id} className={`chat-bubble ${msg.sender}`}>
                  
                  {/* AI 消息加上 Novara 标志和交互按钮 */}
                  {msg.sender === 'ai' ? (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.088)', paddingBottom: '4px' }}>
                        <span className="chat-agent-badge">{NOVARA_AGENT_NAME}</span>
                      </div>
                      
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                      {msg.cards?.map((card: ChatCard, index: number) => (
                        <ChatCardView
                          key={`${msg.id}:card:${index}`}
                          card={card}
                          // 提议只有用户最后一句话之后的还能确认。
                          busy={chatSending || cardBusy || (card.kind === 'proposal' && !openReplyIds.has(msg.id))}
                          onSend={message => { void sendChatInstruction(message); }}
                          onOpenCharacter={openCharacterFromCard}
                          onOpenStage={openStageFromCard}
                          onUndoStage={undoStageFromCard}
                          onUndoFace={undoFaceFromCard}
                        />
                      ))}
                    </div>
                  ) : (
                    <div>{msg.text}</div>
                  )}

                </div>
              ))}

              {/* 阶段执行实时进度卡：调用过程 + 滚动百分比 */}
              {taskData?.stageProgress && taskData.stageProgress.status === 'running' && taskData.status === 'running' && (
                <div className="chat-bubble ai">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.088)', paddingBottom: '4px' }}>
                    <span className="chat-agent-badge">{NOVARA_AGENT_NAME}</span>
                    <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{tr('正在执行 · 实时调用过程')}</span>
                  </div>
                  <StageProgressPanel progress={taskData.stageProgress} onOpenBilling={() => setActivePortal('billing')} />
                </div>
              )}
            </ChatHistory>

            {/* 对话底部输入框 */}
            <div className="chat-sidebar__composer">

              {/* 项目内的失败（发送、状态同步、分集）就地说明，不留到回大厅才看见 */}
              {errorMessage && (
                <div className="error-banner chat-sidebar__error" role="alert">
                  <span>{errorMessage}</span>
                  <button type="button" aria-label={tr('关闭提示')} title={tr('关闭提示')} onClick={() => setErrorMessage('')}>
                    <X size={14} aria-hidden="true" />
                  </button>
                </div>
              )}

              {/* 侧边栏 Skill 选择气泡弹窗 */}
              {activePopover === 'sidebarSkill' && (
                <div className="popover-window" style={{ bottom: '85px', left: '16px', right: '16px', width: 'auto', zIndex: 100 }}>
                  <h4 style={{ fontSize: '0.85rem', marginBottom: '8px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.132)', paddingBottom: '6px' }}>{tr('内置超级 Skills')}</h4>
                  <div 
                    onClick={() => {
                      updateConfigAndSync({ shotStyle: 'cinematic', directorStyle: 'cyberpunk' });
                      setActivePopover('none');
                    }}
                    className={`model-list-item ${config.shotStyle === 'cinematic' ? 'selected' : ''}`}
                  >
                    <div><strong>{tr('AI 短剧一站式生成')}</strong></div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{tr('36运镜及100+自检')}</span>
                  </div>
                  <div 
                    onClick={() => {
                      updateConfigAndSync({ shotStyle: 'standard', directorStyle: 'realistic' });
                      setActivePopover('none');
                    }}
                    className={`model-list-item ${config.shotStyle === 'standard' ? 'selected' : ''}`}
                  >
                    <div><strong>{tr('普通分镜短片生成')}</strong></div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{tr('经典正反打对话')}</span>
                  </div>

                  {importedSkills.length > 0 && (
                    <>
                      <h4 style={{ fontSize: '0.85rem', marginTop: '12px', marginBottom: '8px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.132)', paddingBottom: '6px' }}>{tr('导入外部 Skills')}</h4>
                      {importedSkills.map(s => (
                        <div 
                          key={s.name}
                          onClick={() => {
                            updateConfigAndSync({ shotStyle: s.name });
                            setActivePopover('none');
                          }}
                          className={`model-list-item ${config.shotStyle === s.name ? 'selected' : ''}`}
                          style={{ position: 'relative', paddingRight: '32px' }}
                        >
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteSkill(s.name);
                            }}
                            style={{
                              position: 'absolute',
                              top: '50%',
                              right: '8px',
                              transform: 'translateY(-50%)',
                              background: 'transparent',
                              border: 'none',
                              color: 'rgba(var(--accent-rgb), 0.88)',
                              cursor: 'pointer',
                              padding: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              zIndex: 10
                            }}
                            title={tr('物理删除该技能包')}
                          >
                            <X size={12} />
                          </button>
                          <div><strong>{s.name}</strong> <span style={{ fontSize: '0.65rem', padding: '1px 4px', background: 'var(--neon-green)', color: 'var(--on-accent)', borderRadius: '4px', marginLeft: '4px', fontWeight: 'bold' }}>{tr('已导入')}</span></div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{s.description}</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button 
                  type="button"
                  className={`capsule-btn ${showModelConfiguration ? 'active' : ''}`}
                  style={{ padding: '4px 10px', fontSize: '0.7rem' }}
                  onClick={() => { setActivePopover('none'); setShowModelConfiguration(true); }}
                >
                  {tr('模型: {0}', [hasEnabledGlobalModel ? tr('已配置') : tr('未配置')])}
                </button>
                <button 
                  type="button"
                  className={`capsule-btn ${showProjectSkillManager ? 'active' : ''}`}
                  style={{ padding: '4px 10px', fontSize: '0.7rem' }}
                  onClick={() => { setActivePopover('none'); setShowProjectSkillManager(true); }}
                >
                  {tr('Skill: 项目管理')}
                </button>
              </div>

              <ChatComposer taskId={taskId} value={chatInput} busy={chatSending} onChange={setChatInput}
                onSend={message => { void sendChatInstruction(message); }} />
            </div>

          </div>

        </div>
      )}

      {taskId && projectOverlay && (
        <Suspense fallback={null}>
          {projectOverlay === 'canvas' && <CanvasWorkspace taskId={taskId} onClose={() => setProjectOverlay(null)} />}
          {projectOverlay === 'interactive' && <InteractiveStoryWorkspace taskId={taskId} onClose={() => setProjectOverlay(null)} onOpenCanvas={() => setProjectOverlay('canvas')} />}
          {projectOverlay === 'tasks' && <TaskCenter taskId={taskId} onClose={() => setProjectOverlay(null)} />}
          {projectOverlay === 'memory' && <ProjectMemory taskId={taskId} onClose={() => setProjectOverlay(null)} />}
        </Suspense>
      )}

      {showModelConfiguration && <Suspense fallback={null}><ModelConfigurationCenter
        open={showModelConfiguration}
        canManage={hasPermission(currentUser, 'model_config:manage')}
        mustChangePassword={currentUser?.must_change_password}
        onClose={() => { setShowModelConfiguration(false); void refreshModelConfigurationStatus(); }}
        onConfigurationChange={() => { void refreshModelConfigurationStatus(); }}
        onSelect={(category: ModelCategory, modelId: string) => {
          const configKey = ({
            text: 'llmModel', image: 'imageModel', video: 'videoModel', audio: 'ttsModel',
          } as const)[category];
          if (taskId) updateConfigAndSync({ [configKey]: modelId });
          else setConfig(current => ({ ...current, [configKey]: modelId }));
          setShowModelConfiguration(false);
        }}
      /></Suspense>}

      {showProjectSkillManager && <Suspense fallback={null}><ProjectSkillManager
        open={showProjectSkillManager}
        canManage={hasPermission(currentUser, 'skill:manage')}
        mustChangePassword={currentUser?.must_change_password}
        onClose={() => setShowProjectSkillManager(false)}
      /></Suspense>}

      {/* 磨砂玻璃 导入外部 Skill 弹窗 */}
      {showImportSkillModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(var(--shadow-rgb), 0.358)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center', zIndex: 99999 }}>
          <div className="glass-panel" style={{ width: '500px', padding: '26px', position: 'relative', border: '1px solid rgba(var(--accent-rgb), 0.25)', boxShadow: '0 0 35px rgba(var(--accent-rgb), 0.2)' }}>
            <button 
              onClick={() => setShowImportSkillModal(false)} 
              style={{ position: 'absolute', top: '16px', right: '16px', background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
            >
              <X size={18} />
            </button>

            <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '20px', color: 'var(--neon-cyan)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              {tr('🔌 导入外部 Skill 技能包')}
            </h3>

            {/* 标签切换 */}
            <div style={{ display: 'flex', background: 'rgba(var(--accent-rgb), 0.088)', padding: '4px', borderRadius: '8px', marginBottom: '20px', border: '1px solid rgba(var(--accent-rgb), 0.11)' }}>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'github' ? 'active' : ''}`}
                onClick={() => setImportSkillType('github')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                {tr('GitHub 仓库')}
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'clawhub' ? 'active' : ''}`}
                onClick={() => setImportSkillType('clawhub')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                {tr('Clawhub 库')}
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'npx' ? 'active' : ''}`}
                onClick={() => setImportSkillType('npx')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                {tr('NPX 安装')}
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'zip' ? 'active' : ''}`}
                onClick={() => setImportSkillType('zip')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                {tr('ZIP 上传')}
              </button>
            </div>

            {/* 表单渲染 */}
            <div style={{ marginBottom: '24px' }}>
              {(importSkillType === 'github' || importSkillType === 'clawhub') && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>
                    {importSkillType === 'github' ? tr('GitHub 仓库 URL') : tr('Clawhub 库 URL')}
                  </label>
                  <input 
                    type="text" 
                    placeholder="https://github.com/Shanyin-ai/shanyin-screenwriting-master.git"
                    value={importSkillUrl}
                    onChange={e => setImportSkillUrl(e.target.value)}
                    style={{ width: '100%', padding: '10px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.9rem' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px' }}>
                    {tr('系统会自动克隆该技能包项目，读取其内部配置规范并在大厅中加载。')}
                  </p>
                </div>
              )}

              {importSkillType === 'npx' && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>{tr('NPX 包名')}</label>
                  <input 
                    type="text" 
                    placeholder={tr('例如：create-vite-app')}
                    value={importSkillPackage}
                    onChange={e => setImportSkillPackage(e.target.value)}
                    style={{ width: '100%', padding: '10px', background: 'rgba(var(--shadow-rgb), 0.165)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.9rem' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px' }}>
                    {tr('系统将在后台通过 `npx -y` 载入并安装指定的包。')}
                  </p>
                </div>
              )}

              {importSkillType === 'zip' && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>{tr('本地 ZIP 技能包')}</label>
                  <div 
                    style={{ 
                      border: '1px dashed rgba(var(--accent-rgb), 0.4)', 
                      borderRadius: '12px', 
                      padding: '30px 20px', 
                      textAlign: 'center', 
                      background: 'rgba(var(--shadow-rgb), 0.11)',
                      cursor: 'pointer',
                      transition: 'all 0.3s ease'
                    }}
                    onClick={() => document.getElementById('zip-file-input2')?.click()}
                  >
                    <input 
                      type="file" 
                      id="zip-file-input2"
                      accept=".zip"
                      style={{ display: 'none' }}
                      onChange={e => {
                        const files = e.target.files;
                        if (files && files.length > 0) {
                          setImportSkillFile(files[0]);
                        }
                      }}
                    />
                    <div style={{ fontSize: '2.5rem', marginBottom: '10px' }}>📦</div>
                    <span style={{ fontSize: '0.85rem', display: 'block', color: importSkillFile ? 'var(--neon-green)' : 'var(--surface-2)' }}>
                      {importSkillFile ? tr('已选择: {0} ({1} KB)', [importSkillFile.name, Math.round(importSkillFile.size / 1024)]) : tr('点击选择或拖拽本地 ZIP 压缩文件上传')}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* 提交/取消 */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
              <button 
                onClick={() => setShowImportSkillModal(false)} 
                className="capsule-btn" 
                style={{ padding: '8px 16px' }}
              >
                {tr('取消')}
              </button>
              <button 
                onClick={handleImportSkill} 
                className="cyber-btn" 
                style={{ padding: '8px 20px', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', color: 'var(--ink)', fontWeight: 600 }}
              >
                {tr('立即导入技能包')}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
