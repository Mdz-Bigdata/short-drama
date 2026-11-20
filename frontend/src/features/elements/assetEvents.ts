/**
 * 资产变了(改名、改描述、换图、恢复旧版本)：告诉正在显示镜头的界面重新读一遍。
 *
 * 用 window 事件，和 api/client.ts 的 billing-required 同一做法：元素库和分镜、镜头工作区
 * 互不认识，谁改了资产谁发，谁显示镜头谁听。
 */
import { useEffect, useRef } from 'react';

export const ASSETS_CHANGED_EVENT = 'novara:assets-changed';

export interface AssetsChangedDetail {
  elementId?: string;
  kind?: string;
  name?: string;
  reason: 'rename' | 'edit' | 'image' | 'restore' | 'delete' | 'create';
  /** 后端标成过期的镜头和片段数，界面可据此提示「N 个镜头需重跑」。 */
  shotsMarked?: number;
  clipsMarked?: number;
}

export function notifyAssetsChanged(detail: AssetsChangedDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<AssetsChangedDetail>(ASSETS_CHANGED_EVENT, { detail }));
}

/** 资产变了就调一次 callback；callback 可以每次渲染都不同，不会重复订阅。 */
export function useAssetsChanged(callback: (detail: AssetsChangedDetail) => void): void {
  const latest = useRef(callback);
  useEffect(() => { latest.current = callback; }, [callback]);
  useEffect(() => {
    const handler = (event: Event) => latest.current((event as CustomEvent<AssetsChangedDetail>).detail);
    window.addEventListener(ASSETS_CHANGED_EVENT, handler);
    return () => window.removeEventListener(ASSETS_CHANGED_EVENT, handler);
  }, []);
}
