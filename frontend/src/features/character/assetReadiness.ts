import type { ElementKind } from '../elements/elementTypes';

export interface AssetKindReadiness {
  label: string;
  total: number;
  ready: number;
  missing: string[];
  enforced?: boolean;
}

/** Whether every actor, scene, prop, costume and effect has a reference image. */
export interface AssetReadiness {
  complete: boolean;
  library_error?: string;
  kinds: Partial<Record<ElementKind, AssetKindReadiness>>;
}

export function assetGateReason(readiness: AssetReadiness | null): string {
  if (!readiness || readiness.complete) return '';
  if (readiness.library_error) return `资产库读取失败（${readiness.library_error}），无法确认拍摄资产是否齐备。`;
  const parts = Object.values(readiness.kinds)
    .filter((kind): kind is AssetKindReadiness => Boolean(kind) && kind!.enforced !== false && kind!.missing.length > 0)
    .map(kind => `${kind.label} ${kind.ready}/${kind.total}（缺：${kind.missing.slice(0, 5).join('、')}${kind.missing.length > 5 ? '…' : ''}）`);
  return parts.length
    ? `拍摄资产尚未齐备：${parts.join('；')}。全部生成完成后才能进入分镜师。`
    : '拍摄资产尚未全部生成，完成后才能进入分镜师。';
}
