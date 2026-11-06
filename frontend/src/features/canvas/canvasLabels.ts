import { t } from '../../i18n';
import type { ConnectResult } from './canvasGraph';
import type { CanvasNode, NodeKind, OutputType, RunStatus } from './canvasTypes';

export function kindLabel(kind: NodeKind) {
  switch (kind) {
    case 'artifact': return t('产物');
    case 'candidate': return t('候选');
    case 'media': return t('上传素材');
    case 'note': return t('文本注释');
    case 'group': return t('分组');
    case 'image_gen': return t('图像生成');
    case 'video_gen': return t('视频生成');
    case 'audio_gen': return t('音频生成');
    case 'video_compose': return t('视频合成');
    case 'style_ref': return t('风格参考');
    case 'panorama': return t('360° 全景');
    case 'previz': return t('预演');
    case 'tool': return t('工具');
  }
}

export function outputLabel(type: OutputType) {
  switch (type) {
    case 'image': return t('图片');
    case 'video': return t('视频');
    case 'audio': return t('音频');
    case 'text': return t('文本');
    case 'style': return t('风格');
    case 'capture': return t('预演截取');
  }
}

export function roleLabel(role: string | undefined) {
  switch (role) {
    case 'ref_image': return t('参考图');
    case 'first_frame': return t('首帧');
    case 'last_frame': return t('尾帧');
    case 'ref_video': return t('参考视频');
    case 'continue_from': return t('接上一段尾帧（同一镜头）');
    case 'ref_audio': return t('参考音频');
    case 'ref_capture': return t('预演参考');
    case 'style': return t('风格');
    case 'prompt': return t('提示词');
    case 'clip': return t('片段');
    case 'soundtrack': return t('配音轨');
    case 'style_image': return t('风格图');
    case 'equirect': return t('全景图');
    case 'blockout_image': return t('白模参考图');
    default: return role ?? '';
  }
}

export function statusLabel(status: RunStatus) {
  switch (status) {
    case 'queued': return t('排队中');
    case 'running': return t('运行中');
    case 'done': return t('完成');
    case 'failed': return t('失败');
    case 'cancelled': return t('已取消');
    case 'skipped': return t('已跳过');
  }
}

export function refusalMessage(reason: Extract<ConnectResult, { ok: false }>['reason']) {
  switch (reason) {
    case '自连': return t('节点不能连接自己');
    case '无输出': return t('这个节点还没有可以输出的内容');
    case '不接受': return t('目标节点不接受这种输入');
    case '成环': return t('这条连接会形成环');
    case '已连接': return t('这两个节点已经连上了');
  }
}

export function nodeTitle(node: CanvasNode) {
  return node.payload.label || node.payload.title || kindLabel(node.kind);
}
