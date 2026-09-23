import type { ElementKind } from '../elements/elementTypes';
import type { ActorSheetCellGroup, ActorSheetCellKey } from './types';

export const characterAssetTabLabels: Record<ElementKind, string> = {
  actor: '数字演员',
  scene: '拍摄场地',
  prop: '拍摄道具',
  costume: '服装',
  effect: '特效',
};

/** 设定集 25 格的中文标签，逐条对应 docs/actor-sheet/IMPLEMENTATION.md 的取景表。 */
export const actorSheetCellLabels: Record<ActorSheetCellKey, string> = {
  portrait: '大正面近景',
  full_body: '正面全身立绘',
  front: '正面全身',
  profile: '侧面全身',
  back: '背面全身',
  // 元素拆解 第 1 行
  element_shoe: '鞋履',
  element_waist: '腰部扣环',
  element_wrist: '护腕手部',
  element_collar: '领口肩部刺绣',
  // 元素拆解 第 2 行
  element_fabric: '面料微距',
  element_hair: '发饰拆解',
  element_hand: '手部姿态',
  element_hem: '裙摆刺绣',
  // 细节矩阵 第 1 行
  face_front: '正脸特写',
  face_three_quarter: '3-4侧脸',
  face_back_hair: '后脑发饰',
  // 细节矩阵 第 2 行
  detail_collar: '领口肩颈',
  detail_chest: '前襟胸部纹样',
  detail_waist_knot: '腰部束结',
  // 细节矩阵 第 3 行
  detail_cuff: '袖口末端',
  detail_texture: '材质微距',
  detail_back_tie: '背部暗扣系带',
  // 细节矩阵 第 4 行
  detail_shoe: '鞋履足部',
  detail_eye: '眼妆微距',
  detail_accessory: '动态姿态配件',
};

/** 「细节」页签只展示这两组：元素拆解 8 格 + 细节矩阵 12 格。 */
export const actorSheetDetailGroups = [
  { group: 'elements', label: '元素拆解' },
  { group: 'detail_matrix', label: '细节矩阵' },
] as const satisfies readonly { group: ActorSheetCellGroup; label: string }[];
