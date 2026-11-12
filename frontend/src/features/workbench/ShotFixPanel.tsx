import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { shotPath, type ShotVisualRecord } from './shotVisual';
import './ShotFixPanel.css';

/** 样片与局部修的字段（后端 ShotVisualRecord 上新加的几项）。 */
export interface ShotFixFields {
  draft_resolution?: string;
  draft_upscaled?: boolean;
  hd_retake?: boolean;
  retake_from?: number | null;
  retaken_from?: number | null;
  repair?: { status: 'running' | 'done' | 'failed'; note?: string; error?: string } | null;
}

type FixShot = ShotVisualRecord & ShotFixFields;

/** 九宫格：区域修补先选画面上的哪一块。 */
const REGIONS: ReadonlyArray<readonly [label: string, x: number, y: number]> = [
  ['左上', 0, 0], ['上中', 1 / 3, 0], ['右上', 2 / 3, 0],
  ['左中', 0, 1 / 3], ['正中', 1 / 3, 1 / 3], ['右中', 2 / 3, 1 / 3],
  ['左下', 0, 2 / 3], ['下中', 1 / 3, 2 / 3], ['右下', 2 / 3, 2 / 3],
];

interface ToggleProps<W> {
  taskId: string;
  enabled: boolean;
  locked: boolean;
  onWorkspace: (workspace: W) => void;
  onError: (message: string) => void;
}

