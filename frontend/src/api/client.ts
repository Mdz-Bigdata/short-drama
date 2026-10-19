import { acceptLanguage } from '../i18n';

/** The backend's local development address, used when nothing is configured. */
export const DEFAULT_API_BASE = 'http://localhost:8000';

/**
 * Resolve the backend origin from `VITE_API_BASE_URL`.
 *
 * Unset means local development. An explicitly empty value means the frontend
 * is served from the backend's own origin (behind one reverse proxy), so every
 * request becomes a same-origin relative path.
 */
export function resolveApiBase(configured: string | undefined): string {
  if (configured === undefined) return DEFAULT_API_BASE;
  return configured.trim().replace(/\/+$/, '');
}

export const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE_URL);

/**
 * Address of something the backend returned.
 *
 * The backend answers with paths relative to itself (`/media/…`, `/api/…`) and,
 * once media is served from a public address or a CDN, with complete URLs.
 * Only the relative form needs the API origin in front of it.
 */
export function apiUrl(pathOrUrl: string): string {
  return /^[a-z][a-z\d+.-]*:/i.test(pathOrUrl) || pathOrUrl.startsWith('//') ? pathOrUrl : `${API_BASE}${pathOrUrl}`;
}


export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** True when a request failed because the session is gone, not because the
 *  backend is down. The two need different messages and different recovery. */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

type UnauthorizedListener = () => void;

const unauthorizedListeners = new Set<UnauthorizedListener>();

/**
 * Subscribe to session expiry.
 *
 * Feature components share `apiRequest`, so without this every one of them
 * would swallow a 401 on its own and leave the user staring at a workbench
 * whose panels silently never load. The app shell listens here and returns
 * the user to the login gate instead.
 */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

function notifyUnauthorized() {
  for (const listener of [...unauthorizedListeners]) {
    try {
      listener();
    } catch {
      // One bad listener must not stop the others from resetting their state.
    }
  }
}


export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const hasJsonBody = options.body !== undefined && !(options.body instanceof FormData);
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      // The server answers in this language where it can; the interface picks it (src/i18n).
      'Accept-Language': acceptLanguage(),
      ...(hasJsonBody ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const data = await response.json() as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // Preserve the generic safe error when the server did not return JSON.
    }
    if (response.status === 401) notifyUnauthorized();
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}
