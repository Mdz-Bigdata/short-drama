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
import type { CharacterDashboardResponse } from './types';
import './CharacterDesignerPage.css';

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

export function CharacterDesignerPage({
  dashboard,
  syncMessage,
  refreshing = false,
  exporting = false,
  initialAssetKind = 'actor',
  taskId,
  onRefresh,
  onRegenerate,
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
  const character = dashboard.characters.find(item => item.characterId === selectedId) || dashboard.characters[0];
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
      response: await apiRequest<ElementCountResponse>(`/api/elements?kind=${kind}&page=1&page_size=1`),
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
  }, []);

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

  const refresh = () => {
    onRefresh();
    void synchronizeAssetCounts();
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
    setProjectDetail(null);
    setOverviewDetail(null);
  };

  return (
    <main
      className="character-designer"
      aria-labelledby="character-designer-title"
      aria-label="角色设计完整内容，可上下滚动"
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
              ? '将角色身份 DNA 锁定为可验收的五视图资产，保持脸型、发型、服装与体态跨角度一致。'
              : `管理本剧的${characterAssetTabLabels[activeAssetKind]}资产，与数字演员共用同一资产库。`}
          </p>
        </div>
        <div className="character-designer__actions" aria-label="角色设计工作流操作">
          {activeAssetKind === 'actor' && taskId && (
            <button type="button" onClick={() => { void importActorsFromScript(); }} disabled={extracting}>
              <FileSearch size={16} aria-hidden="true" /> {extracting ? '提取中…' : '从剧本提取演员'}
            </button>
          )}
          <button type="button" onClick={refresh} disabled={refreshing}>
            <RefreshCcw size={16} className={refreshing ? 'is-spinning' : ''} aria-hidden="true" />
            {refreshing ? '同步中' : '刷新'}
          </button>
          <button type="button" onClick={onExport} disabled={exporting}>
            <Download size={16} aria-hidden="true" /> {exporting ? '导出中' : '导出 JSON'}
          </button>
          <button type="button" className="is-accent" onClick={onRegenerate}>
            <WandSparkles size={16} aria-hidden="true" /> 重新生成
          </button>
          <button type="button" className="is-primary" onClick={onContinue}>
            进入分镜师 <ArrowRight size={16} aria-hidden="true" />
          </button>
        </div>
      </header>

      {syncMessage && <p className="character-designer__sync-message" role="status">{syncMessage}</p>}
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
            <div className="character-designer__project" aria-label="项目角色设计基准">
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
                />
                <CharacterInspector key={`inspector-${character.characterId}`} character={character} />
              </div>
              <CharacterEvidencePanels dashboard={dashboard} character={character} />
            </>
          ) : (
            <section className="character-designer__empty" role="status">
              <UserRoundPlus size={42} aria-hidden="true" />
              <h2>等待角色设计资产</h2>
              <p>编剧阶段识别角色后，这里会生成角色库、五视图槽位与身份 DNA 档案。</p>
              <button type="button" onClick={onRegenerate}><WandSparkles size={16} aria-hidden="true" /> 启动角色设计</button>
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
