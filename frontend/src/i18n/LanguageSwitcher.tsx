import { Languages } from 'lucide-react';

import { LOCALES, setLocale, useLocale, type Locale } from './index';

/** The interface language picker; the choice is remembered in this browser. */
export function LanguageSwitcher({ className = '' }: { className?: string }) {
  const locale = useLocale();
  return (
    <label className={`language-switcher ${className}`.trim()}>
      <Languages size={15} aria-hidden="true" />
      <select aria-label="界面语言 / Language / Ngôn ngữ" value={locale} onChange={event => setLocale(event.target.value as Locale)}>
        {LOCALES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>
  );
}
