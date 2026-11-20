import { useEffect, useState } from 'react';
import { HardDrive } from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { ASSETS_CHANGED_EVENT } from './assetEvents';
import { formatBytes } from './storageFormat';
import './StorageMeter.css';

/** The account's asset library against its limits (GET /api/elements/storage-usage). */
export interface StorageUsage {
  used_bytes: number;
  quota_bytes: number;
  remaining_bytes: number;
  asset_count: number;
  asset_quota: number;
  remaining_assets: number;
  share: number;
  level: 'ok' | 'warning' | 'danger';
}

/**
 * How full the asset library is, before an upload is turned down for it: used and total bytes, what
 * is left, and the number of assets. Turns to a warning at 70% and to danger at 90% of the tighter limit.
 */
export function StorageMeter() {
  const [usage, setUsage] = useState<StorageUsage | null>(null);

  useEffect(() => {
    let live = true;
    const load = () => {
      apiRequest<StorageUsage>('/api/elements/storage-usage')
        .then(answer => { if (live) setUsage(answer); })
        // The meter is a convenience: a failed read leaves the page as it was.
        .catch(() => undefined);
    };
    load();
    window.addEventListener(ASSETS_CHANGED_EVENT, load);
    return () => {
      live = false;
      window.removeEventListener(ASSETS_CHANGED_EVENT, load);
    };
  }, []);

  if (!usage) return null;
  const percent = Math.round(usage.share * 100);
  return (
    <div
      className={`storage-meter storage-meter--${usage.level}`}
      role="group"
      aria-label={t('素材库容量')}
      title={t('剩余 {left}，还可再放 {assets} 个资产', { left: formatBytes(usage.remaining_bytes), assets: usage.remaining_assets })}
    >
      <HardDrive size={15} aria-hidden="true" />
      <div
        className="storage-meter__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={t('素材库容量')}
      >
        <span style={{ width: `${Math.max(2, percent)}%` }} />
      </div>
      <span className="storage-meter__text">
        {t('已用 {used} / 共 {total}', { used: formatBytes(usage.used_bytes), total: formatBytes(usage.quota_bytes) })}
        <em>{t('资产 {count} / {limit} 个', { count: usage.asset_count, limit: usage.asset_quota })}</em>
      </span>
    </div>
  );
}
