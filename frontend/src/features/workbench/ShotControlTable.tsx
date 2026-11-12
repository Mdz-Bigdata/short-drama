import { t } from '../../i18n';
import './ShotControlTable.css';

/** 控制表的一行：这一镜要保留的一件事、靠哪份素材、有没有重复或缺（后端 control_table）。 */
export interface ControlRow {
  aspect: string;
  label: string;
  sources: string[];
  status: 'ok' | 'duplicate' | 'missing' | 'none';
  note: string;
}

const STATUS_LABELS: Record<ControlRow['status'], string> = {
  ok: '',
  none: '未用',
  duplicate: '重复',
  missing: '缺',
};

/** 每镜控制表：白模管动作、深度管空间、参考图管外观、场地图管背景；两份抢同一件事就标出来(最小控制集)。 */
export function ShotControlTable({ rows }: { rows?: ControlRow[] }) {
  if (!rows?.length) return null;
  const flagged = rows.filter(row => row.status === 'duplicate' || row.status === 'missing').length;
  return (
    <details className="shot-controls" open={flagged > 0}>
      <summary>
        {t('控制表')}
        {flagged > 0 && <span className="shot-controls__flag">{t('{0} 项要看', [String(flagged)])}</span>}
      </summary>
      <table>
        <tbody>
          {rows.map(row => (
            <tr key={row.aspect} className={`is-${row.status}`}>
              <th scope="row">{t(row.label)}</th>
              <td>
                {row.sources.length ? row.sources.join('、') : '—'}
                {STATUS_LABELS[row.status] && <span className="shot-controls__status">{t(STATUS_LABELS[row.status])}</span>}
                {row.note && <p className="shot-controls__note">{row.note}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
