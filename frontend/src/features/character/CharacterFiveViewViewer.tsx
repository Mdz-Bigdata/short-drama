import { CheckCircle2, ExternalLink, ImageOff, ScanFace, ZoomIn } from 'lucide-react';
import { useState, type KeyboardEvent } from 'react';

import { CharacterDetailDialog } from './CharacterDetailDialog';
import type {
  CharacterDashboardCharacter,
  CharacterViewContract,
  FiveViewKey,
} from './types';

export function CharacterFiveViewViewer({
  character,
  contract,
}: {
  character: CharacterDashboardCharacter;
  contract: CharacterViewContract;
}) {
  const [selectedKey, setSelectedKey] = useState<FiveViewKey>('front');
  const [brokenViewUrls, setBrokenViewUrls] = useState<string[]>([]);
  const [brokenSheetUrl, setBrokenSheetUrl] = useState<string | null>(null);
  const [largeImage, setLargeImage] = useState<{
    src: string;
    title: string;
    alt: string;
  } | null>(null);
  const selectedDefinition = contract.views.find(view => view.key === selectedKey) || contract.views[0];
  const selectedAsset = character.views.find(view => view.key === selectedDefinition.key);
  const selectedAvailable = Boolean(selectedAsset?.imageUrl)
    && !brokenViewUrls.includes(selectedAsset?.imageUrl || '');
  const availableCount = character.views.filter(view => (
    view.available
    && Boolean(view.imageUrl)
    && !brokenViewUrls.includes(view.imageUrl || '')
  )).length;
  const sheetBroken = Boolean(character.sheetUrl) && brokenSheetUrl === character.sheetUrl;
  const sheetOnly = availableCount === 0 && Boolean(character.sheetUrl) && !sheetBroken;
  const panelId = `character-view-panel-${character.characterId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;

  const markBroken = (url: string) => {
    setBrokenViewUrls(current => current.includes(url) ? current : [...current, url]);
  };

  const moveTabFocus = (event: KeyboardEvent<HTMLButtonElement>, key: FiveViewKey) => {
    const keys = contract.views.map(view => view.key);
    const index = keys.indexOf(key);
    let nextIndex: number;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % keys.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + keys.length) % keys.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = keys.length - 1;
    else return;
    event.preventDefault();
    setSelectedKey(keys[nextIndex]);
    const tabs = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs?.[nextIndex]?.focus();
  };

  return (
    <section className="character-viewer" aria-labelledby="character-viewer-title">
      <header className="character-viewer__header">
        <div>
          <span className="character-section-kicker">FIVE-VIEW IDENTITY LOCK</span>
          <h2 id="character-viewer-title">五视图工作区</h2>
        </div>
        <div className="character-viewer__count" aria-label={`五视图已完成 ${availableCount} / 5`}>
          <span>{String(availableCount).padStart(2, '0')}</span>
          <small>/ 05 VIEWS</small>
        </div>
      </header>

      <div
        id={panelId}
        role="tabpanel"
        aria-labelledby={`character-view-tab-${selectedDefinition.key}`}
        className={`character-viewer__stage ${selectedAvailable ? 'is-ready' : 'is-missing'}`}
      >
        <div className="character-viewer__reticle" aria-hidden="true" />
        {selectedAvailable && selectedAsset?.imageUrl ? (
          <>
            <button
              type="button"
              className="character-viewer__image-trigger"
              aria-label={`查看${character.name}${selectedDefinition.labelZh}大图`}
              onClick={() => setLargeImage({
                src: selectedAsset.imageUrl as string,
                title: `${character.name} · ${selectedDefinition.labelZh}`,
                alt: `${character.name} ${selectedDefinition.labelZh} ${selectedDefinition.angleDegrees}度大图`,
              })}
            >
              <img
                src={selectedAsset.imageUrl}
                alt={`${character.name} ${selectedDefinition.labelZh} ${selectedDefinition.angleDegrees}度`}
                onError={() => markBroken(selectedAsset.imageUrl as string)}
              />
              <span className="character-viewer__zoom-hint" aria-hidden="true"><ZoomIn size={15} /> 点击查看大图</span>
            </button>
            <a
              className="character-viewer__open"
              href={selectedAsset.imageUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={`查看${character.name}${selectedDefinition.labelZh}原图`}
            >
              <ExternalLink size={15} /> 原图
            </a>
          </>
        ) : sheetOnly && character.sheetUrl ? (
          <>
            <button
              type="button"
              className="character-viewer__image-trigger is-legacy"
              aria-label={`查看${character.name}整板参考图大图`}
              onClick={() => setLargeImage({
                src: character.sheetUrl as string,
                title: `${character.name} · 整板参考图`,
                alt: `${character.name} 旧版五视图整板参考图大图`,
              })}
            >
              <img
                className="character-viewer__legacy-sheet"
                src={character.sheetUrl}
                alt={`${character.name} 旧版五视图整板参考图`}
                onError={() => setBrokenSheetUrl(character.sheetUrl)}
              />
              <span className="character-viewer__zoom-hint" aria-hidden="true"><ZoomIn size={15} /> 点击查看大图</span>
            </button>
            <div className="character-viewer__sheet-notice" role="note">
              <ScanFace size={17} />
              <span><strong>整板参考图</strong>尚未拆分并通过五视图质检，五个角度槽仍记为缺图。</span>
            </div>
          </>
        ) : (
          <div className="character-viewer__placeholder">
            <span className="character-viewer__placeholder-angle">{selectedDefinition.angleDegrees}°</span>
            <ImageOff aria-hidden="true" size={34} />
            {sheetBroken && <span className="character-viewer__load-error">整板参考图加载失败</span>}
            <strong>{selectedDefinition.labelZh}尚未生成</strong>
            <small>{selectedDefinition.labelEn}</small>
          </div>
        )}

        <div className="character-viewer__stage-label">
          <span>{String(selectedDefinition.order).padStart(2, '0')}</span>
          <div>
            <strong>{selectedDefinition.labelZh}</strong>
            <small>{selectedDefinition.labelEn} · {selectedDefinition.angleDegrees}°</small>
          </div>
        </div>
      </div>

      <div className="character-viewer__tabs" role="tablist" aria-label={`${character.name} 五视图角度`}>
        {contract.views.map(definition => {
          const asset = character.views.find(view => view.key === definition.key);
          const available = Boolean(asset?.imageUrl) && !brokenViewUrls.includes(asset?.imageUrl || '');
          const selected = definition.key === selectedDefinition.key;
          return (
            <button
              key={definition.key}
              id={`character-view-tab-${definition.key}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              tabIndex={selected ? 0 : -1}
              className={`character-viewer__tab ${selected ? 'is-selected' : ''}`}
              onClick={() => setSelectedKey(definition.key)}
              onKeyDown={event => moveTabFocus(event, definition.key)}
            >
              <span className="character-viewer__tab-image">
                {available && asset?.imageUrl ? (
                  <img
                    src={asset.imageUrl}
                    alt=""
                    onError={() => markBroken(asset.imageUrl as string)}
                  />
                ) : (
                  <span className="character-viewer__tab-empty" aria-hidden="true">
                    <ImageOff size={18} />
                  </span>
                )}
                {available && <CheckCircle2 className="character-viewer__tab-check" size={15} aria-hidden="true" />}
              </span>
              <span className="character-viewer__tab-copy">
                <strong>{definition.labelZh}</strong>
                <small>{definition.angleDegrees}°</small>
              </span>
            </button>
          );
        })}
      </div>

      {largeImage && (
        <CharacterDetailDialog
          title={largeImage.title}
          className="character-dialog--image"
          closeLabel="关闭大图"
          onClose={() => setLargeImage(null)}
        >
          <figure className="character-dialog__image">
            <img src={largeImage.src} alt={largeImage.alt} />
            <figcaption>
              <a href={largeImage.src} target="_blank" rel="noreferrer">
                <ExternalLink size={15} aria-hidden="true" /> 在新窗口打开原图
              </a>
            </figcaption>
          </figure>
        </CharacterDetailDialog>
      )}
    </section>
  );
}
