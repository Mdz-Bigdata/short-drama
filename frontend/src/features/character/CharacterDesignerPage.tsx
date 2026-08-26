import {
  ArrowRight,
  Download,
  RefreshCcw,
  UserRoundPlus,
  WandSparkles,
} from 'lucide-react';
import { useState } from 'react';

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

export function CharacterDesignerPage({
  dashboard,
  syncMessage,
  refreshing = false,
  exporting = false,
  onRefresh,
  onRegenerate,
  onExport,
  onContinue,
}: {
  dashboard: CharacterDashboardResponse;
  syncMessage?: string;
  refreshing?: boolean;
  exporting?: boolean;
  onRefresh: () => void;
  onRegenerate: () => void;
  onExport: () => void;
  onContinue: () => void;
}) {
  const [selectedId, setSelectedId] = useState('');
  const [projectDetail, setProjectDetail] = useState<[string, string] | null>(null);
  const [overviewDetail, setOverviewDetail] = useState<CharacterOverviewDetail | null>(null);
  const character = dashboard.characters.find(item => item.characterId === selectedId) || dashboard.characters[0];
  const projectDetails = [
    ['类型', dashboard.project.genre],
    ['平台', dashboard.project.platform],
    ['交付', dashboard.project.deliverySpec],
    ['约束', dashboard.project.constraints],
  ].filter((item): item is [string, string] => Boolean(item[1]));

  return (
    <main
      className="character-designer"
      aria-labelledby="character-designer-title"
      aria-label="角色设计完整内容，可上下滚动"
      tabIndex={0}
    >
      <header className="character-designer__hero">
        <div className="character-designer__title-block">
          <span className="character-designer__eyebrow"><i aria-hidden="true" /> CHARACTER DESIGNER · STAGE 03</span>
          <div>
            <h1 id="character-designer-title">{character?.name || '角色设定'}</h1>
            <span className={`character-designer__global-state is-${dashboard.state.toLowerCase()}`}>{dashboard.state}</span>
          </div>
          <p>将角色身份 DNA 锁定为可验收的五视图资产，保持脸型、发型、服装与体态跨角度一致。</p>
        </div>
        <div className="character-designer__actions" aria-label="角色设计工作流操作">
          <button type="button" onClick={onRefresh} disabled={refreshing}>
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
    </main>
  );
}
