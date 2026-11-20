import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Download, LoaderCircle, Stethoscope, XCircle } from 'lucide-react';

import { API_BASE, apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { changedSinceStartup, type DiagnosticsResponse, type Report } from './diagnosticsReport';
import './SystemDiagnostics.css';


const ICON = { ok: CheckCircle2, warning: AlertTriangle, error: XCircle } as const;

function verdict(report: Report): string {
  if (report.status === 'ok') return t('{count} 项全部正常', { count: report.checks.length });
  return t('{errors} 项有问题，{warnings} 项需留意', { errors: report.counts.error, warnings: report.counts.warning });
}

async function saveBundle(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/platform/diagnostics/bundle`, { credentials: 'include' });
  if (!response.ok) throw new Error(t('诊断包导出失败 ({status})', { status: response.status }));
  const named = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '');
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = named ? named[1] : 'diagnostics.zip';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** The server's self-check, run on demand, and the masked bundle to hand to whoever helps. */
export function SystemDiagnostics() {
  const [report, setReport] = useState<DiagnosticsResponse | null>(null);
  const [busy, setBusy] = useState<'' | 'check' | 'bundle'>('');
  const [error, setError] = useState('');

  const act = async (kind: 'check' | 'bundle') => {
    setBusy(kind);
    setError('');
    try {
      if (kind === 'check') setReport(await apiRequest<DiagnosticsResponse>('/api/platform/diagnostics'));
      else await saveBundle();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('自检没有完成'));
    } finally {
      setBusy('');
    }
  };

  const changed = report ? changedSinceStartup(report, report.startup) : [];

  return (
    <section className="system-diagnostics" aria-labelledby="system-diagnostics-title">
      <div className="system-diagnostics__head">
        <div>
          <h4 id="system-diagnostics-title"><Stethoscope size={16} aria-hidden="true" /> {t('问题诊断')}</h4>
          <p>{t('检查磁盘、两个库、FFmpeg、密钥和模型配置；诊断包里的密钥、网址参数、邮箱和手机号都已遮去，不含任何项目内容。')}</p>
        </div>
        <div className="system-diagnostics__actions">
          <button type="button" onClick={() => void act('check')} disabled={busy !== ''}>
            {busy === 'check' ? <LoaderCircle className="spin" size={15} /> : <Stethoscope size={15} />}
            {t('运行自检')}
          </button>
          <button type="button" onClick={() => void act('bundle')} disabled={busy !== ''}>
            {busy === 'bundle' ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}
            {t('导出诊断包')}
          </button>
        </div>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {report && (
        <>
          <p className={`system-diagnostics__verdict system-diagnostics__verdict--${report.status}`} role="status">
            {verdict(report)}
            {report.startup && ` · ${t('启动时：{verdict}', { verdict: verdict(report.startup) })}`}
            {changed.length > 0 && ` · ${t('启动后有变化：{names}', { names: changed.map(item => item.label).join('、') })}`}
          </p>
          <ul className="system-diagnostics__list">
            {report.checks.map(item => {
              const Icon = ICON[item.status];
              return (
                <li key={item.id} className={`system-diagnostics__item system-diagnostics__item--${item.status}`}>
                  <Icon size={16} aria-hidden="true" />
                  <strong>{item.label}</strong>
                  <span>{item.detail}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
