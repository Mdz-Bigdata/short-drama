import { useState } from 'react';
import { Network } from 'lucide-react';

import { t } from '../../i18n';
import { sendSegmentToCanvas } from './interactiveApi';

function message(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Generate this one segment's video on the canvas: that is where a single clip is run and paid for by itself. */
export function CanvasHandoffButton({ taskId, segmentId, onOpenCanvas }: { taskId: string; segmentId: string; onOpenCanvas?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [failed, setFailed] = useState(false);
  const send = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const made = await sendSegmentToCanvas(taskId, segmentId);
      setNote(made.bound ? t('已在画布上加了首帧和视频两个节点，视频节点已绑定这一镜；到画布运行后提交，这里就能选到。') : t('已在画布上加了首帧和视频两个节点；到画布运行后提交到项目，这里就能选到。'));
    } catch (error) {
      setFailed(true);
      setNote(message(error, t('没能加到画布上')));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="istory-handoff">
      <div className="istory-row">
        <button type="button" className="istory-link" disabled={busy} onClick={() => { void send(); }}><Network size={14} aria-hidden="true" /> {t('在画布上生成这一段')}</button>
        {note && !failed && onOpenCanvas && <button type="button" className="istory-link" onClick={onOpenCanvas}>{t('打开画布')}</button>}
      </div>
      {note && <small className={failed ? 'istory-error' : ''} role={failed ? 'alert' : 'status'}>{note}</small>}
    </div>
  );
}
