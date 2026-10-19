/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Unset: local development backend. Empty: same origin as the page. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
