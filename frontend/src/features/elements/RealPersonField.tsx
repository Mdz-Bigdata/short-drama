import { useState } from 'react';
import { UserCheck } from 'lucide-react';

import { t } from '../../i18n';
import type { ElementItem } from './elementTypes';
import { realPersonOf, type RealPersonPayload } from './realPerson';

const ASSET = /^asset:\/\/[A-Za-z0-9][A-Za-z0-9_-]{2,127}$/;

/** 数字演员设为真人演员：本人照片就是身份，按照片出分镜和视频；必须确认持有肖像授权。 */
export function RealPersonField({
  item,
  locked,
  onSave,
}: {
  item: ElementItem;
  locked: boolean;
  onSave: (payload: RealPersonPayload | null) => void;
}) {
  const record = realPersonOf(item);
  const [open, setOpen] = useState(false);
  const [person, setPerson] = useState(record?.person || item.name);
  const [scope, setScope] = useState(record?.scope || '');
  const [expires, setExpires] = useState(record?.expires || '');
  const [assets, setAssets] = useState((record?.ark_assets || []).join('\n'));
  const [confirmed, setConfirmed] = useState(false);
  const hasFace = item.files.some(file => file.slot === 'face_front');
  const assetList = assets.split(/\s+/).map(value => value.trim()).filter(Boolean);
  const badAsset = assetList.find(value => !ASSET.test(value));
  const canSave = !locked && confirmed && person.trim() !== '' && !badAsset;

  if (record && !open) {
    return (
      <section className="asset-real-person is-on" aria-label={t('真人演员')}>
        <header>
          <UserCheck size={15} aria-hidden="true" />
          <strong>{t('真人演员：{0}', [record.person])}</strong>
        </header>
        <p>
          {t('按本人照片出分镜和视频，不重新生成设定集。')}
          {record.expires ? ` ${t('授权到 {0}', [record.expires])}` : ''}
        </p>
        <p>
          {record.ark_assets.length
            ? t('已登记 {0} 个火山方舟真人素材，Seedance 视频用它们。', [record.ark_assets.length])
            : t('还没登记火山方舟真人素材：Seedance 不收直接上传的真人照片，这名演员的镜头在 Seedance 上只能按文字描述。')}
        </p>
        {!hasFace && <p className="is-warning">{t('还缺正脸特写：请在「正脸特写」槽位上传本人正脸照片。')}</p>}
        <div className="asset-real-person__actions">
          <button type="button" disabled={locked} onClick={() => { setConfirmed(false); setOpen(true); }}>{t('修改')}</button>
          <button type="button" disabled={locked} onClick={() => onSave(null)}>{t('取消真人演员')}</button>
        </div>
      </section>
    );
  }

  if (!open) {
    return (
      <section className="asset-real-person" aria-label={t('真人演员')}>
        <p>{t('有演员本人的照片？设为真人演员后，分镜和视频按本人照片生成，尽量像本人。')}</p>
        <button type="button" disabled={locked} onClick={() => setOpen(true)}>
          <UserCheck size={14} aria-hidden="true" /> {t('设为真人演员')}
        </button>
      </section>
    );
  }

  return (
    <form
      className="asset-real-person is-editing"
      aria-label={t('真人演员')}
      onSubmit={event => {
        event.preventDefault();
        if (!canSave) return;
        onSave({ person: person.trim(), scope: scope.trim(), expires: expires.trim(), ark_assets: assetList, confirmed });
        setOpen(false);
      }}
    >
      <p>{t('先在本演员的「正脸特写」槽位上传本人正脸照片(必需)，「正面全身」上传全身照(建议)。')}</p>
      <label>
        <span>{t('照片上是谁')}</span>
        <input value={person} maxLength={60} onChange={event => setPerson(event.target.value)} />
      </label>
      <label>
        <span>{t('授权用途')}</span>
        <input value={scope} maxLength={200} placeholder={t('如：《暗室回声》短剧拍摄与宣发')} onChange={event => setScope(event.target.value)} />
      </label>
      <label>
        <span>{t('授权到')}</span>
        <input type="date" value={expires} onChange={event => setExpires(event.target.value)} />
      </label>
      <label>
        <span>{t('火山方舟真人素材 ID（每行一个）')}</span>
        <textarea
          rows={3}
          value={assets}
          placeholder="asset://asset-20260401123823-xxxxx"
          onChange={event => setAssets(event.target.value)}
        />
        <small>
          {t('Seedance 视频只接受演员本人在火山方舟「真人人像库」完成真人认证后入库的素材；入库后把素材 ID 填在这里。')}
        </small>
        {badAsset && <small className="is-warning">{t('素材 ID 应是 asset://asset-… 的形式：{0}', [badAsset])}</small>}
      </label>
      <label className="asset-real-person__consent">
        <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
        <span>{t('我确认已取得照片中本人对上述用途的肖像使用授权')}</span>
      </label>
      <div className="asset-real-person__actions">
        <button type="submit" disabled={!canSave}>{t('保存')}</button>
        <button type="button" onClick={() => setOpen(false)}>{t('取消')}</button>
      </div>
    </form>
  );
}
