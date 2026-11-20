import { API_BASE, apiUrl } from '../api/client';
import { applyBrand, DEFAULT_PRODUCT_NAME } from '../features/workbench/agentBrand';

export type LogoFrame = 'rounded' | 'square' | 'circle' | 'none';
export type AppearanceText = 'brand_name' | 'login_tagline' | 'lobby_tagline' | 'assistant_name';

/** What GET /api/public/appearance answers: set text or null, the logo frame, and versioned image addresses. */
export interface PublicAppearance {
  brand_name: string | null;
  login_tagline: string | null;
  lobby_tagline: string | null;
  assistant_name: string | null;
  logo_frame: LogoFrame;
  assets: Partial<Record<'logo' | 'favicon', string>>;
  customised: boolean;
}

const FRAMES: LogoFrame[] = ['rounded', 'square', 'circle', 'none'];
const TEXT: AppearanceText[] = ['brand_name', 'login_tagline', 'lobby_tagline', 'assistant_name'];
/** Long enough for a slow first answer; short enough that a dead backend does not hold the login page back. */
export const APPEARANCE_TIMEOUT_MS = 2500;

let current: PublicAppearance | null = null;

/** The appearance in use; null means the built-in one. */
export function currentAppearance(): PublicAppearance | null {
  return current;
}

export function isPublicAppearance(value: unknown): value is PublicAppearance {
  if (!value || typeof value !== 'object') return false;
  const found = value as Record<string, unknown>;
  const assets = found.assets as Record<string, unknown> | undefined;
  return TEXT.every(key => found[key] === null || typeof found[key] === 'string')
    && FRAMES.includes(found.logo_frame as LogoFrame)
    && !!assets && typeof assets === 'object'
    && Object.values(assets).every(url => typeof url === 'string' && url.startsWith('/api/public/appearance/assets/'));
}

/** The deployment's appearance, or null to use the built-in one (no answer in time, an error, or a malformed answer). */
export async function loadAppearance(timeoutMs = APPEARANCE_TIMEOUT_MS): Promise<PublicAppearance | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}/api/public/appearance`, { signal: controller.signal });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return isPublicAppearance(body) ? body : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** Put an appearance in use: the brand names, the page title and the page icon. */
export function applyAppearance(value: PublicAppearance | null, doc: Document = document): void {
  current = value && value.customised ? value : null;
  applyBrand(current?.brand_name ?? null, current?.assistant_name ?? null);
  if (current?.brand_name && doc.title.includes(DEFAULT_PRODUCT_NAME)) {
    doc.title = doc.title.split(DEFAULT_PRODUCT_NAME).join(current.brand_name);
  }
  const icon = current?.assets.favicon;
  if (icon) {
    const link = doc.querySelector<HTMLLinkElement>('link[rel~="icon"]') ?? doc.head.appendChild(doc.createElement('link'));
    link.rel = 'icon';
    link.removeAttribute('type');
    link.href = apiUrl(icon);
  }
}

/** Read and apply the appearance before the first render. Never rejects. */
export async function bootstrapAppearance(): Promise<void> {
  applyAppearance(await loadAppearance());
}

/** A line of brand text the deployment set, else the interface's own (translated) wording. */
export function brandText(field: Exclude<AppearanceText, 'brand_name'>, fallback: string): string {
  return current?.[field] || fallback;
}
