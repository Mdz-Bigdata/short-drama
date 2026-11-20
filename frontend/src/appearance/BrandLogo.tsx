import type { ReactNode } from 'react';

import { apiUrl } from '../api/client';
import { PRODUCT_NAME } from '../features/workbench/agentBrand';
import { currentAppearance } from './appearance';
import './BrandLogo.css';

/** The deployment's logo in its frame, or `fallback` (nothing by default) when none was uploaded. */
export function BrandLogo({ className = '', fallback = null }: { className?: string; fallback?: ReactNode }) {
  const appearance = currentAppearance();
  const logo = appearance?.assets.logo;
  if (!logo) return <>{fallback}</>;
  return (
    <img
      className={`brand-logo brand-logo--${appearance.logo_frame} ${className}`.trim()}
      src={apiUrl(logo)} alt={PRODUCT_NAME} draggable={false}
    />
  );
}
