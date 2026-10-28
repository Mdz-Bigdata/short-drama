/**
 * Interface language: 中文 (the source text), English, Tiếng Việt.
 *
 * The Chinese text a component renders is its own key: `t('保存')` returns 保存 in Chinese
 * and the dictionary entry in English or Vietnamese, so a screen is translated by wrapping
 * its text and adding entries, and anything not yet translated still reads in Chinese.
 * `{name}` / `{0}` placeholders are filled from the second argument.
 *
 * Chinese needs no dictionary, so the English and Vietnamese ones (a third of the app's
 * first-load script) are fetched only when that language is chosen: `setLocale` loads it
 * before switching, and the entry point loads a remembered language before the first render.
 */
import { useSyncExternalStore } from 'react';

export type Locale = 'zh-CN' | 'en' | 'vi';

export const LOCALES: ReadonlyArray<{ id: Locale; label: string; htmlLang: string }> = [
  { id: 'zh-CN', label: '中文', htmlLang: 'zh-CN' },
  { id: 'en', label: 'English', htmlLang: 'en' },
  { id: 'vi', label: 'Tiếng Việt', htmlLang: 'vi' },
];

type Translated = Exclude<Locale, 'zh-CN'>;

const LOADERS: Record<Translated, () => Promise<Record<string, string>>> = {
  en: () => import('./en').then(module => module.en),
  vi: () => import('./vi').then(module => module.vi),
};

/** The dictionaries loaded so far; a language missing here reads in Chinese until it loads. */
export const DICTIONARIES: Partial<Record<Translated, Record<string, string>>> = {};

/** Fetch a language's dictionary once; Chinese and already-loaded languages resolve at once. */
export async function loadLocale(locale: Locale): Promise<void> {
  if (locale === 'zh-CN' || DICTIONARIES[locale]) return;
  DICTIONARIES[locale] = await LOADERS[locale]();
}

const STORAGE_KEY = 'ui.locale';
const listeners = new Set<() => void>();

function isLocale(value: unknown): value is Locale {
  return LOCALES.some(item => item.id === value);
}

function initialLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch {
    // Storage may be unavailable (private mode); the default applies.
  }
  // Chinese until the person picks another language: the browser's language alone never switches it.
  return 'zh-CN';
}

let current: Locale = typeof window === 'undefined' ? 'zh-CN' : initialLocale();

export function getLocale(): Locale {
  return current;
}

/** Switch the interface language, loading its dictionary first so nothing flashes in Chinese. */
export async function setLocale(next: Locale): Promise<void> {
  if (!isLocale(next) || next === current) return;
  await loadLocale(next);
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Not persisting is fine; the choice still applies to this page.
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = LOCALES.find(item => item.id === next)?.htmlLang ?? 'zh-CN';
  }
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-render the calling component whenever the language changes. */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribe, getLocale, getLocale);
}

type Vars = Record<string, string | number> | ReadonlyArray<string | number>;

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => {
    const value = Array.isArray(vars) ? vars[Number(key)] : (vars as Record<string, string | number>)[key];
    return value === undefined || value === null ? whole : String(value);
  });
}

/** The text in the current language; the Chinese source when no translation exists yet. */
export function t(source: string, vars?: Vars, locale: Locale = current): string {
  const translated = locale === 'zh-CN' ? source : (DICTIONARIES[locale]?.[source] ?? source);
  return fill(translated, vars);
}

/** The Accept-Language value the API client sends. */
export function acceptLanguage(): string {
  return current === 'zh-CN' ? 'zh-CN,zh;q=0.9' : `${current},zh-CN;q=0.5`;
}
