import { Box3, Vector3, type Object3D } from 'three';

/** 地面网格跟着模型的大小走：一只茶杯和一条街不能用同一把格子。 */
export interface FloorGrid {
  /** 细格边长。 */
  cellSize: number;
  /** 粗格边长，五个细格。 */
  sectionSize: number;
  /** 网格从相机脚下向外淡出的距离。 */
  fadeDistance: number;
  /** 网格比模型底面低这么多，免得和模型自带的地面叠在一起闪。 */
  drop: number;
}

// 量不出大小(空模型)时按两米算。
const FALLBACK_SPAN = 2;

/** 把一个长度收成 1 / 2 / 5 × 10ⁿ，格子边长才是整数好读。 */
export function niceStep(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const fraction = value / magnitude;
  const rounded = fraction < 1.5 ? 1 : fraction < 3.5 ? 2 : fraction < 7.5 ? 5 : 10;
  return rounded * magnitude;
}

/** 模型最长边 → 地面网格：最长边上大约排六个细格，网格铺到模型十倍远处淡出。 */
export function floorGridFor(largest: number): FloorGrid {
  const span = Number.isFinite(largest) && largest > 0 ? largest : FALLBACK_SPAN;
  const cellSize = niceStep(span / 6);
  return { cellSize, sectionSize: cellSize * 5, fadeDistance: span * 10, drop: span / 500 };
}

/** 模型包围盒的最长边；空模型返回 0。 */
export function largestSide(object: Object3D): number {
  const size = new Box3().setFromObject(object).getSize(new Vector3());
  return Math.max(size.x, size.y, size.z);
}