/** 样片模式：第 5 阶段按 480P 出片，看过再逐镜出高清。 */
export function DraftModeToggle<W>({ taskId, enabled, locked, onWorkspace, onError }: ToggleProps<W>) {
  const [busy, setBusy] = useState(false);
  const flip = async (next: boolean) => {
    setBusy(true);
    try {
      onWorkspace(await apiRequest<W>(`/api/drama/${encodeURIComponent(taskId)}/shots/draft-mode`, {
        method: 'PUT', body: JSON.stringify({ enabled: next }),
      }));
    } catch (err) {
      onError(err instanceof Error ? err.message : t('样片模式切换失败'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="shot-fix__draft-toggle" title={t('先按 480P 出样片看构图、动作和衔接，满意的镜头再逐镜出高清，省视频费用。')}>
      <input type="checkbox" checked={enabled} disabled={locked || busy} onChange={event => { void flip(event.target.checked); }} />
      {t('样片模式（480P）')}
    </label>
  );
}

interface PanelProps<W> {
  taskId: string;
  shot: FixShot;
  repairSupported: boolean;
  locked: boolean;
  onWorkspace: (workspace: W) => void;
  onNotice: (text: string) => void;
  onError: (message: string) => void;
}

/** 一镜出片之后：样片转高清、从某一秒往后重做、区域修补。穿帮只修出错的那一段或那一块，不整段重抽。 */
export function ShotFixPanel<W extends { shots?: FixShot[] }>({ taskId, shot, repairSupported, locked, onWorkspace, onNotice, onError }: PanelProps<W>) {
  const [busy, setBusy] = useState(false);
  const [retakeAt, setRetakeAt] = useState('');
  const [retakeNote, setRetakeNote] = useState('');
  const [repairOpen, setRepairOpen] = useState(false);
  const [region, setRegion] = useState(4);
  const [repairNote, setRepairNote] = useState('');
  const [repairFrom, setRepairFrom] = useState('');
  const [repairTo, setRepairTo] = useState('');
  const repairing = shot.repair?.status === 'running';

  // 区域修补在后台跑：跑着的时候每 5 秒取一次工作台，结束就停。
  useEffect(() => {
    if (!repairing) return undefined;
    const timer = window.setInterval(() => {
      void apiRequest<W>(`/api/drama/${encodeURIComponent(taskId)}/shots/visual`).then(onWorkspace).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [repairing, taskId, onWorkspace]);

  if (!shot.video_url) return null;

  const post = async (action: string, body: unknown, notice: string) => {
    setBusy(true);
    try {
      onWorkspace(await apiRequest<W>(shotPath(taskId, shot, action), { method: 'POST', body: JSON.stringify(body) }));
      onNotice(notice);
      return true;
    } catch (err) {
      onError(err instanceof Error ? err.message : t('操作失败'));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const seconds = (value: string) => {
    const number = Number(value);
    return value.trim() && Number.isFinite(number) ? number : null;
  };
  const retakeSeconds = seconds(retakeAt);
  const disabled = locked || busy;
  const isDraft = Boolean(shot.draft_resolution) && !shot.hd_retake;

  return (
    <section className="shot-fix" aria-label={t('样片与局部修')}>
      {isDraft && (
        <div className="shot-fix__row">
          <span className="shot-fix__badge">{t('样片')} {shot.draft_resolution?.toUpperCase()}{shot.draft_upscaled ? ` · ${t('已本地放大')}` : ''}</span>
          {!shot.draft_upscaled && (
            <button type="button" className="secondary-action" disabled={disabled}
              title={t('用 ffmpeg 放大到成片尺寸，不花钱，画面和样片一模一样，但偏软。')}
              onClick={() => { void post('hd', { mode: 'upscale' }, t('已本地放大，合成时用放大后的这条。')); }}>
              {t('本地放大')}
            </button>
          )}
          <button type="button" className="secondary-action" disabled={disabled || shot.stale}
            title={t('同提示词、同种子按全分辨率再拍一条，要再付一次全价；人物、服装和场景不变，但走位和镜头可能和样片不一样。要和样片一模一样，用「本地放大」。')}
            onClick={() => { void post('hd', { mode: 'regenerate' }, t('已标记重出高清；重跑第 5 阶段时只按全分辨率重出这一镜。')); }}>
            {t('重出高清')}
          </button>
        </div>
      )}
      {shot.hd_retake && shot.stale && <p className="shot-workspace__hint" role="status">{t('已标记重出高清，重跑第 5 阶段后生效。')}</p>}

      <div className="shot-fix__row">
        <label>
          {t('从第')}
          <input type="number" min={0.1} step={0.1} inputMode="decimal" value={retakeAt} aria-label={t('从第几秒往后重做')}
            onChange={event => setRetakeAt(event.target.value)} />
          {t('秒往后重做')}
        </label>
        <input type="text" className="shot-fix__note" maxLength={300} value={retakeNote} placeholder={t('要改掉的问题，例如：刀从左手穿过去了')}
          aria-label={t('重做要改掉的问题')} onChange={event => setRetakeNote(event.target.value)} />
        <button type="button" className="secondary-action" disabled={disabled || retakeSeconds === null || retakeSeconds <= 0}
          title={t('这一秒之前的画面保留，用这一刻的画面当首帧只重出后面几秒，再接回去。')}
          onClick={() => {
            void post('retake', { from_seconds: retakeSeconds, note: retakeNote }, t('已标记；重跑第 5 阶段时只重出这一秒之后的部分。'))
              .then(done => { if (done) { setRetakeAt(''); setRetakeNote(''); } });
          }}>
          {t('从这里重做')}
        </button>
      </div>
      {typeof shot.retake_from === 'number' && shot.stale && (
        <p className="shot-workspace__hint" role="status">{t('已标记从第 {0} 秒往后重做，重跑第 5 阶段后生效。', [String(shot.retake_from)])}</p>
      )}

      {repairSupported && (
        <div className="shot-fix__repair">
          <button type="button" className="secondary-action" aria-expanded={repairOpen} disabled={repairing}
            onClick={() => setRepairOpen(open => !open)}>
            {repairing ? t('区域修补中…') : t('区域修补')}
          </button>
          {shot.repair?.status === 'failed' && <p className="shot-fix__error" role="alert">{t('上次修补没成功：')}{shot.repair.error}</p>}
          {shot.repair?.status === 'done' && <p className="shot-workspace__hint" role="status">{t('修补完成：')}{shot.repair.note}</p>}
          {repairOpen && !repairing && (
            <form className="shot-fix__repair-form" onSubmit={event => {
              event.preventDefault();
              const [, x, y] = REGIONS[region];
              void post('repair', {
                box: { x, y, w: 1 / 3, h: 1 / 3 }, note: repairNote, start: seconds(repairFrom), end: seconds(repairTo),
              }, t('已开始修补这一块，完成后自动换上。')).then(done => { if (done) { setRepairOpen(false); setRepairNote(''); } });
            }}>
              <div className="shot-fix__grid" role="radiogroup" aria-label={t('要修的区域')}>
                {REGIONS.map(([label], index) => (
                  <button key={label} type="button" role="radio" aria-checked={region === index}
                    className={region === index ? 'is-active' : ''} onClick={() => setRegion(index)}>{t(label)}</button>
                ))}
              </div>
              <label>{t('第')}<input type="number" min={0} step={0.1} value={repairFrom} aria-label={t('修补开始秒数')} onChange={event => setRepairFrom(event.target.value)} />
                {t('到')}<input type="number" min={0} step={0.1} value={repairTo} aria-label={t('修补结束秒数')} onChange={event => setRepairTo(event.target.value)} />{t('秒（可不填）')}</label>
              <input type="text" className="shot-fix__note" maxLength={300} required value={repairNote}
                placeholder={t('这一块要怎么改，例如：去掉门口多出来的那个人')} aria-label={t('这一块要怎么改')}
                onChange={event => setRepairNote(event.target.value)} />
              <button type="submit" className="primary-action" disabled={disabled || !repairNote.trim()}>{t('开始修补')}</button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
