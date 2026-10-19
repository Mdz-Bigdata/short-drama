import {
  ArrowRight,
  Download,
  FileSearch,
  RefreshCcw,
  UserRoundPlus,
  WandSparkles,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiRequest } from '../../api/client';
import { ElementLibraryPage } from '../elements/ElementLibraryPage';
import type { ElementKind } from '../elements/elementTypes';
import { assetGateReason, type AssetReadiness } from './assetReadiness';
import { CharacterAssetTabs } from './CharacterAssetTabs';
import { characterAssetTabLabels } from './assetTabLabels';
import { CharacterFiveViewViewer } from './CharacterFiveViewViewer';
import { CharacterDetailDialog } from './CharacterDetailDialog';
import { CharacterOverview, type CharacterOverviewDetail } from './CharacterOverview';
import {
  CharacterEvidencePanels,
  CharacterInspector,
  CharacterLibrary,
} from './CharacterDesignerPanels';
import type { CharacterDashboardResponse, CharacterRegenerateMode } from './types';
import './CharacterDesignerPage.css';
import { t } from '../../i18n';

const nonActorAssetKinds = ['scene', 'prop', 'costume', 'effect'] as const satisfies readonly ElementKind[];

interface ElementCountResponse {
  items: unknown[];
  total: number;
}

interface ActorExtractionResult {
  created: number;
  skipped: number;
  with_image?: number;
}

interface ProductionAssetSyncResult {
  created: number;
  reused?: number;
  skipped: number;
  with_image?: number;
  kinds?: Partial<Record<(typeof nonActorAssetKinds)[number], number>>;
  readiness?: AssetReadiness;
}

