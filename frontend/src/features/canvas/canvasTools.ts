// The tools of the canvas's tool node. Mirrors backend/app/core/canvas_tools.py, which decides;
// a test on the backend side reads this file and fails when the two tables drift apart.

import { t } from '../../i18n';
import type { CanvasNode, EdgeKind, OutputType } from './canvasTypes';

export type ToolEngine = 'image' | 'vision' | 'text' | 'audio' | 'local';
export type ToolGroup = 'image' | 'video' | 'skill';
type InputTable = Partial<Record<OutputType, [EdgeKind, string]>>;

const IMAGE_INPUT: InputTable = { image: ['reference', 'ref_image'], style: ['reference', 'style'], text: ['dependency', 'prompt'], capture: ['reference', 'ref_capture'] };
const VIDEO_INPUT: InputTable = { video: ['reference', 'ref_video'] };
const TEXT_INPUT: InputTable = { text: ['dependency', 'prompt'], image: ['reference', 'ref_image'] };

export type ToolParam =
  | { key: string; label: () => string; type: 'select'; fallback: string; options: Array<[string, () => string]> }
  | { key: string; label: () => string; type: 'number'; fallback: number; min: number; max: number; step: number }
  /** A colour picker; `visible` hides it while another setting makes it moot. */
  | { key: string; label: () => string; type: 'color'; fallback: string; visible?: (params: Record<string, unknown>) => boolean };

export interface CanvasToolSpec {
  id: string;
  label: () => string;
  group: ToolGroup;
  engine: ToolEngine;
  output: 'image' | 'video' | 'audio' | 'text';
  inputs: InputTable;
  /** The free-text box and what it is for; a tool without one takes no words. */
  prompt?: () => string;
  params?: ToolParam[];
  /** What it actually does where the name could promise more. */
  note?: () => string;
  /** How to get a good result out of it: shown under its settings. */
  tip?: () => string;
}

const RATIO_OPTIONS: Array<[string, () => string]> = ['16:9', '9:16', '4:3', '3:4', '1:1', '21:9', '2:3'].map(value => [value, () => value]);

