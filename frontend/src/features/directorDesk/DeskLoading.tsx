import { t } from '../../i18n';
import './DeskLoading.css';

/** The desk chunk carries three.js: every screen that opens the desk shows this while it downloads.
 *  Lives outside that chunk, so it must not import anything from the desk itself. */
export function DeskLoading() {
  return (
    <div className="desk-loading">
      <p role="status">{t('正在加载 3D 导演台…')}</p>
    </div>
  );
}
