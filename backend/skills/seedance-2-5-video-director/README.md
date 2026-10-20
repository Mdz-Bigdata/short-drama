# Seedance 2.5 Video Director

面向 Dreamina／即梦 Seedance 2.5 的视频导演 Skill。它将文本创意、人物参考图、视频、音频、分镜或旧提示词整理成可执行的视频脚本、导演方案、诊断结果和复制即用的提示词。

> 非字节跳动、Dreamina 或即梦官方项目。本仓库不会调用付费生成接口，不会自动消耗积分。

## 功能

- 4–30秒普通视频与精确30秒时间轴
- 30–180秒 Long Video
- 视频前置／后置续写
- Smart Edit、标记区域编辑和上传视频编辑
- Clay Renderer 粗白模／精白模渲染指令
- 两段视频无缝转场
- 多格分镜动画
- 人物身份、体型、服装和配饰锁定
- 多人物、对白音色、BGM移除与声画同步
- 真人情感表演、情侣戏、竞技综艺直播镜头和障碍物物理
- 提示词冲突诊断与按原结构改写

## 安装

### 推荐：一行安装

已安装 Node.js 的用户，在 Windows、macOS 或 Linux 终端执行：

```bash
npx skills add liyue-aigc/seedance-2-5-video-director -g -y
```

这条命令会从 GitHub 获取 Skill，并安装到当前用户的 Agent Skills 目录；`-g` 表示全局安装，`-y` 表示跳过交互确认。它使用 npm 附带的 `npx` 启动安装器，但本仓库本身不是需要加入项目依赖的 npm 软件包，因此不使用 `npm install`。

如果电脑上没有 Node.js，也可以直接在 Codex 中发送：

```text
请使用 $skill-installer，从 GitHub 安装 liyue-aigc/seedance-2-5-video-director。
```

### 手动安装（备用）

#### Windows PowerShell

```powershell
$skillRoot = Join-Path $env:USERPROFILE '.codex\skills'
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
git clone https://github.com/liyue-aigc/seedance-2-5-video-director.git (Join-Path $skillRoot 'seedance-2-5-video-director')
```

#### macOS / Linux

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/liyue-aigc/seedance-2-5-video-director.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/seedance-2-5-video-director"
```

安装完成后重新打开Codex会话，并在提示词中调用：

```text
使用 $seedance-2-5-video-director，把我的视频创意整理成可复制的 Seedance 2.5 提示词。
```

安装器明确提示刚完成安装时，Skill会展示一次学习指导；普通新对话会直接处理任务，不会重复教程。需要时可主动发送“显示 `$seedance-2-5-video-director` 使用教程”。

## 更新

通过 `npx skills` 安装的用户：

```bash
npx skills update seedance-2-5-video-director -g -y
```

手动克隆的用户：

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/seedance-2-5-video-director" pull
```

Windows默认安装路径更新：

```powershell
git -C (Join-Path $env:USERPROFILE '.codex\skills\seedance-2-5-video-director') pull
```

## 快速使用

```text
使用 $seedance-2-5-video-director。

任务：生成20秒、16:9的水上竞技综艺片段。
素材：@Image 1 是挑战者完整人物参考，保持原服装；不要继承图片背景。
故事：登场 → 滚筒失衡但通过 → 摆锤窄桥 → 成功冲线。
声音：普通话解说、现场欢呼、机关声和紧张BGM，无字幕。
输出：完整导演方案和最终提示词。
```

### 只要提示词

```text
使用 $seedance-2-5-video-director。只要最终提示词，不要解释。
生成15秒、9:16的街头追逐戏：一名成年女性被三人追赶，写实手持动作片风格，人物与空间方向稳定。
```

### 诊断现有提示词

```text
使用 $seedance-2-5-video-director。只诊断，不重写。
检查下面提示词的时间、运镜、人物、物理和声音是否互相冲突：<粘贴提示词>
```

更多模式与结构见 [SKILL.md](SKILL.md)、[提示词蓝图](references/prompt-blueprints.md) 和 [首次使用引导](references/first-use-onboarding.md)。

## 人物参考原则

普通的“人物参考图”默认代表完整可见人物，而不是只参考脸：

- 保持身份、五官、脸型、肤色和年龄感
- 保持发型、发色、身高、体型和身体比例
- 保持可见服装、鞋子、配饰和穿着方式
- 默认不继承参考图背景、姿势、构图、裁切、文字和光线
- 只有用户明确说“只参考脸”或允许换装时，才缩小参考范围

## 目录

```text
seedance-2-5-video-director/
├── SKILL.md
├── README.md
├── LICENSE
├── NOTICE.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── capabilities-and-limits.md
│   ├── first-use-onboarding.md
│   ├── multimodal-patterns.md
│   ├── official-examples.md
│   ├── prompt-blueprints.md
│   └── realistic-direction-patterns.md
├── scripts/
│   └── validate_skill.py
├── tests/
│   └── cases.json
└── .github/workflows/
    └── validate.yml
```

## 测试

本地运行：

```bash
python scripts/validate_skill.py
```

验证器会检查：

- Skill前置元数据和名称
- 必需文件及Markdown相对链接
- 安装引导触发规则与学习内容
- `agents/openai.yaml` 调用名称
- 测试案例格式、唯一ID和主要模式覆盖
- 残留TODO或占位文本

GitHub Actions会在每次push和pull request时运行同一验证器。

`tests/cases.json` 是行为契约测试集。它不会调用视频生成服务，而是记录输入场景和预期输出约束，适合人工回归或交给独立代理做前向测试。

## 能力边界

- 本Skill只产出策划、脚本、诊断和提示词文本。
- 不自动提交视频生成任务，不消耗积分，不承诺生成结果。
- 平台上传限制以当前Dreamina／即梦界面为准；仓库中的能力摘要有快照日期。
- 生成模型存在随机性，提示词只能降低身份漂移、物理错误和镜头冲突，不能保证每次结果完全一致。

## 开源与第三方说明

代码与原创Skill内容采用 [MIT License](LICENSE)。平台名称、商标和第三方文档归各自权利人所有。能力摘要和示例来源说明见 [NOTICE.md](NOTICE.md)。
