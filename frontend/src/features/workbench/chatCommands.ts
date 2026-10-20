export interface ChatCommand {
  command: string;
  label: string;
  description: string;
  keywords: string;
}

export const CHAT_COMMANDS: readonly ChatCommand[] = [
  { command: '/pause', label: '暂停', description: '当前阶段结束后暂停后续制作', keywords: '停止 暂停 pause' },
  { command: '/resume', label: '恢复', description: '从未完成的步骤恢复之前的制作模式', keywords: '继续 恢复 resume continue' },
  { command: '/stop', label: '结束任务', description: '结束后续执行，保留已有资产和对话', keywords: '结束 终止 stop end' },
  { command: '/start', label: '开启', description: '开始第一个尚未完成的步骤', keywords: '开启 开始 启动 start' },
  { command: '/compose', label: '合成视频', description: '前置步骤完成后合成视频、字幕和音轨', keywords: '合成 视频 渲染 compose video' },
  { command: '/auto', label: '一键成片', description: '自动连续完成剩余制作，无需逐步确认', keywords: '一键 成片 全部 自动 auto all' },
  { command: '/status', label: '进度', description: '查看当前步骤、进度和下一步建议', keywords: '进度 查询 状态 status progress' },
  { command: '/help', label: '帮助', description: '查看命令说明和自然语言使用方法', keywords: '帮助 说明 help' },
  { command: '/agent', label: '工具助手', description: '用工具读写本项目：/agent 后面说要做什么；付费操作会先问你', keywords: '助手 工具 agent 查看 修改' },
  { command: '/confirm', label: '确认执行', description: '执行工具助手刚提出的付费操作', keywords: '确认 执行 confirm yes' },
  { command: '/cancel', label: '放弃操作', description: '放弃工具助手刚提出的操作', keywords: '放弃 取消 cancel no' },
];

export function filterChatCommands(input: string): readonly ChatCommand[] {
  const query = input.trim().replace(/^\//, '').trim().toLowerCase();
  return CHAT_COMMANDS.filter(item => `${item.command} ${item.label} ${item.keywords}`.toLowerCase().includes(query));
}
