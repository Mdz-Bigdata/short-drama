import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import './PronunciationTable.css';

export interface Reading {
  word: string;
  say: string;
}

interface Props {
  taskId: string;
}

/**
 * 读音表：这部剧里这个词配音时念什么（多音字、人名地名，用同音字写），配音时替换进去，字幕不动。
 * 数字不用登记：配音前自动按中文读法写（3年 → 三年，2个 → 两个，50% → 百分之五十）。
 */
export function PronunciationTable({ taskId }: Props) {
  const [rows, setRows] = useState<Reading[]>([]);
  const [saved, setSaved] = useState<Reading[]>([]);
  const [word, setWord] = useState('');
  const [say, setSay] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let alive = true;
    apiRequest<{ readings: Reading[] }>(`/api/drama/${encodeURIComponent(taskId)}/pronunciations`)
      .then(result => {
        // 旧后端或别的回包里没有 readings：当作空表，不让整个编剧面板跟着出错。
        const readings = Array.isArray(result?.readings) ? result.readings : [];
        if (alive) { setRows(readings); setSaved(readings); }
      })
      .catch(() => undefined);
    return () => { alive = false; };
  }, [taskId]);

  const changed = JSON.stringify(rows) !== JSON.stringify(saved);
  const add = () => {
    const w = word.trim();
    const s = say.trim();
    if (!w || !s || w === s) return;
    setRows(current => [...current.filter(row => row.word !== w), { word: w, say: s }]);
    setWord('');
    setSay('');
  };
  const save = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await apiRequest<{ readings: Reading[] }>(`/api/drama/${encodeURIComponent(taskId)}/pronunciations`, {
        method: 'PUT', body: JSON.stringify({ readings: rows }),
      });
      const readings = Array.isArray(result?.readings) ? result.readings : rows;
      setRows(readings);
      setSaved(readings);
      setNotice(t('已保存，之后的配音按这张表念。'));
    } catch (err) {
      setNotice(err instanceof Error ? err.message : t('读音表保存失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="pronunciations">
      <summary title={t('多音字、人名地名念不对时登记在这里：配音时把词换成登记的念法，字幕不动。数字会自动按中文读法念。')}>
        {t('配音读音表')}{saved.length ? `（${saved.length}）` : ''}
      </summary>
      <ul>
        {rows.map(row => (
          <li key={row.word}>
            <span>{row.word}</span><span aria-hidden="true">→</span><span>{row.say}</span>
            <button type="button" className="secondary-action" disabled={busy} aria-label={t('删掉 {0} 的读音', [row.word])}
              onClick={() => setRows(current => current.filter(item => item.word !== row.word))}>
              {t('删除')}
            </button>
          </li>
        ))}
      </ul>
      <div className="pronunciations__add">
        <input type="text" maxLength={20} value={word} placeholder={t('剧本里写的，如：行长')} aria-label={t('剧本里的写法')} disabled={busy}
          onChange={event => setWord(event.target.value)} />
        <input type="text" maxLength={20} value={say} placeholder={t('配音念成，如：航长')} aria-label={t('配音时的念法')} disabled={busy}
          onChange={event => setSay(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') add(); }} />
        <button type="button" className="secondary-action" disabled={busy || !word.trim() || !say.trim()} onClick={add}>{t('加一条')}</button>
        {changed && <button type="button" className="primary-action" disabled={busy} onClick={() => { void save(); }}>{t('保存读音表')}</button>}
      </div>
      {notice && <p className="pronunciations__notice" role="status">{notice}</p>}
    </details>
  );
}
