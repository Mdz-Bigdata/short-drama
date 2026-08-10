import { useState, useEffect, useRef } from 'react';
import { 
  Film, Play, Pause, ChevronRight, 
  UserCheck, ClipboardList, Video, Music, Share2, 
  Layers, HardDrive, Cpu, Monitor, Sliders, 
  Send, X, ArrowUp, Folder, ArrowRight, User,
  Upload
} from 'lucide-react';
import { type TaskConfig, type TaskResponse } from './types';
import { CapabilityCenter } from './features/platform/CapabilityCenter';
import { ElementLibraryPage, type ElementKind } from './features/elements/ElementLibraryPage';
import { UserCenterPage } from './features/account/UserCenterPage';
import { BillingCenterPage } from './features/billing/BillingCenterPage';
import { ModelConfigurationCenter, type ModelCategory } from './features/models/ModelConfigurationCenter';
import { ProjectSkillManager } from './features/skills/ProjectSkillManager';

// 定义 Agent 节点常数
const AGENT_STAGES = [
  { id: 1, name: '总导演 (Executive Director)', icon: Film, desc: '确立主旋律与故事爽点大纲' },
  { id: 2, name: '专业编剧 (Writer Agent)', icon: ClipboardList, desc: '撰写双轨节奏剧本与口语化台词' },
  { id: 3, name: '角色设计师 (Character Designer)', icon: UserCheck, desc: '设计人物五维 DNA 档案' },
  { id: 4, name: '专业分镜师 (Storyboard Artist)', icon: Sliders, desc: '拆解 15 秒切片与 36 运镜系统' },
  { id: 5, name: '视觉总监 (Visual Director)', icon: Video, desc: '调用文生图/图生视频及多帧校验' },
  { id: 6, name: '音频总监 (Audio Director)', icon: Music, desc: '合成多角色 TTS 配音及音画对齐' },
  { id: 7, name: '合成发布 (Composer & Publisher)', icon: Layers, desc: '视听合流压制与内置特效字幕' },
  { id: 8, name: '宣发 Agent (PR Agent)', icon: Share2, desc: '生成引流封面大字及高完播率文案' },
];
interface ChatMessage {
  id: string;
  sender: 'user' | 'ai';
  text: string;
  stage?: number;
  isSystem?: boolean;
}

interface CurrentUser {
  user_id: string;
  username: string;
  email?: string | null;
  phone?: string | null;
  role?: 'admin' | 'editor' | 'user';
  status?: 'active' | 'suspended';
  must_change_password?: boolean;
}

interface EpisodeItem {
  index: number;
  title: string;
  status: 'idle' | 'running' | 'completed' | 'failed';
  videoUrl?: string | null;
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

interface CharacterCard {
  name: string;
  role?: string;
  desc?: string;
  sheet?: string;
  views?: Array<{ view: string; image_url: string }>;
}

interface ProductionShot {
  shot_id?: number;
  size?: string;
  motion?: string;
  desc?: string;
  image_url?: string;
  video_url?: string;
}

let messageSequence = 0;
const nextMessageId = () => `message-${++messageSequence}`;

export default function App() {
  // 用户身份认证状态
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authChecked, setAuthChecked] = useState<boolean>(false);
  const [showUserMenu, setShowUserMenu] = useState<boolean>(false);
  const [activePortal, setActivePortal] = useState<'home' | 'user' | 'billing' | ElementKind>('home');

