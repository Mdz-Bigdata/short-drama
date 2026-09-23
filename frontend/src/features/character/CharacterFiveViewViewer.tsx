import { CheckCircle2, ExternalLink, ImageOff, ScanFace, ZoomIn } from 'lucide-react';
import { useState, type KeyboardEvent } from 'react';

import { actorSheetCellLabels, actorSheetDetailGroups } from './assetTabLabels';
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
  const [mode, setMode] = useState<'identity' | 'details'>('identity');
  const [brokenViewUrls, setBrokenViewUrls] = useState<string[]>([]);
  const [brokenSheetUrl, setBrokenSheetUrl] = useState<string | null>(null);
  const [largeImage, setLargeImage] = useState<{
    src: string;
    title: string;
    alt: string;
  } | null>(null);
  // 「细节」页签只收元素拆解 8 格 + 细节矩阵 12 格；身份锚点留在主选择器里。
  const detailGroups = actorSheetDetailGroups
    .map(({ group, label }) => ({
      group,
      label,
      cells: character.sheetCells.filter(cell => cell.group === group),
    }))
    .filter(item => item.cells.length > 0);
  const hasDetails = detailGroups.length > 0;
  const showDetails = hasDetails && mode === 'details';
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
          <span className="character-section-kicker">ACTOR SHEET IDENTITY LOCK</span>
          <h2 id="character-viewer-title">数字演员设定集</h2>
        </div>
        <div className="character-viewer__count" aria-label={`身份视图已完成 ${availableCount} / 5`}>
          <span>{String(availableCount).padStart(2, '0')}</span>
          <small>/ 05 VIEWS</small>
        </div>
      </header>

      {hasDetails && (
        <div className="character-viewer__modes">
          <div role="tablist" aria-label={`${character.name} 设定集视图`}>
          {([['identity', '身份视图'], ['details', '细节']] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              aria-controls={panelId}
              className={`character-viewer__mode ${mode === value ? 'is-selected' : ''}`}
              onClick={() => setMode(value)}
            >
              {label}
              {value === 'details' && (
                <small>{character.sheetCells.filter(cell => cell.available).length} 格</small>
              )}
            </button>
          ))}
          </div>
          {/* 拆分之后整板本身仍然要能看——25 个格子拼在一起才看得出版面有没有走样。 */}
          {character.sheetUrl && !sheetBroken && (
            <button
              type="button"
              className="character-viewer__mode character-viewer__mode--sheet"
              aria-label={`查看${character.name}设定集整板大图`}
              onClick={() => setLargeImage({
                src: character.sheetUrl as string,
                title: `${character.name} · 设定集整板`,
                alt: `${character.name} 设定集整板大图`,
              })}
            >
              <ZoomIn size={13} aria-hidden="true" /> 整板
            </button>
          )}
        </div>
      )}

      {showDetails ? (
        <div id={panelId} role="tabpanel" aria-label={`${character.name} 设定集细节`} className="character-viewer__details">
          {detailGroups.map(({ group, label, cells }) => (
            <section key={group} className="character-viewer__detail-group" aria-label={`${label} ${cells.length} 格`}>
              <h3>{label}<small>{cells.length}</small></h3>
              <div className="character-viewer__detail-grid">
                {cells.map(cell => {
                  const available = Boolean(cell.imageUrl) && !brokenViewUrls.includes(cell.imageUrl || '');
                  const cellLabel = actorSheetCellLabels[cell.key];
                  return available && cell.imageUrl ? (
                    <button
                      key={cell.key}
                      type="button"
                      className="character-viewer__detail-cell"
                      aria-label={`查看${character.name}${cellLabel}大图`}
                      onClick={() => setLargeImage({
                        src: cell.imageUrl as string,
                        title: `${character.name} · ${cellLabel}`,
                        alt: `${character.name} ${cellLabel}大图`,
                      })}
                    >
                      <img
                        src={cell.imageUrl}
                        alt={`${character.name} ${cellLabel}`}
                        onError={() => markBroken(cell.imageUrl as string)}
                      />
                      <span>{cellLabel}</span>
                    </button>
                  ) : (
                    <div key={cell.key} className="character-viewer__detail-cell is-missing">
                      <ImageOff aria-hidden="true" size={16} />
                      <span>{cellLabel}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      ) : (
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
                alt: `${character.name} 设定集整板参考图大图`,
              })}
            >
              <img
                className="character-viewer__legacy-sheet"
                src={character.sheetUrl}
                alt={`${character.name} 设定集整板参考图`}
                onError={() => setBrokenSheetUrl(character.sheetUrl)}
              />
              <span className="character-viewer__zoom-hint" aria-hidden="true"><ZoomIn size={15} /> 点击查看大图</span>
            </button>
            <div className="character-viewer__sheet-notice" role="note">
              <ScanFace size={17} />
              <span><strong>整板参考图</strong>尚未拆分并通过设定集质检，五个身份视图槽仍记为缺图。</span>
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
      )}

      <div
        className={`character-viewer__tabs ${showDetails ? 'is-hidden' : ''}`}
        role="tablist"
        aria-label={`${character.name} 身份视图`}
      >
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