export const CANVAS_TOOLS: CanvasToolSpec[] = [
  { id: 'redraw', label: () => t('重绘'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('要改成什么样') },
  {
    id: 'outpaint', label: () => t('扩图'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补全的内容（可选）'),
    params: [{ key: 'ratio', label: () => t('目标画幅'), type: 'select', fallback: '16:9', options: RATIO_OPTIONS }],
  },
  {
    id: 'relight', label: () => t('打光'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'),
    params: [{
      key: 'light', label: () => t('光线'), type: 'select', fallback: 'golden',
      options: [
        ['golden', () => t('黄昏金光')], ['noon', () => t('正午顶光')], ['overcast', () => t('阴天柔光')], ['night', () => t('夜晚月光')],
        ['neon', () => t('霓虹')], ['rembrandt', () => t('伦勃朗')], ['backlit', () => t('强逆光')], ['candle', () => t('烛光')],
      ],
    }],
  },
  {
    id: 'multi_view', label: () => t('多视角'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'),
    params: [{
      key: 'view', label: () => t('视角'), type: 'select', fallback: 'three_quarter',
      options: [
        ['three_quarter', () => t('四分之三侧面')], ['front', () => t('正面')], ['left', () => t('左侧面')], ['right', () => t('右侧面')],
        ['back', () => t('背面')], ['top', () => t('俯视')], ['low', () => t('仰视')],
      ],
    }],
  },
  { id: 'style_transfer', label: () => t('风格转绘'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）') },
  {
    id: 'template_edit', label: () => t('模板改图'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('改成什么（换装、换色、表情、天气、加道具、加文字时必填）'),
    params: [{
      key: 'template', label: () => t('模板'), type: 'select', fallback: 'remove_people',
      options: [
        ['remove_people', () => t('去路人')], ['remove_text', () => t('去文字水印')], ['change_outfit', () => t('换服装')],
        ['change_expression', () => t('改表情')], ['change_weather', () => t('改天气时间')], ['add_prop', () => t('加道具')],
        ['empty_room', () => t('清空人物（留空房间）')], ['recolor_outfit', () => t('保衣型换色')], ['add_text', () => t('加一处文字')],
      ],
    }],
  },
  { id: 'enhance', label: () => t('高清修复'), group: 'image', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'), note: () => t('由图像模型重新生成，细节可能有细微变化') },
  {
    id: 'upscale_image', label: () => t('图片放大（本地）'), group: 'image', engine: 'local', output: 'image', inputs: IMAGE_INPUT,
    params: [{ key: 'factor', label: () => t('倍数'), type: 'select', fallback: '2', options: [['2', () => '2×'], ['3', () => '3×'], ['4', () => '4×']] }],
    note: () => t('本机插值放大，不增加真实细节；要补细节用「高清修复」'),
  },
  {
    id: 'grid_cell', label: () => t('取宫格'), group: 'image', engine: 'local', output: 'image', inputs: IMAGE_INPUT,
    params: [
      { key: 'rows', label: () => t('行'), type: 'number', fallback: 3, min: 1, max: 12, step: 1 },
      { key: 'columns', label: () => t('列'), type: 'number', fallback: 3, min: 1, max: 12, step: 1 },
      { key: 'cell', label: () => t('第几格'), type: 'number', fallback: 1, min: 1, max: 144, step: 1 },
    ],
  },
  { id: 'composite', label: () => t('贴回人物'), group: 'image', engine: 'local', output: 'image', inputs: IMAGE_INPUT, note: () => t('连三张图：生成好的新图、导演台的完整画面截图和它的人物遮罩；把人物贴回新图') },
  { id: 'reverse_prompt', label: () => t('反推提示词'), group: 'image', engine: 'vision', output: 'text', inputs: IMAGE_INPUT },
  { id: 'mark_detect', label: () => t('水印字幕检测'), group: 'image', engine: 'vision', output: 'text', inputs: IMAGE_INPUT },
  {
    id: 'video_upscale', label: () => t('视频放大（本地）'), group: 'video', engine: 'local', output: 'video', inputs: VIDEO_INPUT,
    params: [{ key: 'factor', label: () => t('倍数'), type: 'select', fallback: '2', options: [['1.5', () => '1.5×'], ['2', () => '2×'], ['3', () => '3×']] }],
    note: () => t('本机插值放大加锐化，不增加真实细节'),
  },
  {
    id: 'video_erase', label: () => t('区域擦除'), group: 'video', engine: 'local', output: 'video', inputs: VIDEO_INPUT,
    params: [
      {
        key: 'mode', label: () => t('做法'), type: 'select', fallback: 'delogo',
        options: [['delogo', () => t('无痕擦除（去字幕、去水印）')], ['blur', () => t('隐私模糊')], ['mosaic', () => t('马赛克')]],
      },
      {
        key: 'preset', label: () => t('选区'), type: 'select', fallback: 'custom',
        options: [['custom', () => t('按下面的数字')], ['bottom_band', () => t('底部字幕条（整行）')], ['top_band', () => t('顶部字幕条（整行）')]],
      },
      { key: 'x', label: () => t('左 %'), type: 'number', fallback: 0, min: 0, max: 100, step: 1 },
      { key: 'y', label: () => t('上 %'), type: 'number', fallback: 0, min: 0, max: 100, step: 1 },
      { key: 'w', label: () => t('宽 %'), type: 'number', fallback: 20, min: 0.5, max: 100, step: 1 },
      { key: 'h', label: () => t('高 %'), type: 'number', fallback: 10, min: 0.5, max: 100, step: 1 },
    ],
    note: () => t('无痕擦除用周围像素补上固定位置的字幕、台标或水印；隐私打码用模糊或马赛克；会移动的东西擦不掉'),
  },
  { id: 'audio_extract', label: () => t('提取音轨'), group: 'video', engine: 'local', output: 'audio', inputs: VIDEO_INPUT, note: () => t('取出原声，不区分人声和配乐') },
  { id: 'voice_isolate', label: () => t('人声分离'), group: 'video', engine: 'audio', output: 'audio', inputs: VIDEO_INPUT, note: () => t('由 ElevenLabs 去掉配乐和噪声，只留人声') },
  {
    id: 'frame_extract', label: () => t('抽帧'), group: 'video', engine: 'local', output: 'image', inputs: VIDEO_INPUT,
    params: [
      { key: 'at', label: () => t('位置'), type: 'select', fallback: 'first', options: [['first', () => t('第一帧')], ['last', () => t('最后一帧')], ['time', () => t('指定时间')]] },
      { key: 'seconds', label: () => t('秒'), type: 'number', fallback: 0, min: 0, max: 3600, step: 0.1 },
    ],
  },
  {
    id: 'to_gif', label: () => t('转动图'), group: 'video', engine: 'local', output: 'image', inputs: VIDEO_INPUT,
    params: [
      { key: 'seconds', label: () => t('时长（秒）'), type: 'number', fallback: 6, min: 0.5, max: 30, step: 0.5 },
      { key: 'width', label: () => t('宽度'), type: 'number', fallback: 480, min: 120, max: 960, step: 10 },
    ],
  },
  {
    id: 'sprite_frames', label: () => t('抠像序列帧'), group: 'video', engine: 'local', output: 'image', inputs: VIDEO_INPUT,
    // Defaults and bounds mirror backend/app/data/prompt/sprite_frames.json, which decides.
    params: [
      {
        key: 'key', label: () => t('底色'), type: 'select', fallback: 'auto',
        options: [['auto', () => t('自动（取四角的颜色）')], ['magenta', () => t('品红')], ['blue', () => t('蓝')], ['green', () => t('绿')], ['custom', () => t('自定义')]],
      },
      { key: 'key_hex', label: () => t('自定义颜色'), type: 'color', fallback: '#ff00ff', visible: params => params.key === 'custom' },
      { key: 'tolerance', label: () => t('容差'), type: 'number', fallback: 40, min: 0, max: 100, step: 1 },
      { key: 'fps', label: () => t('帧率（帧/秒）'), type: 'number', fallback: 12, min: 1, max: 30, step: 1 },
      { key: 'max_frames', label: () => t('最多帧数'), type: 'number', fallback: 120, min: 1, max: 240, step: 1 },
    ],
    note: () => t('本机把纯色背景抠成透明，输出一组同样大小的透明 PNG（ZIP）和一张精灵图；整段共用一个裁剪框、脚底对齐，回放时人物不抖'),
    tip: () => t('在纯色背景上生成的片段抠得最干净：背景色要远离人物的衣服、肤色和武器（穿绿色或蓝色衣服、拿银色刀刃的人物，品红通常比蓝、绿好），全身连脚都要在画面里'),
  },
  { id: 'shot_analysis', label: () => t('镜头分析'), group: 'video', engine: 'vision', output: 'text', inputs: VIDEO_INPUT, note: () => t('本机找切点，再由多模态模型看每个镜头') },
  { id: 'sketch', label: () => t('转线稿'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）') },
  { id: 'action_breakdown', label: () => t('拆动作'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('一句笼统的动作（也可以连文本）'), note: () => t('拆成起始姿态、主动作、身体联动、结束姿态四行，连到视频节点当提示词') },
  { id: 'link_design', label: () => t('设计接镜'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('上一镜和下一镜各是什么（也可以连文本）'), note: () => t('写出接法、两边切出和接入的状态、剪辑备注和检查项') },
  { id: 'frame_bridge', label: () => t('写首尾帧过渡'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('首帧和尾帧各是什么（也可以连文本）'), note: () => t('写出首帧走到尾帧的过渡，连到视频节点当提示词') },
  { id: 'script_write', label: () => t('写剧本'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('这场戏要讲什么（也可以连文本）') },
  {
    id: 'shot_table', label: () => t('拆镜头表'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('剧本（也可以连文本）'),
    // 0: as many as the script asks for (「镜头数：3」「三个镜头」), or as the story needs.
    params: [{ key: 'shots', label: () => t('镜头数（0 = 按剧本）'), type: 'number', fallback: 0, min: 0, max: 60, step: 1 }],
  },
  { id: 'svg_art', label: () => t('生成矢量图'), group: 'skill', engine: 'text', output: 'image', inputs: TEXT_INPUT, prompt: () => t('要画什么'), note: () => t('输出 SVG；多数图像和视频模型不接受它作参考图') },
  { id: 'html_page', label: () => t('生成网页'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('做什么页面'), note: () => t('只在隔离的预览框里显示，可以下载') },
  { id: 'frame_from_context', label: () => t('按上下文出首帧'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('这一镜要拍什么（也可以连文本）') },
  { id: 'set_background', label: () => t('换背景'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'), note: () => t('连两张图：先连主体，再连场景') },
  { id: 'scene_360', label: () => t('生成 360° 场景'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('描述这个地点') },
  { id: 'frame_review', label: () => t('画面审查'), group: 'skill', engine: 'vision', output: 'text', inputs: IMAGE_INPUT, prompt: () => t('这一镜应该是什么（可选）') },
  { id: 'beat_plan', label: () => t('拍点规划'), group: 'skill', engine: 'text', output: 'text', inputs: TEXT_INPUT, prompt: () => t('这段故事（也可以连文本）') },
  {
    id: 'character_extract', label: () => t('提取角色设定'), group: 'skill', engine: 'vision', output: 'text', inputs: TEXT_INPUT,
    prompt: () => t('连了图：写图里哪个人、叫什么（可选）；没连图：写角色描述'),
    note: () => t('从角色图或文字写出一段外貌设定：性别年龄、五官、面部标记、发型、体型、服装、配饰、画风，可以直接连到图像或视频节点当提示词'),
  },
  // 逆向拆解一张剧照：空间基底 + 配色卡 + 氛围建立，三个节点连起来用。
  { id: 'space_base', label: () => t('空间基底'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'), note: () => t('连一张剧照：去掉人物、道具等叙事元素，重建这个地点平常的样子，机位和透视不变') },
  {
    id: 'color_card', label: () => t('配色卡'), group: 'skill', engine: 'local', output: 'image', inputs: IMAGE_INPUT,
    note: () => t('连一张剧照，得到一条从暗到亮的纯色色块；再连一张自己的配色条，它的颜色也会算进去'),
    params: [{ key: 'colors', label: () => t('色块数'), type: 'number', fallback: 8, min: 6, max: 10, step: 1 }],
  },
  { id: 'mood_frame', label: () => t('氛围建立'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'), note: () => t('连三张图：空间基底、原始剧照、配色卡。空间照基底，光影照原图，配色照色卡') },
  // 换装：先取出整套衣服，再让人物只换这一套；底图不动，一次只换服装这一张图。
  { id: 'outfit_extract', label: () => t('服装提取'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'), note: () => t('连一张穿搭照：只取出整套衣服、鞋包和配饰，做成白底、没有真人和人台的平铺图') },
  {
    id: 'outfit_swap', label: () => t('换装'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'),
    note: () => t('连两张图：先连人物，再连服装图。只换衣服，脸、发型、身材、姿势和场景照人物图'),
    tip: () => t('换几套都从同一张人物底图出发，每次只换服装图，脸才不会一套比一套走样；服装图越干净，换上去越像'),
  },
  {
    id: 'reference_remake', label: () => t('参考复刻词'), group: 'skill', engine: 'local', output: 'text', inputs: TEXT_INPUT, prompt: () => t('补充说明（只学运镜时写新画面拍什么，必填）'),
    params: [{
      key: 'mode', label: () => t('做法'), type: 'select', fallback: 'swap',
      options: [['swap', () => t('换人（动作运镜照参考视频）')], ['camera', () => t('只学运镜和节奏')], ['outfit', () => t('换装过场')]],
    }],
    note: () => t('本机拼出一段固定写法，不调用模型；把它连到视频节点当提示词，参考视频和参考图也连到那个视频节点'),
    tip: () => t('换人：人物正面图连在最前；片子里有转头和侧脸时，再连一张同一个人的侧脸图。换装过场：依次连换装前、换装后、没有人的同一个房间三张图。参考视频里有真人的脸，先用「区域擦除」打上马赛克，不然多半过不了视频模型的人脸审核'),
  },
  // 招式分解图：同一个人逐格摆出一组招式，给后面的图像或视频节点当动作参考（招式组与 backend move_sheets.json 的 sets 一致）。
  {
    id: 'move_sheet', label: () => t('招式分解图'), group: 'skill', engine: 'image', output: 'image', inputs: IMAGE_INPUT, prompt: () => t('补充说明（可选）'),
    params: [{
      key: 'set', label: () => t('招式组'), type: 'select', fallback: 'sword',
      options: [['staff', () => t('棍法八式')], ['sword', () => t('长剑八式')], ['sword_basics_a', () => t('剑术基本功（上）八式')], ['sword_basics_b', () => t('剑术基本功（下）五式')], ['sword_duel', () => t('对剑五式')], ['saber', () => t('横刀八式')], ['saber_basics_a', () => t('刀术基本功（上）八式')], ['saber_basics_b', () => t('刀术基本功（下）八式')], ['saber_duel', () => t('对刀五式')], ['spear', () => t('长枪八式')], ['bare', () => t('徒手攻防八式')], ['qinggong', () => t('轻功八式')], ['breakout', () => t('群战突围五式')], ['chase', () => t('轻功追逐五式')], ['spear_charge', () => t('长枪破阵五式')], ['archery', () => t('弓箭五式')], ['spell', () => t('法术近战五式')], ['finisher', () => t('大招五拍')]],
    }],
    note: () => t('连一张人物图：同一个人按选的一组招式逐格摆出来，图上不出字；把它连到图像或视频节点当动作参考'),
    tip: () => t('人物图用全身、手里已经拿着兵器的那张，兵器的长短和样子才不会每格不一样；一个视频节点只挑其中一两格的动作来写，不要把整组塞进一条提示词'),
  },
];

const BY_ID = new Map(CANVAS_TOOLS.map(tool => [tool.id, tool]));
export const DEFAULT_TOOL = 'redraw';

export function toolById(id: unknown): CanvasToolSpec | undefined {
  return BY_ID.get(String(id ?? DEFAULT_TOOL));
}

export function toolOf(node: Pick<CanvasNode, 'payload'>): CanvasToolSpec | undefined {
  return toolById(node.payload.params?.tool);
}

export function groupLabel(group: ToolGroup) {
  switch (group) {
    case 'image': return t('图像工具');
    case 'video': return t('视频工具');
    case 'skill': return t('一键技能');
  }
}

/** Who does the work and whether it costs anything: shown on the node, before anyone presses run. */
export function engineLabel(engine: ToolEngine) {
  switch (engine) {
    case 'image': return t('图像模型 · 计费');
    case 'vision': return t('多模态模型 · 计费');
    case 'text': return t('文本模型 · 计费');
    case 'audio': return t('ElevenLabs · 计费');
    case 'local': return t('本机处理 · 免费');
  }
}