export function CharacterDesignerPage({
  dashboard,
  syncMessage,
  refreshing = false,
  exporting = false,
  initialAssetKind = 'actor',
  taskId,
  onRefresh,
  onRegenerate,
  onRegenerateCharacter,
  onRegenerateCharacters,
  onExport,
  onContinue,
}: {
  dashboard: CharacterDashboardResponse;
  syncMessage?: string;
  refreshing?: boolean;
  exporting?: boolean;
  initialAssetKind?: ElementKind;
  taskId?: string;
  onRefresh: () => void;
  onRegenerate: () => void;
  /** 只为一名角色重新出设定集或补高清身份视图；不传时角色档案里不显示这些按钮。 */
  onRegenerateCharacter?: (name: string, mode: CharacterRegenerateMode) => void;
  /** 把这些角色的设定集全部重新出一遍（每名一次付费出图）。 */
  onRegenerateCharacters?: (names: string[]) => void;
  onExport: () => void;
  onContinue: () => void;
}) {
  const [selectedId, setSelectedId] = useState('');
  const [activeAssetKind, setActiveAssetKind] = useState<ElementKind>(initialAssetKind);
  const [assetCounts, setAssetCounts] = useState<Partial<Record<ElementKind, number>>>({});
  const assetCountGenerations = useRef<Partial<Record<ElementKind, number>>>({});
  const [projectDetail, setProjectDetail] = useState<[string, string] | null>(null);
  const [overviewDetail, setOverviewDetail] = useState<CharacterOverviewDetail | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractNotice, setExtractNotice] = useState('');
  const [assetSyncNotice, setAssetSyncNotice] = useState('');
  const [assetGenerationToken, setAssetGenerationToken] = useState(0);
  const [assetReplaceToken, setAssetReplaceToken] = useState(0);
  const [assetGenerationBusy, setAssetGenerationBusy] = useState(false);
  const [assetReadiness, setAssetReadiness] = useState<AssetReadiness | null>(null);
  const synchronizedTaskId = useRef('');
  const character = dashboard.characters.find(item => item.characterId === selectedId) || dashboard.characters[0];
  // 数字演员、场地、道具、服装、特效没出齐就离开第 3 步，下游分镜拿不到锁人物的
  // 身份视图，只能自己编一个人出来。看板契约 READY 之前不放行，成片一致性才守得住。
  // The library gate covers scenes, props, costumes and effects; while it is
  // unknown (older backend, request failed) the server-side stage-4 check still holds.
  const assetsReady = !assetReadiness || assetReadiness.complete;
  const castReady = dashboard.state === 'READY' && assetsReady;
  const castGateReason = dashboard.state !== 'READY'
    ? (dashboard.characters.length
      ? `数字演员设定集尚未齐备：${dashboard.stats.readyCount}/${dashboard.characters.length} 名数字演员可交付`
        + `${dashboard.stats.failedCount ? `，${dashboard.stats.failedCount} 名生成失败` : ''}`
        + '。全部生成完成后才能进入分镜师。'
      : '尚未生成任何数字演员资产，完成第 3 步后才能进入分镜师。')
    : assetGateReason(assetReadiness);
  const projectDetails = [
    ['类型', dashboard.project.genre],
    ['平台', dashboard.project.platform],
    ['交付', dashboard.project.deliverySpec],
    ['约束', dashboard.project.constraints],
  ].filter((item): item is [string, string] => Boolean(item[1]));
  const synchronizeAssetCounts = useCallback(async () => {
    const requests = nonActorAssetKinds.map(kind => {
      const generation = (assetCountGenerations.current[kind] || 0) + 1;
      assetCountGenerations.current[kind] = generation;
      return { kind, generation };
    });
    setAssetCounts(current => {
      const next = { ...current };
      nonActorAssetKinds.forEach(kind => { delete next[kind]; });
      return next;
    });

    const results = await Promise.allSettled(requests.map(async ({ kind, generation }) => ({
      kind,
      generation,
      response: await apiRequest<ElementCountResponse>(
        `/api/elements?kind=${kind}&page=1&page_size=1${taskId ? `&task_id=${encodeURIComponent(taskId)}` : ''}`,
      ),
    })));

    setAssetCounts(current => {
      const next = { ...current };
      results.forEach(result => {
        if (result.status !== 'fulfilled') return;
        const { kind, generation, response } = result.value;
        if (assetCountGenerations.current[kind] !== generation) return;
        if (!Number.isFinite(response.total) || response.total < 0) return;
        next[kind] = Math.trunc(response.total);
      });
      return next;
    });
  }, [taskId]);

  const refreshAssetReadiness = useCallback(async () => {
    if (!taskId) return;
    try {
      const readiness = await apiRequest<AssetReadiness>(
        `/api/drama/${encodeURIComponent(taskId)}/production-assets/readiness`,
      );
      if (readiness && typeof readiness.complete === 'boolean') setAssetReadiness(readiness);
    } catch {
      // Keep the last known readiness; the backend gate remains authoritative.
    }
  }, [taskId]);

  useEffect(() => {
    const generations = assetCountGenerations.current;
    const handle = window.setTimeout(() => { void synchronizeAssetCounts(); }, 0);
    return () => {
      window.clearTimeout(handle);
      nonActorAssetKinds.forEach(kind => {
        generations[kind] = (generations[kind] || 0) + 1;
      });
    };
  }, [synchronizeAssetCounts]);

  useEffect(() => {
    if (!taskId || synchronizedTaskId.current === taskId) return;
    synchronizedTaskId.current = taskId;
    let cancelled = false;

    const synchronizeProductionAssets = async () => {
      try {
        const result = await apiRequest<ProductionAssetSyncResult>(
          `/api/drama/${encodeURIComponent(taskId)}/production-assets/sync`,
          { method: 'POST', body: JSON.stringify({}) },
        );
        if (cancelled) return;
        if (result.readiness && typeof result.readiness.complete === 'boolean') setAssetReadiness(result.readiness);
        const reused = Number(result.reused || 0);
        setAssetSyncNotice(result.created > 0 || reused > 0
          ? (result.created > 0 ? `已根据剧本同步 ${result.created} 项拍摄资产` : '')
            + (result.created > 0 && reused > 0 ? '，' : '')
            + (reused > 0 ? `从资产库复用 ${reused} 项` : '')
            + '。'
          : result.skipped > 0
            ? '剧本中的拍摄资产已全部存在于本项目资产。'
            : '剧本中暂未识别到场地、道具、服装或特效资产。');
        await synchronizeAssetCounts();
      } catch {
        if (!cancelled) {
          setAssetSyncNotice('拍摄资产自动同步失败，可进入对应分类手动从剧本提取。');
        }
      }
    };
    void synchronizeProductionAssets();
    return () => { cancelled = true; };
  }, [taskId, synchronizeAssetCounts]);

  const refresh = () => {
    onRefresh();
    void synchronizeAssetCounts();
    void refreshAssetReadiness();
  };

  /** Mine the screenplay for its cast and file each actor into the asset库. */
  const importActorsFromScript = async () => {
    if (!taskId || extracting) return;
    setExtracting(true);
    setExtractNotice('');
    try {
      const result = await apiRequest<ActorExtractionResult>(
        `/api/drama/${encodeURIComponent(taskId)}/production-assets/actor/import`,
        { method: 'POST', body: JSON.stringify({}) },
      );
      const images = Number(result.with_image || 0);
      setExtractNotice(result.created > 0
        ? `已从剧本提取 ${result.created} 位演员`
          + (images ? `，其中 ${images} 位带参考图` : '，暂无参考图，可上传或重新生成')
          + (result.skipped ? `，跳过 ${result.skipped} 位已存在演员` : '')
          + '。'
        : result.skipped > 0
          ? `剧本中的 ${result.skipped} 位演员已全部存在于资产库。`
          : '剧本中尚未识别到可提取的演员，可先完成编剧阶段或手动添加。');
      onRefresh();
      void synchronizeAssetCounts();
    } catch {
      setExtractNotice('从剧本提取演员失败，请确认后端服务可用后重试。');
    } finally {
      setExtracting(false);
    }
  };
  const selectAssetKind = (kind: ElementKind) => {
    setActiveAssetKind(kind);
    setAssetGenerationBusy(false);
    setProjectDetail(null);
    setOverviewDetail(null);
  };

  const replaceAllActors = () => {
    if (!onRegenerateCharacters) return;
    const names = dashboard.characters.filter(item => !item.regenerating).map(item => item.name);
    if (!names.length) return;
    const confirmed = window.confirm(
      `把本项目全部 ${names.length} 名数字演员的设定集重新生成一遍？\n每名角色一次付费出图，以现在的主肖像为身份参考；新图通过质检才替换旧图，未通过的保留旧图。`,
    );
    if (confirmed) onRegenerateCharacters(names);
  };

  const regenerateSelectedActor = () => {
    if (!onRegenerateCharacter || !character || character.regenerating) return;
    const confirmed = window.confirm(
      `重新为「${character.name}」生成一张数字演员设定集？\n这是一次付费出图，以现在的主肖像为身份参考；新图通过质检后才替换旧图，未通过则保留旧图。`,
    );
    if (confirmed) onRegenerateCharacter(character.name, 'sheet');
  };

  const replaceActiveAssets = () => {
    if (activeAssetKind === 'actor') {
      replaceAllActors();
      return;
    }
    if (assetGenerationBusy) return;
    const label = characterAssetTabLabels[activeAssetKind];
    const confirmed = window.confirm(
      `把本项目全部「${label}」的参考图重新生成一遍？\n已有的图也会被替换，每一项都是一次付费出图。只想补缺图请用「生成缺失图片」。`,
    );
    if (confirmed) setAssetReplaceToken(current => current + 1);
  };

  const regenerateActiveAssets = () => {
    if (activeAssetKind === 'actor') {
      onRegenerate();
      return;
    }
    if (!assetGenerationBusy) setAssetGenerationToken(current => current + 1);
  };

  return (
    <main
      className="character-designer"
      aria-labelledby="character-designer-title"
      aria-label={t('角色设计完整内容，可上下滚动')}
      tabIndex={0}
    >
      <CharacterAssetTabs
        activeKind={activeAssetKind}
        counts={{ ...assetCounts, actor: dashboard.characters.length }}
        onSelect={selectAssetKind}
      />

      <header className="character-designer__hero">
        <div className="character-designer__title-block">
          <span className="character-designer__eyebrow"><i aria-hidden="true" /> CHARACTER DESIGNER · STAGE 03</span>
          <div>
            <h1 id="character-designer-title">
              {activeAssetKind === 'actor'
                ? (character?.name || '角色设定')
                : characterAssetTabLabels[activeAssetKind]}
            </h1>
            <span className={`character-designer__global-state is-${dashboard.state.toLowerCase()}`}>{dashboard.state}</span>
          </div>
          <p>
            {activeAssetKind === 'actor'
              ? '将角色身份 DNA 锁定为可验收的数字演员设定集，保持脸型、发型、服装与体态跨角度一致。'
              : `管理本剧的${characterAssetTabLabels[activeAssetKind]}资产，与数字演员共用同一资产库。`}
          </p>
        </div>
        <div className="character-designer__actions" aria-label={t('角色设计工作流操作')}>
          {activeAssetKind === 'actor' && taskId && (
            <button type="button" onClick={() => { void importActorsFromScript(); }} disabled={extracting}>
              <FileSearch size={16} aria-hidden="true" /> {extracting ? t('提取中…') : t('从剧本提取演员')}
            </button>
          )}
          <button type="button" onClick={refresh} disabled={refreshing}>
            <RefreshCcw size={16} className={refreshing ? 'is-spinning' : ''} aria-hidden="true" />
            {refreshing ? t('同步中') : t('刷新')}
          </button>
          <button type="button" onClick={onExport} disabled={exporting}>
            <Download size={16} aria-hidden="true" /> {exporting ? t('导出中') : t('导出 JSON')}
          </button>
          {(activeAssetKind !== 'actor' || onRegenerateCharacters) && (
            <button
              type="button"
              onClick={replaceActiveAssets}
              disabled={activeAssetKind === 'actor'
                ? !dashboard.characters.some(item => !item.regenerating)
                : assetGenerationBusy}
              title={activeAssetKind === 'actor' ? t('每名数字演员重新出一张设定集，已有的图在新图通过质检后才被替换') : undefined}
            >
              <RefreshCcw size={16} aria-hidden="true" /> {t('全部重新生成')}
            </button>
          )}
          {activeAssetKind === 'actor' && onRegenerateCharacter && character && (
            <button
              type="button"
              onClick={regenerateSelectedActor}
              disabled={Boolean(character.regenerating)}
            >
              <RefreshCcw size={16} className={character.regenerating ? 'is-spinning' : ''} aria-hidden="true" />
              {character.regenerating ? t('设定集生成中…') : `重新生成「${character.name}」`}
            </button>
          )}
          <button
            type="button"
            className="is-accent"
            onClick={regenerateActiveAssets}
            disabled={activeAssetKind !== 'actor' && assetGenerationBusy}
            title={activeAssetKind === 'actor'
              ? '重跑角色设计：只为缺图或未通过质检的角色出图；已完成的角色请用「重新生成」。'
              : undefined}
          >
            <WandSparkles size={16} aria-hidden="true" />
            {activeAssetKind !== 'actor' && assetGenerationBusy ? '图片生成中…' : '生成缺失图片'}
          </button>
          <button
            type="button"
            className="is-primary"
            onClick={onContinue}
            disabled={!castReady}
            title={castReady ? undefined : castGateReason}
          >
            {t('进入分镜师')} <ArrowRight size={16} aria-hidden="true" />
          </button>
        </div>
      </header>

      {!castReady && (
        <p className="character-designer__gate-hint" role="status" aria-label={t('进入分镜师的资产门禁')}>
          {castGateReason}
        </p>
      )}
      {syncMessage && <p className="character-designer__sync-message" role="status">{syncMessage}</p>}
      {assetSyncNotice && <p className="character-designer__sync-message" role="status">{assetSyncNotice}</p>}
      {extractNotice && <p className="character-designer__sync-message" role="status">{extractNotice}</p>}

      {activeAssetKind === 'actor' ? (
        <section
          id="character-asset-panel-actor"
          className="character-asset-panel character-asset-panel--actor"
          role="tabpanel"
          aria-labelledby="character-asset-tab-actor"
        >
          <CharacterOverview dashboard={dashboard} onOpen={setOverviewDetail} />

          {overviewDetail && (
            <CharacterDetailDialog
              title={overviewDetail.title}
              onClose={() => setOverviewDetail(null)}
            >
              <p className="character-dialog__project-value">{overviewDetail.content}</p>
            </CharacterDetailDialog>
          )}

          {projectDetails.length > 0 && (
            <div className="character-designer__project" aria-label={t('项目角色设计基准')}>
              {projectDetails.map(([label, value]) => (
                <button
                  key={label}
                  type="button"
                  aria-haspopup="dialog"
                  aria-label={`查看${label}完整内容`}
                  onClick={() => setProjectDetail([label, value])}
                >
                  <small>{label}</small>
                  <span>{value}</span>
                </button>
              ))}
            </div>
          )}

          {projectDetail && (
            <CharacterDetailDialog
              title={`项目角色设计基准 · ${projectDetail[0]}`}
              onClose={() => setProjectDetail(null)}
            >
              <p className="character-dialog__project-value">{projectDetail[1]}</p>
            </CharacterDetailDialog>
          )}

          {character ? (
            <>
              <div className="character-designer__workspace">
                <CharacterLibrary
                  characters={dashboard.characters}
                  selectedId={character.characterId}
                  onSelect={setSelectedId}
                />
                <CharacterFiveViewViewer
                  key={character.characterId}
                  character={character}
                  contract={dashboard.viewContract}
                  onFillDetails={onRegenerateCharacter ? () => onRegenerateCharacter(character.name, 'details') : undefined}
                />
                <CharacterInspector key={`inspector-${character.characterId}`} character={character} onRegenerate={onRegenerateCharacter} />
              </div>
              <CharacterEvidencePanels dashboard={dashboard} character={character} />
            </>
          ) : (
            <section className="character-designer__empty" role="status">
              <UserRoundPlus size={42} aria-hidden="true" />
              <h2>{t('等待角色设计资产')}</h2>
              <p>{t('编剧阶段识别角色后，这里会生成角色库、设定集视图槽位与身份 DNA 档案。')}</p>
              <button type="button" onClick={onRegenerate}><WandSparkles size={16} aria-hidden="true" /> {t('启动角色设计')}</button>
            </section>
          )}
        </section>
      ) : (
        <section
          id={`character-asset-panel-${activeAssetKind}`}
          className="character-asset-panel character-asset-panel--library"
          role="tabpanel"
          aria-labelledby={`character-asset-tab-${activeAssetKind}`}
        >
          <ElementLibraryPage
            key={activeAssetKind}
            initialKind={activeAssetKind}
            embedded
            taskId={taskId}
            regenerateAllToken={assetGenerationToken}
            replaceAllToken={assetReplaceToken}
            onGenerationStateChange={busy => {
              setAssetGenerationBusy(busy);
              if (!busy) void refreshAssetReadiness();
            }}
            onCountChange={(kind, total) => {
              assetCountGenerations.current[kind] = (assetCountGenerations.current[kind] || 0) + 1;
              setAssetCounts(current => current[kind] === total ? current : { ...current, [kind]: total });
            }}
          />
        </section>
      )}
    </main>
  );
}
