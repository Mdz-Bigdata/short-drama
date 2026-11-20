import type { ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';

import { t } from '../../i18n';


export function Problem({ text }: { text: string }) {
  return text ? <div className="inline-error" role="alert">{text}</div> : null;
}

export function Waiting() {
  return <div className="empty-library"><LoaderCircle className="spin" /> {t('正在加载…')}</div>;
}

export function Stat({ name, value, hint }: { name: string; value: ReactNode; hint?: string }) {
  return <div className="finance-stat"><span>{name}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}