  // 统一的网络请求拦截器，确保附带 HttpOnly Cookie 并在 401 时拦截至登录态
  const apiFetch = async (url: string, options: RequestInit = {}) => {
    options.credentials = 'include';
    const response = await fetch(url, options);
    if (response.status === 401) {
      setCurrentUser(null);
      setAuthChecked(true);
      throw new Error('未登录或登录已过期');
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

  // 发送验证码并启动 60 秒倒计时；生产环境永不回显验证码。
  const handleSendVerificationCode = async () => {
    const loginId = authForm.loginId.trim();
    if (!loginId) {
      setAuthError('请输入邮箱或手机号');
      return;
    }
    setAuthError('');
    setAuthSuccess('');
    
    try {
      const res = await fetch('http://localhost:8000/api/auth/send_code', {
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
          ? `验证码发送成功（本地开发码：${developmentCode}）`
          : '验证码发送成功，请查看短信或邮件。');
        setCodeCountdown(60);
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
        setAuthError(err.detail || '验证码发送失败');
      }
    } catch {
      setAuthError('无法连接至后端，请先确保后端运行中。');
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
          setAuthError('请输入账号和密码');
          return;
        }
        const res = await fetch('http://localhost:8000/api/auth/login_password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ login_id: authForm.loginId, password: authForm.password }),
          credentials: 'include'
        });
        
        if (res.ok) {
          const data = await res.json();
          setCurrentUser(data.user);
          if (data.user.must_change_password) setActivePortal('user');
          setAuthForm({ loginId: '', password: '', email: '', phone: '', code: '' });
          fetchHistoryTasks();
          fetchImportedSkills();
        } else {
          const err = await res.json();
          setAuthError(err.detail || '登录失败，账号或密码错误');
        }
      } else if (authTab === 'login_code') {
        if (!authForm.loginId.trim() || !authForm.code.trim()) {
          setAuthError('请输入手机/邮箱及验证码');
          return;
        }
        const res = await fetch('http://localhost:8000/api/auth/login_code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ login_id: authForm.loginId, code: authForm.code }),
          credentials: 'include'
        });
        
        if (res.ok) {
          const data = await res.json();
          setCurrentUser(data.user);
          if (data.user.must_change_password) setActivePortal('user');
          setAuthForm({ loginId: '', password: '', email: '', phone: '', code: '' });
          setMockVerificationCode('');
          fetchHistoryTasks();
          fetchImportedSkills();
        } else {
          const err = await res.json();
          setAuthError(err.detail || '登录失败，验证码错误或已失效');
        }
      } else if (authTab === 'register') {
        if (!authForm.email.trim() && !authForm.phone.trim()) {
          setAuthError('邮箱与手机号至少需填写一项');
          return;
        }
        if (!authForm.password || authForm.password.length < 10) {
          setAuthError('密码长度不能少于 10 位');
          return;
        }
        
        const res = await fetch('http://localhost:8000/api/auth/register', {
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
          setAuthSuccess('恭喜您注册成功！已自动为您填入登录项，请输入密码进行登录。');
          setAuthTab('login_pwd');
          setAuthForm(prev => ({
            ...prev,
            loginId: authForm.email.trim() || authForm.phone.trim() || ''
          }));
        } else {
          const err = await res.json();
          setAuthError(err.detail || '注册失败，手机号或邮箱可能已被占用');
        }
      }
    } catch {
      setAuthError('连接服务器失败，请确认后端已正常启动。');
    }
  };

  // 登出系统并清理状态
  const handleLogout = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/auth/logout', {
        method: 'POST',
        credentials: 'include'
      });
      if (res.ok) {
        setCurrentUser(null);
        setTaskId('');
        setTaskData(null);
      }
    } catch (e) {
      console.error('退出登录失败', e);
    }
  };

  // 配置状态
  const [config, setConfig] = useState<TaskConfig>({
    titleSuggestion: '',
    directorStyle: 'cyberpunk',
    shotStyle: 'cinematic',
    llmModel: '',
    imageModel: '',
    videoModel: '',
    ttsModel: '',
    oneClick: false,
    episodeCount: 3
  });

  // 界面交互状态
  const [taskId, setTaskId] = useState<string>('');
  const [taskData, setTaskData] = useState<TaskResponse | null>(null);
  const taskDataRef = useRef<TaskResponse | null>(null);
  const [uploadedScript, setUploadedScript] = useState<File | null>(null);
  const [scriptContent, setScriptContent] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeTabStage, setActiveTabStage] = useState<number>(1);
  const [historyTasks, setHistoryTasks] = useState<TaskResponse[]>([]);
  const [isPolling, setIsPolling] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string>('');
  
  // 气泡控制
  const [activePopover, setActivePopover] = useState<'none' | 'skill' | 'element' | 'sidebarSkill'>('none');
  const [showModelConfiguration, setShowModelConfiguration] = useState(false);
  const [showProjectSkillManager, setShowProjectSkillManager] = useState(false);
  
  // 对话流状态
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState<string>('');

  // 新项目创建模态窗及 Skills 区状态
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [newProjectName, setNewProjectName] = useState<string>('');
  const [newProjectDirectorStyle, setNewProjectDirectorStyle] = useState<string>('cyberpunk');
  const [newProjectShotStyle, setNewProjectShotStyle] = useState<string>('cinematic');
  const [newProjectOneClick, setNewProjectOneClick] = useState<boolean>(true); // 成片方式：true=一键成片 / false=分步引导
  const [newProjectEpisodes, setNewProjectEpisodes] = useState<number>(3); // 一次性生成的剧本集数
  const [episodes, setEpisodes] = useState<EpisodeItem[]>([]); // 分集制作清单 (逐集出片)
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
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    taskDataRef.current = taskData;
  }, [taskData]);

  // 挂载时检查一次会话登录态，成功后再拉取任务和Skills。
  useEffect(() => {
    let active = true;
    void fetch('http://localhost:8000/api/auth/session', {
      method: 'GET', credentials: 'include'
    }).then(async res => {
      if (res.ok && active) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setCurrentUser(data.user);
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
      const res = await apiFetch('http://localhost:8000/api/drama/skills');
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
        alert('请输入 Git 仓库或 Clawhub 的克隆 URL！');
        return;
      }
      formData.append('url', importSkillUrl.trim());
    } else if (importSkillType === 'npx') {
      if (!importSkillPackage.trim()) {
        alert('请输入 NPX 包名！');
        return;
      }
      formData.append('package_name', importSkillPackage.trim());
    } else if (importSkillType === 'zip') {
      if (!importSkillFile) {
        alert('请选择需要上传的本地 ZIP 技能压缩包！');
        return;
      }
      formData.append('file', importSkillFile);
    }
    
    try {
      const res = await apiFetch('http://localhost:8000/api/drama/import_skill', {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        alert(`🎉 技能包导入成功: ${data.skillName}`);
        
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
        alert(`导入失败: ${err.detail || '接口解析错误'}`);
      }
    } catch {
      alert('无法连接至后端，请先确保后端启动运行中。');
    }
  };

  // 物理删除指定已导入的 Skill 技能包
  const handleDeleteSkill = async (skillName: string) => {
    if (!window.confirm(`确定要物理删除技能包 "${skillName}" 吗？此操作不可逆！`)) {
      return;
    }
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/skills/${skillName}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        alert('技能包删除成功！');
        fetchImportedSkills();
        if (config.shotStyle === skillName) {
          updateConfigAndSync({ shotStyle: 'cinematic' });
        }
      } else {
        const err = await res.json();
        alert(`删除失败: ${err.detail || '接口错误'}`);
      }
    } catch {
      alert('删除失败，无法连接至后端。');
    }
  };

  // 物理删除指定任务记录
  const handleDeleteTask = async (targetTaskId: string) => {
    if (!window.confirm("确定要物理删除该短剧生成项目吗？该操作不可逆且将清除所有已生成视频与音频资产！")) {
      return;
    }
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${targetTaskId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        alert('该任务已成功物理删除！');
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
        alert(`删除失败: ${err.detail || '接口解析错误'}`);
      }
    } catch {
      alert('物理删除失败，无法连接至后端。');
    }
  };

  // 处理手动剧本文件上传
  const handleScriptUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setErrorMessage('');
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await apiFetch('http://localhost:8000/api/drama/parse_script', {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        setUploadedScript(file);
        setScriptContent(data.content);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || '解析剧本文件失败，请确保格式正确。');
      }
    } catch {
      setErrorMessage('无法连接至后端解析剧本，请检查服务。');
    }
  };




  // 轮询监控后台当前任务
  useEffect(() => {
    if (isPolling && taskId) {
      pollIntervalRef.current = setInterval(() => {
        fetchTaskStatus(taskId);
      }, 1500);
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    }
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [isPolling, taskId]); // eslint-disable-line react-hooks/exhaustive-deps -- polling callback reads current refs

  // 登录后在大厅定时轮询拉取所有任务 (当不在工作台内时)
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    if (currentUser && !taskId) {
      interval = setInterval(() => {
        fetchHistoryTasks();
      }, 1500);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [currentUser, taskId]); // eslint-disable-line react-hooks/exhaustive-deps -- lobby refresh follows authentication and selected task

  // 聊天自动滚动到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, taskData]);

  // 拉取历史列表
  async function fetchHistoryTasks() {
    try {
      const res = await apiFetch('http://localhost:8000/api/drama/list');
      if (res.ok) {
        const data = await res.json();
        setHistoryTasks(data);
      }
    } catch (e) {
      console.error('加载历史任务失败', e);
    }
  }

  // 拉取单条任务状态并联动更新聊天气泡
  async function fetchTaskStatus(id: string) {
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${id}/status`);
      if (res.ok) {
        const data: TaskResponse = await res.json();
        const prevStage = taskDataRef.current?.currentStage || 0;
        setTaskData(data);
        taskDataRef.current = data;
        
        // 当 stage 发生变化时，追加入 AI 的进度对话气泡
        if (data.currentStage > prevStage) {
          setActiveTabStage(data.currentStage);
          const currentStageInfo = AGENT_STAGES.find(s => s.id === data.currentStage);
          setChatMessages(prev => [
            ...prev,
            {
              id: nextMessageId(),
              sender: 'ai',
              text: `⚙️ **【${currentStageInfo?.name} 已完成】**\n\n该阶段资产已成功生成并校验完毕。您可直接在左侧看板查阅该步骤的高保真输出。`,
              stage: data.currentStage
            }
          ]);
        }

        // 状态判定
        if (data.status !== 'running') {
          setIsPolling(false);
          fetchHistoryTasks();
          if (data.status === 'completed') {
            setChatMessages(prev => [
              ...prev,
              {
                id: nextMessageId(),
                sender: 'ai',
                text: `🎉 **【短剧生成大功告成】**\n\n8大智能体已顺利完成全部工序，最终 9:16 H.264 格式高清成片及社交引爆 PR 文案已封装完毕！您现在可以点击右上角“导出”进行下载和发布。`
              }
            ]);
          } else if (data.status === 'awaiting_quality_review') {
            setChatMessages(prev => [
              ...prev,
              {
                id: `quality-review-${data.taskId}`,
                sender: 'ai',
                text: '🛡️ **【成片已生成，等待终审】**\n\n人物身份、解剖、表情、真人感、镜头连续、对白情绪与口型必须提交真实多模态或人工验收；未通过前不会标记成片完成。'
              }
            ]);
          }
        }
      }
    } catch (e) {
      console.error('获取状态失败', e);
      setIsPolling(false);
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
      ? `📖 已手动载入剧本《${uploadedScript.name}》生成短剧。${text.trim() ? `\n附加要求：${text.trim()}` : ''}`
      : titleText;
      
    // 初始化聊天流
    setChatMessages([
      { id: '1', sender: 'user', text: displayMsg },
      { id: '2', sender: 'ai', text: uploadedScript 
        ? '🎬 **【总导演 Agent 启动】**\n正在为您定调与策划您上传的剧本，请稍候...'
        : '🎬 **【总导演 Agent 启动】**\n正在为您规划短剧框架与角色 DNA，请稍候...' }
    ]);

    try {
      const res = await apiFetch('http://localhost:8000/api/drama/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskId(data.taskId);
        setTaskData(data);
        setUploadedScript(null);
        setScriptContent('');
        setActiveTabStage(1);
        setIsPolling(true);
        
        // 自动触发下一步
        const nextRes = await apiFetch(`http://localhost:8000/api/drama/${data.taskId}/next?current_stage=1`, {
          method: 'POST'
        });
        if (nextRes.ok) {
          const nextData = await nextRes.json();
          setTaskData(nextData);
          setChatMessages(prev => [
            ...prev,
            {
              id: '3',
              sender: 'ai',
              text: '⚙️ **【总导演策划已完成】**\n主旋律及角色 DNA 档案已建档。点击下方按钮即可进入 **编剧剧本创作 (Phase 2)**。',
              stage: 1
            }
          ]);
        }
        fetchHistoryTasks();
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || '创建任务失败');
      }
    } catch {
      setErrorMessage('无法连接至后端，请先在终端运行 `./start.sh` 启动系统。');
    }
  };

  // 步骤式单步生成
  const handleNextStage = async () => {
    if (!taskData) return;
    const nextStage = taskData.currentStage + 1;
    if (nextStage > 8) return;
    
    const stageInfo = AGENT_STAGES.find(s => s.id === nextStage);
    setChatMessages(prev => [
      ...prev,
      {
        id: nextMessageId(),
        sender: 'ai',
        text: `⏳ **【${stageInfo?.name} 正在生成中...】**`
      }
    ]);
    
    setTaskData({ ...taskData, status: 'running', currentStage: nextStage });
    setIsPolling(true);

    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/next?current_stage=${nextStage}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskData(data);
        setActiveTabStage(nextStage);
        fetchHistoryTasks();
      } else {
        setIsPolling(false);
      }
    } catch (e) {
      console.error(e);
      setIsPolling(false);
    }
  };

  // —— 分集制作 (item 6: 剧本一次多集，视频逐集制作) ——
  const fetchEpisodes = async (tid: string) => {
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${tid}/episodes`);
      if (res.ok) {
        const data = await res.json();
        const eps = data.episodes || [];
        setEpisodes(eps);
        // 有正在制作的集则继续轮询
        if (eps.some((episode: EpisodeItem) => episode.status === 'running')) {
          setTimeout(() => fetchEpisodes(tid), 8000);
        }
      }
    } catch (e) { console.error(e); }
  };

  const handlePlanEpisodes = async () => {
    if (!taskId) return;
    setEpisodesBusy(true);
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/episodes/plan`, { method: 'POST' });
      if (res.ok) {
        await fetchEpisodes(taskId);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || '分集失败 (请先完成阶段1-2剧本)');
      }
    } catch {
      setErrorMessage('分集请求失败');
    } finally {
      setEpisodesBusy(false);
    }
  };

  const handleProduceEpisode = async (idx: number) => {
    if (!taskId) return;
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/episodes/${idx}/produce`, { method: 'POST' });
      if (res.ok) {
        setEpisodes(prev => prev.map(e => e.index === idx ? { ...e, status: 'running' } : e));
        setTimeout(() => fetchEpisodes(taskId), 5000);
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || `第${idx}集制作启动失败`);
      }
    } catch {
      setErrorMessage(`第${idx}集制作请求失败`);
    }
  };

  // 一键生成全片
  const handleRunAll = async () => {
    if (!taskId) return;
    setIsPolling(true);
    setTaskData(prev => prev ? { ...prev, status: 'running' } : null);
    setChatMessages(prev => [
      ...prev,
      { id: nextMessageId(), sender: 'ai', text: '🚀 一键成片启动！8大智能体正在后台连续执行生成，请稍候...' }
    ]);
    try {
      await apiFetch(`http://localhost:8000/api/drama/${taskId}/run_all`, {
        method: 'POST'
      });
    } catch (e) {
      console.error(e);
      setIsPolling(false);
    }
  };

  // 暂停
  const handlePause = async () => {
    if (!taskId) return;
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/pause`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setTaskData(data);
        setIsPolling(false);
        setChatMessages(prev => [
          ...prev,
          { id: nextMessageId(), sender: 'ai', text: '⏸️ 任务已成功暂停，断点已保存。您可随时点击恢复继续。' }
        ]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // 恢复一键成片
  const handleResume = async () => {
    if (!taskId) return;
    setIsPolling(true);
    setTaskData(prev => prev ? { ...prev, status: 'running' } : null);
    setChatMessages(prev => [
      ...prev,
      { id: nextMessageId(), sender: 'ai', text: '▶️ 正在从断点恢复生成...' }
    ]);
    try {
      await apiFetch(`http://localhost:8000/api/drama/${taskId}/resume`, {
        method: 'POST'
      });
    } catch (e) {
      console.error(e);
      setIsPolling(false);
    }
  };

  // 发送对话指引微调或生成
  const sendChatInstruction = async (text: string) => {
    if (!text.trim()) return;
    setErrorMessage('');
    setChatInput('');
    
    // 添加用户发送的文本气泡
    setChatMessages(prev => [
      ...prev,
      { id: nextMessageId(), sender: 'user', text: text }
    ]);
    
    const pendingId = nextMessageId();
    setChatMessages(prev => [
      ...prev,
      { id: pendingId, sender: 'ai', text: '⚙️ **【收到您的指令】**\n正在根据您的对话指引调整并生成短剧，请稍候...' }
    ]);
    
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskData(data);
        setActiveTabStage(data.currentStage > 0 ? data.currentStage : 1);
        
        // 移除等待气泡并追加成功调整气泡
        setChatMessages(prev => {
          const filtered = prev.filter(m => m.id !== pendingId);
          const currentStageInfo = AGENT_STAGES.find(s => s.id === data.currentStage);
          return [
            ...filtered,
            {
              id: nextMessageId(),
              sender: 'ai',
              text: `✅ **【指引调整已生效】**\n\n已根据您的指示 “*${text}*” 对 **${currentStageInfo?.name || '当前阶段'}** 进行了内容重塑！您可以立即在左侧面板查阅更新后的剧作资产与 100+ 项质检 Hook 报告。`,
              stage: data.currentStage
            }
          ];
        });
        fetchHistoryTasks();
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || '发送指令失败');
        setChatMessages(prev => prev.filter(m => m.id !== pendingId));
      }
    } catch {
      setErrorMessage('发送消息失败，请检查后端网络连接。');
      setChatMessages(prev => prev.filter(m => m.id !== pendingId));
    }
  };

  // 载入已有项目
  const handleLoadTask = (task: TaskResponse) => {
    setTaskId(task.taskId);
    setTaskData(task);
    setActiveTabStage(task.currentStage > 0 ? task.currentStage : 1);
    setIsPolling(task.status === 'running');
    setEpisodes([]);
    fetchEpisodes(task.taskId); // 载入已有的分集制作清单

    // 同步配置状态，以便工作台侧边栏能够高亮匹配该项目的实际模型配置
    if (task.config) {
      setConfig({
        titleSuggestion: task.config.titleSuggestion || '',
        directorStyle: task.config.directorStyle || 'cyberpunk',
        shotStyle: task.config.shotStyle || 'cinematic',
        llmModel: task.config.llmModel || '',
        imageModel: task.config.imageModel || '',
        videoModel: task.config.videoModel || '',
        ttsModel: task.config.ttsModel || '',
        oneClick: task.config.oneClick || false,
        episodeCount: task.config.episodeCount || 3
      });
    }
    
    // 初始化已有消息
    setChatMessages([
      { id: 'init', sender: 'ai', text: `📁 已经为您加载项目: **${task.config.titleSuggestion}**。当前进度为第 ${task.currentStage}/8 步 (${task.stageName})。` }
    ]);
  };

  // 统一的配置同步方法，如果在工作台内，还会自动向后端请求更新配置以应用在下一步执行中
  const updateConfigAndSync = async (newConfig: Partial<TaskConfig>) => {
    const updated = { ...config, ...newConfig };
    setConfig(updated);
    if (taskId) {
      try {
        const res = await apiFetch(`http://localhost:8000/api/drama/${taskId}/update_config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updated)
        });
        if (res.ok) {
          const data = await res.json();
          setTaskData(data);
        }
      } catch (e) {
        console.error('同步配置到后端失败', e);
      }
    }
  };

  // 大厅项目卡片暂停操作
  const handleCardPause = async (id: string) => {
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${id}/pause`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchHistoryTasks();
      }
    } catch (e) {
      console.error('暂停任务失败', e);
    }
  };

  // 大厅项目卡片恢复一键成片操作
  const handleCardResume = async (id: string) => {
    try {
      const res = await apiFetch(`http://localhost:8000/api/drama/${id}/resume`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchHistoryTasks();
      }
    } catch (e) {
      console.error('恢复任务失败', e);
    }
  };

  // 磨砂玻璃 Modal 弹窗确认创建真实短剧项目
  const handleConfirmCreate = async () => {
    if (!newProjectName.trim()) {
      alert("请输入短剧选题名称！");
      return;
    }
    setErrorMessage('');
    setShowCreateModal(false);
    
    // 初始化工作台聊天提示
    setChatMessages([
      { id: '1', sender: 'user', text: newProjectName },
      { id: '2', sender: 'ai', text: '🎬 **【总导演 Agent 启动】**\n正在为您规划短剧框架与角色 DNA，请稍候...' }
    ]);

    const currentConfig = {
      titleSuggestion: newProjectName,
      directorStyle: newProjectDirectorStyle,
      shotStyle: newProjectShotStyle,
      llmModel: config.llmModel,
      imageModel: config.imageModel,
      videoModel: config.videoModel,
      ttsModel: config.ttsModel,
      episodeCount: newProjectEpisodes, // 一次性生成的剧本集数 (视频按集逐集制作)
      oneClick: newProjectOneClick // 由新建弹窗的「成片方式」选择决定：一键成片 / 分步引导
    };

    try {
      const res = await apiFetch('http://localhost:8000/api/drama/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      if (res.ok) {
        const data: TaskResponse = await res.json();
        setTaskId(data.taskId);
        setTaskData(data);
        setActiveTabStage(1);
        setIsPolling(true);

        if (newProjectOneClick) {
          // ⚡ 一键成片：后台连续执行全部 8 步，前端轮询进度
          await apiFetch(`http://localhost:8000/api/drama/${data.taskId}/run_all`, { method: 'POST' });
          setChatMessages(prev => [
            ...prev,
            {
              id: nextMessageId(),
              sender: 'ai',
              text: `🚀 **【一键成片启动】**\n8 大智能体正在后台连续生成《${newProjectName}》(${newProjectEpisodes} 集剧本)，请稍候，进度会实时刷新。`,
              stage: 1
            }
          ]);
        } else {
          // 🧭 分步引导：仅先生成第 1 步 (总导演)，其余由用户逐步推进/对话微调
          const nextRes = await apiFetch(`http://localhost:8000/api/drama/${data.taskId}/next?current_stage=1`, {
            method: 'POST'
          });
          if (nextRes.ok) {
            const nextData = await nextRes.json();
            setTaskData(nextData);
            setChatMessages(prev => [
              ...prev,
              {
                id: nextMessageId(),
                sender: 'ai',
                text: '⚙️ **【总导演策划已完成】**\n主旋律及角色 DNA 档案已建档。点击下方按钮即可进入 **编剧剧本创作 (Phase 2)**。',
                stage: 1
              }
            ]);
          }
        }
        fetchHistoryTasks();
        setNewProjectName(''); // 清空输入
      } else {
        const err = await res.json();
        setErrorMessage(err.detail || '创建项目失败');
      }
    } catch {
      setErrorMessage('无法连接至后端，请先确保后端运行中。');
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
          <span style={{ fontSize: '0.95rem', letterSpacing: '1px' }}>正在加载 AI 协同系统会话...</span>
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
        background: 'radial-gradient(circle at 50% -20%, #112240 0%, var(--bg-dark) 100%)',
        padding: '20px',
        position: 'relative',
        overflow: 'hidden'
      }}>
        {/* 背景动态流光感装饰球 */}
        <div style={{ position: 'absolute', width: '300px', height: '300px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(0,242,254,0.12) 0%, transparent 70%)', top: '-10%', left: '-5%', filter: 'blur(30px)' }} />
        <div style={{ position: 'absolute', width: '400px', height: '400px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(255,51,102,0.08) 0%, transparent 70%)', bottom: '-10%', right: '-5%', filter: 'blur(40px)' }} />

        {/* 仅 AUTH_EXPOSE_MOCK_CODE=1 的本地开发环境显示；生产环境无此字段。 */}
        {mockVerificationCode && (
          <div className="glass-panel" style={{
            position: 'absolute',
            top: '24px',
            right: '24px',
            border: '1px solid rgba(0, 242, 254, 0.4)',
            boxShadow: '0 0 15px rgba(0, 242, 254, 0.2)',
            zIndex: 99999,
            padding: '12px 18px',
            borderRadius: '12px',
            background: 'rgba(18, 28, 48, 0.95)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            animation: 'ping 1.5s ease-in-out infinite alternate'
          }}>
            <span style={{ color: 'var(--neon-cyan)', fontSize: '0.85rem', fontWeight: 600 }}>💡 [演示通道] 验证码为:</span>
            <strong style={{ fontSize: '1.05rem', color: '#fff', letterSpacing: '2px', fontFamily: 'monospace' }}>{mockVerificationCode}</strong>
          </div>
        )}

        <div className="glass-panel" style={{
          width: '100%',
          maxWidth: '440px',
          padding: '32px',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
          background: 'rgba(13, 20, 35, 0.55)',
          backdropFilter: 'blur(30px)',
          WebkitBackdropFilter: 'blur(30px)',
          borderRadius: '24px',
          position: 'relative',
          zIndex: 10
        }}>
          {/* 系统头部 Logo 与名称 */}
          <div style={{ textAlign: 'center', marginBottom: '28px' }}>
            <h2 style={{ fontSize: '1.8rem', fontWeight: 700, letterSpacing: '2px', background: 'linear-gradient(135deg, #00f2fe, #0072ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', marginBottom: '8px' }}>
              Novara 1.0
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>工业级 AI 短剧多智能体协同成片平台</p>
          </div>

          {/* 表单切换 Tab 栏 */}
          <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: '24px', paddingBottom: '2px' }}>
            <button
              onClick={() => { setAuthTab('login_pwd'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'login_pwd' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              密码登录
            </button>
            <button
              onClick={() => { setAuthTab('login_code'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'login_code' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              验证码登录
            </button>
            <button
              onClick={() => { setAuthTab('register'); setAuthError(''); setAuthSuccess(''); }}
              className={`popover-tab-btn ${authTab === 'register' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center', fontSize: '0.85rem' }}
            >
              快速注册
            </button>
          </div>

          {/* 统一提示信息反馈 */}
          {authError && (
            <div style={{ background: 'rgba(239, 68, 68, 0.12)', border: '1px solid var(--neon-red)', color: '#fca5a5', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
              ⚠️ {authError}
            </div>
          )}
          {authSuccess && (
            <div style={{ background: 'rgba(16, 185, 129, 0.12)', border: '1px solid var(--neon-green)', color: '#a7f3d0', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
              ✓ {authSuccess}
            </div>
          )}

          {/* 登录注册表单主体 */}
          <form onSubmit={handleAuthSubmit}>
            {authTab === 'login_pwd' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>账号 (手机号或邮箱)</label>
                  <input
                    type="text"
                    required
                    placeholder="请输入绑定的手机号或邮箱"
                    value={authForm.loginId}
                    onChange={e => setAuthForm({ ...authForm, loginId: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>密码</label>
                  <input
                    type="password"
                    required
                    placeholder="请输入您的密码"
                    value={authForm.password}
                    onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
              </div>
            )}

            {authTab === 'login_code' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>手机号或邮箱</label>
                  <input
                    type="text"
                    required
                    placeholder="请输入绑定的手机号或邮箱"
                    value={authForm.loginId}
                    onChange={e => setAuthForm({ ...authForm, loginId: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>6位验证码</label>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <input
                      type="text"
                      required
                      maxLength={6}
                      placeholder="验证码"
                      value={authForm.code}
                      onChange={e => setAuthForm({ ...authForm, code: e.target.value })}
                      style={{ flex: 1, padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none', textAlign: 'center', letterSpacing: '2px', fontFamily: 'monospace' }}
                    />
                    <button
                      type="button"
                      disabled={codeCountdown > 0}
                      onClick={handleSendVerificationCode}
                      className="capsule-btn"
                      style={{ padding: '0 16px', fontSize: '0.75rem', whiteSpace: 'nowrap', minWidth: '110px', justifyContent: 'center' }}
                    >
                      {codeCountdown > 0 ? `${codeCountdown}s 重发` : '获取验证码'}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {authTab === 'register' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>注册邮箱 (选填)</label>
                  <input
                    type="email"
                    placeholder="请输入注册邮箱"
                    value={authForm.email}
                    onChange={e => setAuthForm({ ...authForm, email: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>注册手机号 (选填)</label>
                  <input
                    type="text"
                    placeholder="请输入注册手机号"
                    value={authForm.phone}
                    onChange={e => setAuthForm({ ...authForm, phone: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '6px' }}>登录密码</label>
                  <input
                    type="password"
                    required
                    placeholder="设置登录密码，不少于10位"
                    value={authForm.password}
                    onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                    style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem', outline: 'none' }}
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
                background: 'linear-gradient(135deg, #00f2fe, #0072ff)',
                color: '#fff',
                fontWeight: 600,
                fontSize: '0.9rem',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                boxShadow: '0 4px 15px rgba(0, 242, 254, 0.15)'
              }}
            >
              {authTab === 'register' ? '提交注册' : '立即登录'}
            </button>
          </form>

          {/* 安全提示 */}
          <div style={{ marginTop: '20px', borderTop: '1px solid rgba(255,255,255,0.04)', paddingTop: '14px', fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div>🔐 本地默认管理员：<strong>admin@short-drama</strong></div>
            <div>登录配置位于后端 `.env`；首次登录必须修改。生产环境禁止使用开发默认密码。</div>
          </div>
        </div>
      </div>
    );
  }

  if (currentUser && activePortal === 'user') {
    return <UserCenterPage onBack={() => setActivePortal('home')} onUserChange={setCurrentUser} />;
  }

  if (currentUser && activePortal === 'billing') {
    return <BillingCenterPage onBack={() => setActivePortal('home')} />;
  }

  if (currentUser && ['actor', 'prop', 'scene', 'effect'].includes(activePortal)) {
    return <ElementLibraryPage initialKind={activePortal as ElementKind} onBack={() => setActivePortal('home')} />;
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      


      {/* 1. 未进入项目：主配置大厅 (截图 1, 2) */}
      {taskId === '' ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '0 24px' }}>
          
          {/* 右上角快捷导航 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '16px', padding: '20px 0', alignItems: 'center' }}>
            <span style={{ background: 'rgba(255,255,255,0.06)', padding: '5px 14px', borderRadius: '20px', fontSize: '0.8rem', border: '1px solid var(--border-color)', color: '#fbc02d', display: 'flex', alignItems: 'center', gap: '6px' }}>
              🏆 世界杯挑战赛让「灵感上场」
            </span>
            <span style={{ background: 'rgba(255,255,255,0.06)', padding: '5px 14px', borderRadius: '20px', fontSize: '0.8rem', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              ⚡ 132 Free
            </span>
            <div 
              style={{ position: 'relative' }}
              onMouseEnter={() => setShowUserMenu(true)}
              onMouseLeave={() => setShowUserMenu(false)}
            >
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'linear-gradient(135deg, #00f2fe, #4facfe)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
                <User size={16} color="#000" />
              </div>
              
              {showUserMenu && currentUser && (
                <div className="glass-panel" style={{
                  position: 'absolute',
                  top: '36px',
                  right: 0,
                  width: '180px',
                  padding: '12px',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  boxShadow: '0 10px 20px rgba(0,0,0,0.3)',
                  zIndex: 1000,
                  background: 'var(--bg-popover)',
                  borderRadius: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px'
                }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '6px', color: 'var(--neon-cyan)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'left' }}>
                    👤 {currentUser.username || '当前用户'}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'left' }}>
                    {currentUser.email || currentUser.phone || '未绑定账号'}
                  </div>
                  <button className="account-menu-action" onClick={() => { setActivePortal('user'); setShowUserMenu(false); }}>
                    用户中心
                  </button>
                  <button className="account-menu-action" onClick={() => { setActivePortal('billing'); setShowUserMenu(false); }}>
                    会员与支付
                  </button>
                  <button
                    onClick={handleLogout}
                    style={{
                      background: 'rgba(239, 68, 68, 0.1)',
                      border: '1px solid rgba(239, 68, 68, 0.2)',
                      color: 'var(--neon-red)',
                      fontSize: '0.75rem',
                      padding: '4px 8px',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      width: '100%',
                      fontWeight: 600,
                      marginTop: '4px'
                    }}
                  >
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 标题 */}
          <div style={{ textAlign: 'center', marginTop: '60px', marginBottom: '40px' }}>
            <h2 style={{ fontSize: '2.8rem', fontWeight: 300, letterSpacing: '3px', marginBottom: '12px' }}>
              Novara 1.0 - 你的专属AI视频创作Agent
            </h2>
            <p style={{ color: 'var(--text-dim)', fontSize: '1.1rem', fontWeight: 300 }}>
              把品味和习惯写进Skill，让精力回归创意
            </p>
          </div>

          {/* 核心创意输入框 (带气泡) */}
          <div style={{ position: 'relative', width: '100%' }}>
            {errorMessage && (
              <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', color: '#fca5a5', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.9rem' }}>
                ⚠️ {errorMessage}
              </div>
            )}
            <div className="creative-input-card">
              <textarea 
                className="creative-textarea"
                placeholder={uploadedScript ? `已加载手动剧本《${uploadedScript.name}》，共 ${scriptContent.length} 字。\n您可在此输入特定导演风格或视觉修改意见，或直接点击发送生成短剧。` : "由一个想法或故事开始..."}
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    initDramaProject(chatInput);
                  }
                }}
              />
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px' }}>
                {/* 左下角三个胶囊按钮 */}
                <div style={{ display: 'flex', gap: '10px', position: 'relative' }}>
                  
                  {/* 模型选择按钮 */}
                  <button 
                    type="button" 
                    className={`capsule-btn ${showModelConfiguration ? 'active' : ''}`}
                    onClick={() => { setActivePopover('none'); setShowModelConfiguration(true); }}
                  >
                    <Cpu size={14} /> 模型: {config.videoModel || '未配置'}
                  </button>

                  {/* Skill 选择按钮 */}
                  <button 
                    type="button" 
                    className={`capsule-btn ${showProjectSkillManager ? 'active' : ''}`}
                    onClick={() => { setActivePopover('none'); setShowProjectSkillManager(true); }}
                  >
                    <Sliders size={14} /> Skill: 项目管理
                  </button>

                  <button
                    type="button"
                    className={`capsule-btn ${activePopover === 'element' ? 'active' : ''}`}
                    onClick={() => setActivePopover(activePopover === 'element' ? 'none' : 'element')}
                    aria-haspopup="menu"
                    aria-expanded={activePopover === 'element'}
                  ><Folder size={14} /> 元素</button>

                  {activePopover === 'element' && (
                    <div className="element-menu" role="menu" aria-label="选择元素类型">
                      {([
                        ['actor', '演员', '五视图与表演身份锚点'],
                        ['prop', '道具', '归属、位置和状态连续性'],
                        ['scene', '场景', '空间、时段、天气和灯光'],
                        ['effect', '特效', '时间、目标和结束状态'],
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
                    title={uploadedScript ? '已加载手动剧本，点击可重新上传' : '上传手动剧本并一键生成短剧'}
                  >
                    <Upload size={14} /> {uploadedScript ? `已选剧本: ${uploadedScript.name.substring(0, 10)}${uploadedScript.name.length > 10 ? '...' : ''}` : '上传剧本'}
                    {uploadedScript && (
                      <span 
                        onClick={(e) => {
                          e.stopPropagation();
                          setUploadedScript(null);
                          setScriptContent('');
                          if (fileInputRef.current) fileInputRef.current.value = '';
                        }} 
                        style={{ marginLeft: '6px', color: 'var(--neon-red)', cursor: 'pointer', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center' }}
                        title="清除剧本并切换回普通选题模式"
                      >
                        <X size={10} />
                      </span>
                    )}
                  </button>
                  <input 
                    type="file" 
                    ref={fileInputRef} 
                    style={{ display: 'none' }} 
                    accept=".txt,.md,.docx,.pdf,.fdx"
                    onChange={handleScriptUpload}
                  />

                  {/* Skill 选择气泡弹窗 */}
                  {activePopover === 'skill' && (
                    <div className="popover-window" style={{ bottom: '45px', left: '120px', width: '300px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '6px' }}>
                        <h4 style={{ fontSize: '0.9rem', margin: 0 }}>内置与导入 Skills</h4>
                        <button 
                          onClick={() => { setShowImportSkillModal(true); setActivePopover('none'); }}
                          style={{ background: 'transparent', border: 'none', color: 'var(--neon-cyan)', fontSize: '0.75rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '2px' }}
                        >
                          + 导入外部Skill
                        </button>
                      </div>
                      <div 
                        onClick={() => {
                          updateConfigAndSync({ shotStyle: 'cinematic', directorStyle: 'cyberpunk' });
                          setActivePopover('none');
                        }}
                        className={`model-list-item ${config.shotStyle === 'cinematic' ? 'selected' : ''}`}
                      >
                        <div><strong>AI 短剧一站式生成</strong></div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>内置36运镜及100+质检</span>
                      </div>
                      <div 
                        onClick={() => {
                          updateConfigAndSync({ shotStyle: 'standard', directorStyle: 'realistic' });
                          setActivePopover('none');
                        }}
                        className={`model-list-item ${config.shotStyle === 'standard' ? 'selected' : ''}`}
                      >
                        <div><strong>剧情短片生成</strong></div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>经典正反打文戏对切</span>
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
                              color: 'rgba(255, 255, 255, 0.4)',
                              cursor: 'pointer',
                              padding: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              zIndex: 10
                            }}
                            title="物理删除该技能包"
                          >
                            <X size={12} />
                          </button>
                          <div><strong>{s.name}</strong> <span style={{ fontSize: '0.65rem', padding: '1px 4px', background: 'var(--neon-green)', color: '#000', borderRadius: '4px', marginLeft: '4px', fontWeight: 'bold' }}>已导入</span></div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{s.description}</span>
                        </div>
                      ))}
                    </div>
                  )}

                </div>

                {/* 右下角圆形发送按钮 */}
                <button 
                  onClick={() => initDramaProject(chatInput)}
                  className="cyber-btn" 
                  style={{ width: '40px', height: '40px', borderRadius: '50%', padding: '0', background: 'linear-gradient(135deg, #00f2fe, #0072ff)' }}
                >
                  <ArrowUp size={18} color="#fff" />
                </button>

              </div>
            </div>

          </div>

          {/* 热门 Skills 卡片横列 */}
          {showSkillsGrid && (
            <div style={{ marginTop: '24px', position: 'relative' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  🔥 推荐创作 Skills (点击快速填入选题)
                </span>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  <button 
                    onClick={() => setShowProjectSkillManager(true)}
                    style={{ background: 'rgba(0, 242, 254, 0.08)', border: '1px solid rgba(0, 242, 254, 0.3)', color: 'var(--neon-cyan)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px' }}
                  >
                    + 管理项目 Skill
                  </button>
                  <button 
                    onClick={() => setShowSkillsGrid(false)} 
                    style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem' }}
                    title="关闭推荐"
                  >
                    <X size={14} /> 隐藏
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
                      setChatInput(item.prompt);
                      setConfig({ ...config, titleSuggestion: item.prompt });
                    }}
                  >
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRecommendedTemplates(prev => prev.filter(t => t.id !== item.id));
                      }}
                      style={{ 
                        position: 'absolute', 
                        top: '6px', 
                        right: '6px', 
                        background: 'rgba(255,255,255,0.1)', 
                        border: 'none', 
                        borderRadius: '50%', 
                        color: 'rgba(255,255,255,0.6)', 
                        width: '18px', 
                        height: '18px', 
                        display: 'flex', 
                        alignItems: 'center', 
                        justifyContent: 'center', 
                        cursor: 'pointer',
                        padding: 0,
                        transition: 'all 0.2s'
                      }}
                      title="删除该模版"
                    >
                      <X size={10} />
                    </button>
                    <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{item.title}</span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{item.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <CapabilityCenter role={currentUser?.role} />

          {/* 历史任务/断点大厅 (大卡片) */}
          <div style={{ maxWidth: '900px', width: '100%', margin: '40px auto 0 auto' }}>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 500, marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HardDrive size={18} color="#fbc02d" /> 断点续传项目大厅
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
              {historyTasks.map(task => {
                const isRunning = task.status === 'running';
                const isCompleted = task.status === 'completed';
                const isIdle = task.status === 'idle' || task.status === 'paused';
                const isReview = task.status === 'awaiting_quality_review';
                const isQualityFailed = task.status === 'quality_failed';
                
                // 状态名及色彩对齐
                let statusLabel = "IDLE";
                let statusColor = "var(--neon-amber)";
                if (isRunning) {
                  statusLabel = "RUNNING";
                  statusColor = "var(--neon-cyan)";
                } else if (isCompleted) {
                  statusLabel = "COMPLETED";
                  statusColor = "var(--neon-green)";
                } else if (isReview) {
                  statusLabel = "QUALITY REVIEW";
                  statusColor = "var(--neon-amber)";
                } else if (isQualityFailed) {
                  statusLabel = "QUALITY FAILED";
                  statusColor = "var(--neon-red)";
                }

                // 进度百分比
                const progressPct = Math.min(Math.round((task.currentStage / 8) * 100), 100);

                return (
                  <div 
                    key={task.taskId} 
                    onClick={() => handleLoadTask(task)}
                    className="glass-panel"
                    style={{ 
                      padding: '18px', 
                      cursor: 'pointer', 
                      background: 'rgba(255,255,255,0.02)',
                      border: isRunning ? '1px solid rgba(0, 242, 254, 0.3)' : '1px solid var(--border-color)',
                      boxShadow: isRunning ? '0 0 15px rgba(0, 242, 254, 0.08)' : 'none',
                      transition: 'all 0.3s ease',
                      position: 'relative'
                    }}
                  >
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteTask(task.taskId);
                      }}
                      style={{
                        position: 'absolute',
                        top: '4px',
                        right: '4px',
                        background: 'transparent',
                        border: 'none',
                        color: 'rgba(255, 255, 255, 0.35)',
                        cursor: 'pointer',
                        padding: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 10
                      }}
                      title="删除任务项目"
                    >
                      <X size={10} />
                    </button>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px', alignItems: 'center', paddingRight: '12px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '140px' }}>
                        {task.config.titleSuggestion}
                      </span>
                      <span style={{ fontSize: '0.75rem', fontWeight: 'bold', color: statusColor, textShadow: `0 0 8px ${statusColor}40` }}>
                        {statusLabel}
                      </span>
                    </div>

                    <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '8px' }}>
                      {isCompleted ? (
                        <span>🎉 已完成一键成片 (100%)</span>
                      ) : (
                        <span>
                          当前进度: 第 {task.currentStage}/8 步 ({task.stageName})
                          {isRunning ? (
                            <span style={{ color: 'var(--neon-cyan)', marginLeft: '4px' }}>- 正在生成...</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)', marginLeft: '4px' }}>- 已暂停</span>
                          )}
                        </span>
                      )}
                    </p>

                    {/* 进度条打印显示 */}
                    <div style={{ width: '100%', height: '5px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden', marginBottom: '14px' }}>
                      <div 
                        style={{ 
                          width: `${progressPct}%`, 
                          height: '100%', 
                          background: isCompleted 
                            ? 'linear-gradient(90deg, #10b981, #10b981)' 
                            : 'linear-gradient(90deg, #00f2fe, #0072ff)',
                          boxShadow: isRunning ? '0 0 8px #00f2fe' : 'none',
                          transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)' 
                        }}
                      ></div>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      {/* 卡片快速状态切换按钮，支持暂停/恢复 */}
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {isRunning && (
                          <button 
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCardPause(task.taskId);
                            }}
                            className="capsule-btn" 
                            style={{ padding: '2px 8px', fontSize: '0.7rem', borderColor: 'var(--neon-red)', color: 'var(--neon-red)', background: 'rgba(239, 68, 68, 0.05)' }}
                          >
                            <Pause size={10} style={{ display: 'inline', marginRight: '2px' }} /> 暂停
                          </button>
                        )}
                        {isIdle && (
                          <button 
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCardResume(task.taskId);
                            }}
                            className="capsule-btn" 
                            style={{ padding: '2px 8px', fontSize: '0.7rem', borderColor: 'var(--neon-cyan)', color: 'var(--neon-cyan)', background: 'rgba(0, 242, 254, 0.05)' }}
                          >
                            <Play size={10} style={{ display: 'inline', marginRight: '2px' }} /> 恢复
                          </button>
                        )}
                      </div>
                      
                      <button className="capsule-btn" style={{ padding: '2px 10px', fontSize: '0.7rem' }}>
                        加载断点 <ArrowRight size={10} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 创建项目悬浮按钮 */}
          <div style={{ position: 'fixed', bottom: '40px', left: '40px', zIndex: 100 }}>
            <button 
              className="glass-panel" 
              onClick={() => {
                setNewProjectName('');
                setShowCreateModal(true);
              }} 
              style={{ padding: '12px 20px', borderRadius: '99px', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', background: 'rgba(255,255,255,0.03)' }}
            >
              <span style={{ width: 16, height: 16, borderRadius: '50%', background: 'var(--neon-cyan)', display: 'inline-block' }}></span>
              创建新项目
            </button>
          </div>

          {/* 磨砂玻璃真·创建新项目 Modal 弹窗 */}
          {showCreateModal && (
            <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
              <div className="glass-panel" style={{ width: '480px', padding: '24px', position: 'relative', border: '1px solid rgba(0, 242, 254, 0.2)', boxShadow: '0 0 30px rgba(0, 242, 254, 0.15)' }}>
                <button 
                  onClick={() => setShowCreateModal(false)} 
                  style={{ position: 'absolute', top: '16px', right: '16px', background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                >
                  <X size={18} />
                </button>

                <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '20px', color: 'var(--neon-cyan)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  🎬 创建全新短剧制作项目
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>创意大纲/选题名称</label>
                    <input 
                      type="text" 
                      placeholder="例如：重生之我在火山方舟当车载配件巨头"
                      value={newProjectName}
                      onChange={e => setNewProjectName(e.target.value)}
                      style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.9rem' }}
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>导演风格</label>
                      <select 
                        value={newProjectDirectorStyle}
                        onChange={e => setNewProjectDirectorStyle(e.target.value)}
                        style={{ width: '100%', padding: '10px', background: '#0a1017', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                      >
                        <option value="cyberpunk">Cyberpunk 赛博朋克</option>
                        <option value="retro">Retro 怀旧经典</option>
                        <option value="realistic">Realistic 电影写实</option>
                        <option value="sci_fi_future">Sci-Fi Future 科幻未来</option>
                        <option value="palace">Ancient Palace 古风宫廷</option>
                        <option value="mystery_dark">Dark Mystery 悬疑暗黑</option>
                        <option value="anime">Anime Niji 动漫二次元</option>
                        <option value="horror_folk">Horror Folk 民俗惊悚</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>运镜风格</label>
                      <select 
                        value={newProjectShotStyle}
                        onChange={e => setNewProjectShotStyle(e.target.value)}
                        style={{ width: '100%', padding: '10px', background: '#0a1017', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                      >
                        <option value="cinematic">Cinematic 36运镜系统</option>
                        <option value="standard">Standard 普通分镜</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* 成片方式 + 集数 (item 3 两种成片方式 / item 6 选择指定集数) */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginTop: '14px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>成片方式</label>
                    <select
                      value={newProjectOneClick ? 'one_click' : 'guided'}
                      onChange={e => setNewProjectOneClick(e.target.value === 'one_click')}
                      style={{ width: '100%', padding: '10px', background: '#0a1017', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                    >
                      <option value="one_click">⚡ 一键成片 (后台连续生成全部 8 步)</option>
                      <option value="guided">🧭 一步一步引导 (逐步生成，可对话微调)</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>剧本集数 (一次生成，视频逐集制作)</label>
                    <select
                      value={newProjectEpisodes}
                      onChange={e => setNewProjectEpisodes(parseInt(e.target.value, 10))}
                      style={{ width: '100%', padding: '10px', background: '#0a1017', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                    >
                      {[1, 2, 3, 4, 5, 6, 8, 10, 12].map(n => (
                        <option key={n} value={n}>{n} 集</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '18px' }}>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="capsule-btn"
                    style={{ padding: '8px 16px' }}
                  >
                    取消
                  </button>
                  <button
                    onClick={handleConfirmCreate}
                    className="cyber-btn"
                    style={{ padding: '8px 20px', background: 'linear-gradient(135deg, #00f2fe, #0072ff)', color: '#fff', fontWeight: 600 }}
                  >
                    立即创建项目
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      ) : (
        
        // 2. 已进入项目：双栏工作区大厅 (截图 3)
        <div className="workbench-layout">
          
          {/* 左侧：核心资产产出看版 (70% 宽) */}
          <div className="asset-viewer">
            
            {/* 顶部二级导航条 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px', marginBottom: '20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <Film size={22} color="var(--neon-cyan)" />
                <h2 style={{ fontSize: '1.2rem', fontWeight: 600 }}>
                  {taskData?.config.titleSuggestion ? `《${taskData.config.titleSuggestion}》` : "AI短剧制作"} - 看板展示大厅
                </h2>
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button className={`capsule-btn ${activeTabStage === 1 ? 'active' : ''}`} onClick={() => setActiveTabStage(1)}><Film size={12} /> 1.总导演</button>
                <button className={`capsule-btn ${activeTabStage === 2 ? 'active' : ''}`} onClick={() => setActiveTabStage(2)}><ClipboardList size={12} /> 2.编剧</button>
                <button className={`capsule-btn ${activeTabStage === 3 ? 'active' : ''}`} onClick={() => setActiveTabStage(3)}><UserCheck size={12} /> 3.角色</button>
                <button className={`capsule-btn ${activeTabStage === 4 ? 'active' : ''}`} onClick={() => setActiveTabStage(4)}><Sliders size={12} /> 4.分镜</button>
                <button className={`capsule-btn ${activeTabStage === 5 ? 'active' : ''}`} onClick={() => setActiveTabStage(5)}><Video size={12} /> 5.视觉</button>
                <button className={`capsule-btn ${activeTabStage === 6 ? 'active' : ''}`} onClick={() => setActiveTabStage(6)}><Music size={12} /> 6.音频</button>
                <button className={`capsule-btn ${activeTabStage === 7 ? 'active' : ''}`} onClick={() => setActiveTabStage(7)}><Layers size={12} /> 7.合成</button>
                <button className={`capsule-btn ${activeTabStage === 8 ? 'active' : ''}`} onClick={() => setActiveTabStage(8)}><Share2 size={12} /> 8.宣发</button>
              </div>
            </div>

            {/* 当选择的阶段尚无资产时，展示 Novara Slate */}
            {!taskData?.assets[activeTabStage.toString()] ? (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', opacity: 0.65 }}>
                <img 
                  src="https://portal.volccdn.com/obj/volcfe/cloud-universal-doc/upload_5a2661e94d2474b95a54475798558b66.mp4" 
                  style={{ width: '120px', height: '120px', display: 'none' }} 
                  alt="clapperboard" 
                />
                <Film size={80} color="var(--neon-cyan)" style={{ marginBottom: '20px', filter: 'drop-shadow(0 0 20px rgba(0, 242, 254, 0.3))' }} />
                <h3 style={{ fontSize: '1.8rem', fontWeight: 600, marginBottom: '10px' }}>开始！</h3>
                <p style={{ color: 'var(--text-muted)' }}>请在右侧聊天框中输入您的创作需求，或者点击“下一步”启动生成吧！</p>
              </div>
            ) : (
              
              // 步骤资产高保真呈现
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '24px' }}>
                
                <div className="glass-panel" style={{ flex: 1, background: 'rgba(0,0,0,0.2)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '16px' }}>
                    <Monitor size={18} color="var(--neon-cyan)" />
                    <span style={{ fontWeight: 600 }}>Stage {activeTabStage} 阶段资产预览</span>
                  </div>

                  {/* 1: 总导演策划方案 */}
                  {activeTabStage === 1 && (
                    <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.7', fontSize: '0.95rem', background: '#05080c', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.03)' }}>
                      {taskData.assets["1"]}
                    </div>
                  )}

                  {/* 2: 编剧剧本创作 */}
                  {activeTabStage === 2 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.7', fontSize: '0.95rem', background: '#05080c', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.03)' }}>
                        {taskData.assets["2"]}
                      </div>

                      {/* 分集制作：剧本一次生成多集，视频逐集制作 (item 6) */}
                      {taskData.assets["2"] && (
                        <div style={{ background: '#05080c', padding: '16px 20px', borderRadius: '12px', border: '1px solid rgba(0, 242, 254, 0.18)' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                            <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neon-cyan)' }}>
                              🎬 分集制作 (视频逐集出片)
                            </div>
                            <button
                              onClick={handlePlanEpisodes}
                              disabled={episodesBusy}
                              className="capsule-btn"
                              style={{ padding: '6px 14px', fontSize: '0.78rem', opacity: episodesBusy ? 0.6 : 1 }}
                            >
                              {episodesBusy ? '分集中...' : (episodes.length > 0 ? '🔄 重新分集' : '📑 一键分集')}
                            </button>
                          </div>
                          {episodes.length === 0 ? (
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                              点击「一键分集」把完整剧本切分为多集，然后可逐集制作 2.5-3 分钟成片。
                            </div>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              {episodes.map((ep: EpisodeItem) => (
                                <div key={ep.index} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', background: '#0a1017', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                                  <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-light)', minWidth: '52px' }}>第{ep.index}集</span>
                                  <span style={{ flex: 1, fontSize: '0.76rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ep.title}</span>
                                  <span style={{ fontSize: '0.7rem', padding: '1px 8px', borderRadius: '999px', border: '1px solid var(--border-color)', color: ep.status === 'completed' ? '#3ddc84' : ep.status === 'running' ? '#ffb020' : 'var(--text-muted)' }}>
                                    {ep.status === 'completed' ? '✓ 已完成' : ep.status === 'running' ? '制作中…' : '待制作'}
                                  </span>
                                  {ep.status === 'completed' && ep.videoUrl ? (
                                    <a href={ep.videoUrl} target="_blank" rel="noreferrer" className="capsule-btn" style={{ padding: '4px 12px', fontSize: '0.74rem' }}>▶ 播放</a>
                                  ) : (
                                    <button
                                      onClick={() => handleProduceEpisode(ep.index)}
                                      disabled={ep.status === 'running'}
                                      className="capsule-btn"
                                      style={{ padding: '4px 12px', fontSize: '0.74rem', opacity: ep.status === 'running' ? 0.6 : 1 }}
                                    >
                                      {ep.status === 'running' ? '⏳' : '🎬 制作本集'}
                                    </button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 3: 角色五视图设定图 + 五维 DNA 设定文本 */}
                  {activeTabStage === 3 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                      {/* 全部人物角色：姓名 + 身份 + 特征信息 + 有序五视图，跨镜头一致性锚点 */}
                      {(() => {
                        const structured = Array.isArray(taskData.assets["3_characters"]) ? taskData.assets["3_characters"] : null;
                        const sheets = taskData.assets["3_sheets"] || {};
                        const cards = structured && structured.length > 0
                          ? structured
                          : Object.entries(sheets).map(([name, sheet]) => ({ name, role: '', desc: '', sheet: String(sheet) }));
                        if (!cards || cards.length === 0) return null;
                        return (
                          <div>
                            <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neon-cyan)', marginBottom: '10px' }}>
                              🎭 全部人物角色 ({cards.length}) · 五视图设定图 (正面 · 正面3/4 · 侧面 · 背面3/4 · 背面)
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '14px' }}>
                              {(cards as CharacterCard[]).map((c: CharacterCard, i: number) => {
                                const url = c.sheet;
                                return (
                                  <div key={`${c.name}-${i}`} className="glass-panel" style={{ background: '#05080c', border: '1px solid rgba(0, 242, 254, 0.18)', borderRadius: '12px', padding: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                                      <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-light)' }}>{String(c.name).replace(/[:：]$/, '')}</span>
                                      {c.role && (
                                        <span style={{ fontSize: '0.68rem', padding: '1px 7px', borderRadius: '999px', background: 'rgba(0, 242, 254, 0.14)', color: 'var(--neon-cyan)', border: '1px solid rgba(0, 242, 254, 0.3)' }}>{c.role}</span>
                                      )}
                                    </div>
                                    {typeof url === 'string' && url.startsWith('http') ? (
                                      <a href={url} target="_blank" rel="noreferrer">
                                        <img src={url} alt={`${c.name} 五视图`} style={{ width: '100%', borderRadius: '8px', objectFit: 'contain', background: '#fff', border: '1px solid rgba(0, 242, 254, 0.25)' }} />
                                      </a>
                                    ) : (
                                      <div style={{ width: '100%', height: '160px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '8px', border: '1px dashed var(--text-muted)', color: 'var(--text-muted)', fontSize: '0.8rem' }}>五视图生成中...</div>
                                    )}
                                    {Array.isArray(c.views) && c.views.length === 5 && (
                                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px', marginTop: '8px' }}>
                                        {c.views.map((view: { view: string; image_url: string }) => (
                                          <a href={view.image_url} target="_blank" rel="noreferrer" key={view.view} title={view.view}>
                                            <img src={view.image_url} alt={`${c.name} ${view.view}`} style={{ width: '100%', aspectRatio: '1/2', objectFit: 'cover', borderRadius: '4px', border: '1px solid rgba(0, 242, 254, 0.2)' }} />
                                          </a>
                                        ))}
                                      </div>
                                    )}
                                    {c.desc && (
                                      <div style={{ marginTop: '8px', fontSize: '0.74rem', lineHeight: '1.5', color: 'var(--text-muted)', maxHeight: '88px', overflow: 'auto' }}>{c.desc}</div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}
                      {/* 五维 DNA 设定文本 */}
                      <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.7', fontSize: '0.95rem', background: '#05080c', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.03)' }}>
                        {typeof taskData.assets["3"] === 'string'
                          ? taskData.assets["3"]
                          : Object.entries(taskData.assets["3"] || {}).map(([key, val]) => `【${key}】:\n${val}`).join('\n\n')
                        }
                      </div>
                    </div>
                  )}

                  {/* 4: 精准九宫格分镜 + 明细表 */}
                  {activeTabStage === 4 && (
                    <div style={{ overflowX: 'auto', display: 'flex', flexDirection: 'column', gap: '18px' }}>
                      {taskData.assets["4_grid"] && (
                        <div>
                          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neon-cyan)', marginBottom: '10px' }}>
                            🎬 3×3 九宫格分镜 · 从左到右、从上到下
                          </div>
                          <a href={taskData.assets["4_grid"]} target="_blank" rel="noreferrer">
                            <img src={taskData.assets["4_grid"]} alt="3×3 九宫格分镜" style={{ width: 'min(100%, 540px)', display: 'block', margin: '0 auto', borderRadius: '10px', border: '1px solid rgba(0, 242, 254, 0.35)', background: '#000' }} />
                          </a>
                        </div>
                      )}
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                        <thead>
                          <tr style={{ background: 'rgba(0, 242, 254, 0.08)', borderBottom: '1px solid var(--neon-cyan)' }}>
                            <th style={{ padding: '10px', textAlign: 'left' }}>镜号</th>
                            <th style={{ padding: '10px', textAlign: 'left' }}>分镜预览图</th>
                            <th style={{ padding: '10px', textAlign: 'left' }}>景别</th>
                            <th style={{ padding: '10px', textAlign: 'left' }}>运镜</th>
                            <th style={{ padding: '10px', textAlign: 'left' }}>画面视觉动作描述 (拍摄指南映射)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {taskData.assets["4"].map((shot: ProductionShot) => (
                            <tr key={shot.shot_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <td style={{ padding: '12px', fontWeight: 600 }}>Shot {shot.shot_id}</td>
                              <td style={{ padding: '12px' }}>
                                {shot.image_url ? (
                                  <img 
                                    src={shot.image_url} 
                                    style={{ width: '70px', height: '124px', borderRadius: '6px', objectFit: 'cover', border: '1px solid rgba(0, 242, 254, 0.25)', boxShadow: '0 0 6px rgba(0, 242, 254, 0.1)' }} 
                                    alt={`Shot ${shot.shot_id}`} 
                                  />
                                ) : (
                                  <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>暂无图片</span>
                                )}
                              </td>
                              <td style={{ padding: '12px' }}><span style={{ padding: '2px 6px', background: 'rgba(255,255,255,0.04)', borderRadius: '4px' }}>{shot.size}</span></td>
                              <td style={{ padding: '12px', color: 'var(--neon-cyan)' }}>{shot.motion}</td>
                              <td style={{ padding: '12px' }}>{shot.desc}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* 5: 视觉总监生成 */}
                  {activeTabStage === 5 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                      {taskData.assets["5"] ? (
                        Array.isArray(taskData.assets["5"]) ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxHeight: '500px', overflowY: 'auto', paddingRight: '8px' }}>
                            {taskData.assets["5"].map((shot: ProductionShot, idx: number) => (
                              <div key={idx} className="glass-panel" style={{ background: '#05080c', border: '1px solid rgba(0, 242, 254, 0.15)', padding: '16px', borderRadius: '12px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '6px' }}>
                                  <span style={{ fontWeight: 600, color: 'var(--neon-cyan)', fontSize: '0.9rem' }}>镜头 {shot.shot_id || (idx + 1)} ({shot.size || 'MS'} | {shot.motion || 'Dolly In'})</span>
                                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>描述: {shot.desc || '分镜画面'}</span>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '16px' }}>
                                  <div>
                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>图生视频动态画面 ({taskData.config.videoModel || config.videoModel})</span>
                                    {shot.video_url ? (
                                      <video src={shot.video_url} controls loop style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--neon-cyan)' }} />
                                    ) : (
                                      <div style={{ width: '100%', height: '150px', background: 'rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '8px', border: '1px dashed var(--text-muted)', color: 'var(--text-muted)', fontSize: '0.8rem' }}>视频生成中...</div>
                                    )}
                                  </div>
                                  <div>
                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>文生图底片首帧 ({taskData.config.imageModel || config.imageModel})</span>
                                    {shot.image_url ? (
                                      <img src={shot.image_url} style={{ width: '100%', borderRadius: '8px', objectFit: 'cover' }} alt={`镜头 ${shot.shot_id || (idx + 1)}`} />
                                    ) : (
                                      <div style={{ width: '100%', height: '150px', background: 'rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '8px', border: '1px dashed var(--text-muted)', color: 'var(--text-muted)', fontSize: '0.8rem' }}>图片生成中...</div>
                                    )}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px' }}>
                            <div>
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>图生视频动态渲染片段 ({taskData.config.videoModel || config.videoModel})</span>
                              {taskData.assets["5"].video_url ? (
                                <video src={taskData.assets["5"].video_url} controls loop style={{ width: '100%', borderRadius: '12px', border: '1px solid var(--neon-cyan)' }} />
                              ) : (
                                <div style={{ width: '100%', height: '200px', background: 'rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '12px', border: '1px dashed var(--text-muted)', color: 'var(--text-muted)' }}>视频生成中...</div>
                              )}
                            </div>
                            <div>
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>首帧文生图高精度底片 ({taskData.config.imageModel || config.imageModel})</span>
                              {taskData.assets["5"].image_url ? (
                                <img src={taskData.assets["5"].image_url} style={{ width: '100%', borderRadius: '12px', objectFit: 'cover' }} alt="首帧" />
                              ) : (
                                <div style={{ width: '100%', height: '200px', background: 'rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '12px', border: '1px dashed var(--text-muted)', color: 'var(--text-muted)' }}>图片生成中...</div>
                              )}
                            </div>
                          </div>
                        )
                      ) : (
                        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                          暂无视觉片段资产。请先运行此阶段以生成底片与视频。
                        </div>
                      )}
                    </div>
                  )}

                  {/* 6: 音频总监生成 */}
                  {activeTabStage === 6 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      <div className="glass-panel" style={{ background: '#05080c', display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <Music size={28} color="var(--neon-cyan)" />
                        <div>
                          <h4 style={{ fontSize: '0.95rem' }}>音轨合成: 角色专属配音 + BGM摇滚背景音</h4>
                          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>模型: {taskData.config.ttsModel || config.ttsModel} | 唇形对齐率: 92.5% | 声线特征: {taskData.assets["6"]?.voice_profile || "自适应推荐"}</p>
                        </div>
                      </div>
                      <audio src={taskData.assets["6"].audio_url} controls style={{ width: '100%' }} />
                    </div>
                  )}

                  {/* 7: 合成发布 */}
                  {activeTabStage === 7 && (
                    <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '20px' }}>
                      <div>
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>9:16 H.264 竖屏高清成片</span>
                        <video src={taskData.videoUrl || taskData.assets["7"]?.final_video_url} controls style={{ width: '100%', borderRadius: '16px', border: '2px solid var(--neon-cyan)', boxShadow: '0 0 20px rgba(0, 242, 254, 0.2)' }} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        <div className="glass-panel" style={{ background: '#05080c', padding: '12px' }}>
                          <span style={{ color: 'var(--neon-cyan)', fontSize: '0.8rem', display: 'block', marginBottom: '4px' }}>合成属性</span>
                          <div style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            <div><strong>画幅比例:</strong> {taskData.assets["7"]?.aspect_ratio || "9:16 (竖屏)"}</div>
                            <div><strong>帧率:</strong> 30 fps (锁定恒定帧率)</div>
                            <div><strong>音画同步:</strong> 0 帧偏移</div>
                            <div><strong>字幕样式:</strong> {taskData.assets["7"]?.subtitles || "内置流光特效字幕"}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* 8: 宣发 Agent */}
                  {activeTabStage === 8 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div className="glass-panel" style={{ background: '#05080c', padding: '12px' }}>
                        <span style={{ color: 'var(--neon-cyan)', fontSize: '0.8rem', display: 'block', marginBottom: '4px' }}>宣发大字标题</span>
                        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                          {(() => {
                            const titleMatch = taskData.prContent?.match(/🔥 抖音爆款大字标题：([^\n]+)/);
                            return titleMatch ? titleMatch[1] : taskData.config.titleSuggestion;
                          })()}
                        </span>
                      </div>
                      <div className="glass-panel" style={{ background: '#05080c', padding: '12px' }}>
                        <span style={{ color: 'var(--neon-cyan)', fontSize: '0.8rem', display: 'block', marginBottom: '4px' }}>引流文案</span>
                        <p style={{ fontSize: '0.8rem', lineHeight: '1.4' }}>
                          {(() => {
                            const bodyMatch = taskData.prContent?.match(/📌 黄金引流文案：‘([^’]+)’/);
                            return bodyMatch ? bodyMatch[1] : (taskData.prContent || "暂无文案");
                          })()}
                        </p>
                      </div>
                      <div style={{ fontSize: '0.85rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>短发布链接: </span>
                        <a href={taskData.shortLink} target="_blank" rel="noreferrer" style={{ color: 'var(--neon-cyan)' }}>{taskData.shortLink}</a>
                      </div>
                    </div>
                  )}

                  {/* 统一卡片底部推进/下一步按钮栏 */}
                  {taskData && (
                    <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      {activeTabStage > 1 ? (
                        <button 
                          type="button"
                          onClick={() => setActiveTabStage(activeTabStage - 1)}
                          className="capsule-btn"
                          style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                        >
                          ← 上一步资产
                        </button>
                      ) : <div />}

                      <div style={{ display: 'flex', gap: '10px' }}>
                        {activeTabStage < taskData.currentStage ? (
                          <button 
                            type="button"
                            onClick={() => setActiveTabStage(activeTabStage + 1)}
                            className="capsule-btn"
                            style={{ borderColor: 'var(--neon-cyan)', color: 'var(--neon-cyan)', fontSize: '0.75rem', padding: '5px 12px' }}
                          >
                            查看下一步资产 →
                          </button>
                        ) : (
                          activeTabStage === taskData.currentStage && taskData.status !== 'completed' ? (
                            taskData.status === 'awaiting_quality_review' ? (
                              <span style={{ fontSize: '0.75rem', color: 'var(--neon-amber)', fontWeight: 600 }}>
                                🛡️ 等待真实多模态/人工质量验收
                              </span>
                            ) : taskData.status === 'quality_failed' ? (
                              <span style={{ fontSize: '0.75rem', color: 'var(--neon-red)', fontWeight: 600 }}>
                                ✕ 质量门禁未通过，请按报告定向重生成
                              </span>
                            ) :
                            taskData.status === 'running' ? (
                              <button 
                                type="button"
                                onClick={handlePause} 
                                className="capsule-btn" 
                                style={{ borderColor: 'var(--neon-red)', color: 'var(--neon-red)', fontSize: '0.75rem', padding: '5px 12px' }}
                              >
                                <Pause size={10} style={{ marginRight: '4px' }} /> 暂停任务
                              </button>
                            ) : taskData.status === 'paused' ? (
                              <button 
                                type="button"
                                onClick={handleResume} 
                                className="capsule-btn" 
                                style={{ borderColor: 'var(--neon-amber)', color: 'var(--neon-amber)', fontSize: '0.75rem', padding: '5px 12px' }}
                              >
                                <Play size={10} style={{ marginRight: '4px' }} /> 恢复一键成片
                              </button>
                            ) : (
                              <>
                                <button 
                                  type="button"
                                  onClick={handleNextStage} 
                                  className="capsule-btn" 
                                  style={{ borderColor: 'var(--neon-cyan)', color: 'var(--neon-cyan)', fontSize: '0.75rem', padding: '5px 12px' }}
                                >
                                  执行下一步 <ChevronRight size={10} />
                                </button>
                                <button 
                                  type="button"
                                  onClick={handleRunAll} 
                                  className="capsule-btn"
                                  style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                                >
                                  一键成片
                                </button>
                              </>
                            )
                          ) : (
                            activeTabStage === 8 && taskData.status === 'completed' && (
                              <span style={{ fontSize: '0.75rem', color: 'var(--neon-green)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                                ✓ 全剧一键成片已完成！
                              </span>
                            )
                          )
                        )}
                      </div>
                    </div>
                  )}

                </div>

                {/* 质检监控底栏 */}
                <div className="glass-panel" style={{ background: 'rgba(0,0,0,0.1)' }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neon-amber)', marginBottom: '10px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '6px' }}>
                    100+项质检校验 (AI 生成短剧一致性检查清单.md) 一致性 Hooks 报告
                  </div>
                  <div 
                    style={{ fontFamily: 'monospace', fontSize: '0.8rem', maxHeight: '120px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}
                  >
                    {taskData.logs[activeTabStage.toString()]}
                  </div>
                </div>

              </div>

            )}

          </div>

          {/* 右侧：对话与工作流控制侧边栏 (30% 宽) (截图 3) */}
          <div className="chat-sidebar">
            
            {/* 顶栏 */}
            <div style={{ height: '56px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 16px' }}>
              <span style={{ fontWeight: 600 }}>对话</span>
              <button 
                onClick={() => {
                  setTaskId('');
                  setTaskData(null);
                }} 
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            {/* 对话消息流区域 */}
            <div style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              {chatMessages.map(msg => (
                <div key={msg.id} className={`chat-bubble ${msg.sender}`}>
                  
                  {/* AI 消息加上 Novara 标志和交互按钮 */}
                  {msg.sender === 'ai' ? (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '4px' }}>
                        <span style={{ fontSize: '0.7rem', padding: '1px 6px', background: 'linear-gradient(90deg, #00f2fe, #0072ff)', color: '#fff', borderRadius: '4px', fontWeight: 'bold' }}>Novara AI</span>
                      </div>
                      
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                      
                      {/* 如果有绑定的步骤，且是当前活跃步骤，且任务处于暂停/等待，则渲染控制按钮 */}
                      {taskData && msg.stage === taskData.currentStage && taskData.status !== 'completed' && (
                        <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
                          
                          {taskData.status === 'running' ? (
                            <button onClick={handlePause} className="capsule-btn" style={{ borderColor: 'var(--neon-red)', color: 'var(--neon-red)' }}>
                              <Pause size={10} /> 暂停任务
                            </button>
                          ) : (
                            <>
                              {taskData.status === 'paused' ? (
                                <button onClick={handleResume} className="capsule-btn" style={{ borderColor: 'var(--neon-amber)', color: 'var(--neon-amber)' }}>
                                  <Play size={10} /> 恢复一键成片
                                </button>
                              ) : (
                                <>
                                  <button onClick={handleNextStage} className="capsule-btn" style={{ borderColor: 'var(--neon-cyan)', color: 'var(--neon-cyan)' }}>
                                    执行下一步 <ChevronRight size={10} />
                                  </button>
                                  <button onClick={handleRunAll} className="capsule-btn">
                                    一键成片
                                  </button>
                                </>
                              )}
                            </>
                          )}

                        </div>
                      )}
                    </div>
                  ) : (
                    <div>{msg.text}</div>
                  )}

                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* 对话底部输入框 */}
            <div style={{ padding: '16px', borderTop: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '10px', position: 'relative' }}>
              
              {/* 侧边栏 Skill 选择气泡弹窗 */}
              {activePopover === 'sidebarSkill' && (
                <div className="popover-window" style={{ bottom: '85px', left: '16px', right: '16px', width: 'auto', zIndex: 100 }}>
                  <h4 style={{ fontSize: '0.85rem', marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '6px' }}>内置超级 Skills</h4>
                  <div 
                    onClick={() => {
                      updateConfigAndSync({ shotStyle: 'cinematic', directorStyle: 'cyberpunk' });
                      setActivePopover('none');
                    }}
                    className={`model-list-item ${config.shotStyle === 'cinematic' ? 'selected' : ''}`}
                  >
                    <div><strong>AI 短剧一站式生成</strong></div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>36运镜及100+自检</span>
                  </div>
                  <div 
                    onClick={() => {
                      updateConfigAndSync({ shotStyle: 'standard', directorStyle: 'realistic' });
                      setActivePopover('none');
                    }}
                    className={`model-list-item ${config.shotStyle === 'standard' ? 'selected' : ''}`}
                  >
                    <div><strong>普通分镜短片生成</strong></div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>经典正反打对话</span>
                  </div>

                  {importedSkills.length > 0 && (
                    <>
                      <h4 style={{ fontSize: '0.85rem', marginTop: '12px', marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '6px' }}>导入外部 Skills</h4>
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
                              color: 'rgba(255, 255, 255, 0.4)',
                              cursor: 'pointer',
                              padding: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              zIndex: 10
                            }}
                            title="物理删除该技能包"
                          >
                            <X size={12} />
                          </button>
                          <div><strong>{s.name}</strong> <span style={{ fontSize: '0.65rem', padding: '1px 4px', background: 'var(--neon-green)', color: '#000', borderRadius: '4px', marginLeft: '4px', fontWeight: 'bold' }}>已导入</span></div>
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
                  模型: {config.llmModel || '未配置'} / {config.videoModel || '未配置'}
                </button>
                <button 
                  type="button"
                  className={`capsule-btn ${showProjectSkillManager ? 'active' : ''}`}
                  style={{ padding: '4px 10px', fontSize: '0.7rem' }}
                  onClick={() => { setActivePopover('none'); setShowProjectSkillManager(true); }}
                >
                  Skill: 项目管理
                </button>
              </div>

              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input 
                  type="text" 
                  placeholder="发送消息..." 
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      sendChatInstruction(chatInput);
                    }
                  }}
                  style={{ flex: 1, padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.9rem' }}
                />
                <button 
                  onClick={() => sendChatInstruction(chatInput)}
                  className="cyber-btn" 
                  style={{ width: '36px', height: '36px', borderRadius: '50%', padding: '0' }}
                >
                  <Send size={14} />
                </button>
              </div>
            </div>

          </div>

        </div>
      )}

      <ModelConfigurationCenter
        open={showModelConfiguration}
        role={currentUser?.role}
        mustChangePassword={currentUser?.must_change_password}
        onClose={() => setShowModelConfiguration(false)}
        onSelect={(category: ModelCategory, modelId: string) => {
          const configKey = ({
            text: 'llmModel', image: 'imageModel', video: 'videoModel', audio: 'ttsModel',
          } as const)[category];
          if (taskId) updateConfigAndSync({ [configKey]: modelId });
          else setConfig(current => ({ ...current, [configKey]: modelId }));
          setShowModelConfiguration(false);
        }}
      />

      <ProjectSkillManager
        open={showProjectSkillManager}
        role={currentUser?.role}
        mustChangePassword={currentUser?.must_change_password}
        onClose={() => setShowProjectSkillManager(false)}
      />

      {/* 磨砂玻璃 导入外部 Skill 弹窗 */}
      {showImportSkillModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center', zIndex: 99999 }}>
          <div className="glass-panel" style={{ width: '500px', padding: '26px', position: 'relative', border: '1px solid rgba(0, 242, 254, 0.25)', boxShadow: '0 0 35px rgba(0, 242, 254, 0.2)' }}>
            <button 
              onClick={() => setShowImportSkillModal(false)} 
              style={{ position: 'absolute', top: '16px', right: '16px', background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
            >
              <X size={18} />
            </button>

            <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '20px', color: 'var(--neon-cyan)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              🔌 导入外部 Skill 技能包
            </h3>

            {/* 标签切换 */}
            <div style={{ display: 'flex', background: 'rgba(255,255,255,0.04)', padding: '4px', borderRadius: '8px', marginBottom: '20px', border: '1px solid rgba(255,255,255,0.05)' }}>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'github' ? 'active' : ''}`}
                onClick={() => setImportSkillType('github')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                GitHub 仓库
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'clawhub' ? 'active' : ''}`}
                onClick={() => setImportSkillType('clawhub')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                Clawhub 库
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'npx' ? 'active' : ''}`}
                onClick={() => setImportSkillType('npx')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                NPX 安装
              </button>
              <button 
                type="button"
                className={`popover-tab-btn ${importSkillType === 'zip' ? 'active' : ''}`}
                onClick={() => setImportSkillType('zip')}
                style={{ flex: 1, padding: '6px 0', fontSize: '0.8rem' }}
              >
                ZIP 上传
              </button>
            </div>

            {/* 表单渲染 */}
            <div style={{ marginBottom: '24px' }}>
              {(importSkillType === 'github' || importSkillType === 'clawhub') && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>
                    {importSkillType === 'github' ? 'GitHub 仓库 URL' : 'Clawhub 库 URL'}
                  </label>
                  <input 
                    type="text" 
                    placeholder="https://github.com/Shanyin-ai/shanyin-screenwriting-master.git"
                    value={importSkillUrl}
                    onChange={e => setImportSkillUrl(e.target.value)}
                    style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.9rem' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px' }}>
                    系统会自动克隆该技能包项目，读取其内部配置规范并在大厅中加载。
                  </p>
                </div>
              )}

              {importSkillType === 'npx' && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>NPX 包名</label>
                  <input 
                    type="text" 
                    placeholder="例如：create-vite-app"
                    value={importSkillPackage}
                    onChange={e => setImportSkillPackage(e.target.value)}
                    style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '0.9rem' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px' }}>
                    系统将在后台通过 `npx -y` 载入并安装指定的包。
                  </p>
                </div>
              )}

              {importSkillType === 'zip' && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>本地 ZIP 技能包</label>
                  <div 
                    style={{ 
                      border: '1px dashed rgba(0, 242, 254, 0.4)', 
                      borderRadius: '12px', 
                      padding: '30px 20px', 
                      textAlign: 'center', 
                      background: 'rgba(0,0,0,0.2)',
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
                    <span style={{ fontSize: '0.85rem', display: 'block', color: importSkillFile ? 'var(--neon-green)' : '#fff' }}>
                      {importSkillFile ? `已选择: ${importSkillFile.name} (${Math.round(importSkillFile.size / 1024)} KB)` : '点击选择或拖拽本地 ZIP 压缩文件上传'}
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
                取消
              </button>
              <button 
                onClick={handleImportSkill} 
                className="cyber-btn" 
                style={{ padding: '8px 20px', background: 'linear-gradient(135deg, #00f2fe, #0072ff)', color: '#fff', fontWeight: 600 }}
              >
                立即导入技能包
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
