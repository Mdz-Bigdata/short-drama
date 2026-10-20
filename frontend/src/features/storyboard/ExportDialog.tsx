import { useEffect, useMemo, useState } from 'react';
import { ClipboardCopy, Download, Loader2, X } from 'lucide-react';

import { apiRequest } from '../../api/client';
import './ExportDialog.css';
import { t } from '../../i18n';

/** 单条提示词时长：模型一次拿得住的内容量，不是简单改秒数。 */
const PACKAGE_SECONDS = [10, 15, 20, 30] as const;
const VARIANTS = [
  { id: 'standard', label: '标准分包', hint: '每条自带锁与负面词，可单独粘贴' },
  { id: 'continuous', label: '连续镜头', hint: '一条动作链，禁止切镜' },
  { id: 'fight', label: '武戏', hint: '整体战斗设定 + 短而不均的攻防节拍' },
  { id: 'script_doc', label: '分段脚本', hint: '资产清单 + 完整台词本 + Shot 逐镜' },
] as const;
const DELIVERIES = ['正常', '急切', '沉重'] as const;

type Variant = (typeof VARIANTS)[number]['id'];
type Kind = 'packages' | 'sheets';

interface PackagesResponse {
  text: string;
  plan: { packages: unknown[]; total_seconds: number; warnings: string[] };
}

interface SheetsResponse {
  markdown: string;
  sheets: { warnings: string[] };
}

interface ExportDialogProps {
  taskId: string;
  sceneId: string;
  kind: Kind;
  onClose: () => void;
}

export function ExportDialog({ taskId, sceneId, kind, onClose }: ExportDialogProps) {
  const [packageSeconds, setPackageSeconds] = useState<number>(15);
  const [variant, setVariant] = useState<Variant>('standard');
  const [delivery, setDelivery] = useState<string>('正常');
  const [text, setText] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState('');
  // 每次换设置都由控件自己置为「编译中」；effect 里只在回调里改状态，不做同步 setState。
  const [busy, setBusy] = useState(true);
  const [copied, setCopied] = useState(false);

  const path = useMemo(() => (
    kind === 'packages'
      ? `/api/drama/${taskId}/prompt-packages?scene_id=${encodeURIComponent(sceneId)}`
        + `&package_seconds=${packageSeconds}&variant=${variant}&delivery=${encodeURIComponent(delivery)}`
      : `/api/drama/${taskId}/asset-sheets`
  ), [taskId, sceneId, kind, packageSeconds, variant, delivery]);

  useEffect(() => {
    let cancelled = false;
    apiRequest<PackagesResponse | SheetsResponse>(path)
      .then(payload => {
        if (cancelled) return;
        setError('');
        if ('text' in payload) {
          setText(payload.text);
          setWarnings(payload.plan.warnings || []);
        } else {
          setText(payload.markdown);
          setWarnings(payload.sheets.warnings || []);
        }
      })
      .catch((issue: unknown) => {
        if (!cancelled) setError(issue instanceof Error ? issue.message : '导出失败');
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => { cancelled = true; };
  }, [path]);

  const copy = () => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    });
  };

  const download = () => {
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = kind === 'packages' ? `${sceneId || 'episode'}-prompts.md` : `${taskId}-assets.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="export-dialog" role="dialog" aria-label={kind === 'packages' ? t('提示词分包') : t('资产设定图')} aria-modal="true">
      <div className="export-dialog__panel">
        <header className="export-dialog__head">
          <h2>{kind === 'packages' ? t('提示词分包') : t('资产设定图')}</h2>
          <button type="button" onClick={onClose} aria-label={t('关闭')}><X aria-hidden="true" /></button>
        </header>

        {kind === 'packages' && (
          <div className="export-dialog__controls">
            <label>
              {t('单条时长')}
              <select
                value={packageSeconds}
                onChange={event => { setBusy(true); setPackageSeconds(Number(event.target.value)); }}
              >
                {PACKAGE_SECONDS.map(seconds => <option key={seconds} value={seconds}>{seconds} 秒</option>)}
              </select>
            </label>
            <label>
              {t('形态')}
              <select
                value={variant}
                onChange={event => { setBusy(true); setVariant(event.target.value as Variant); }}
              >
                {VARIANTS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>
              {t('语速档')}
              <select
                value={delivery}
                onChange={event => { setBusy(true); setDelivery(event.target.value); }}
              >
                {DELIVERIES.map(item => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <span className="export-dialog__hint">{VARIANTS.find(item => item.id === variant)?.hint}</span>
          </div>
        )}

        {error && <p className="export-dialog__error">{error}</p>}
        {warnings.length > 0 && (
          <ul className="export-dialog__warnings">
            {warnings.map(warning => <li key={warning}>{warning}</li>)}
          </ul>
        )}

        <pre className="export-dialog__text">{busy ? t('正在编译…') : text}</pre>

        <footer className="export-dialog__foot">
          <button type="button" onClick={copy} disabled={!text || busy}>
            <ClipboardCopy aria-hidden="true" /> {copied ? t('已复制') : t('复制全文')}
          </button>
          <button type="button" onClick={download} disabled={!text || busy}>
            <Download aria-hidden="true" /> {t('下载 Markdown')}
          </button>
          {busy && <Loader2 className="export-dialog__spin" aria-hidden="true" />}
        </footer>
      </div>
    </div>
  );
}
