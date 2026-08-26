import {
  ShieldCheck,
  UserRoundPlus,
  UsersRound,
} from 'lucide-react';

import type { CharacterDashboardResponse, CharacterViewDefinition } from './types';

export type CharacterOverviewDetail = {
  title: string;
  content: string;
};

function joinedNames(names: string[], emptyMessage: string) {
  return names.length > 0 ? names.join('、') : emptyMessage;
}

function isViewReady(
  character: CharacterDashboardResponse['characters'][number],
  definition: CharacterViewDefinition,
) {
  const asset = character.views.find(view => view.key === definition.key);
  return Boolean(asset?.available && asset.imageUrl);
}

function viewStatusSummary(
  dashboard: CharacterDashboardResponse,
  definition: CharacterViewDefinition,
) {
  return dashboard.characters
    .map(character => `${character.name}：${isViewReady(character, definition) ? '已就绪' : '待生成'}`)
    .join('、');
}

export function CharacterOverview({
  dashboard,
  onOpen,
}: {
  dashboard: CharacterDashboardResponse;
  onOpen: (detail: CharacterOverviewDetail) => void;
}) {
  const characterNames = dashboard.characters.map(character => character.name);
  const readyNames = dashboard.characters
    .filter(character => character.assetState === 'READY')
    .map(character => character.name);
  const perCharacterViews = dashboard.characters.map(character => {
    const readyViews = dashboard.viewContract.views
      .filter(definition => isViewReady(character, definition))
      .length;
    return `${character.name} ${readyViews} / ${dashboard.viewContract.views.length}`;
  });

  return (
    <section className="character-designer__overview" aria-label="角色资产概览">
      <div className="character-designer__stat">
        <UsersRound size={18} aria-hidden="true" />
        <div>
          <button
            type="button"
            className="character-designer__number"
            aria-haspopup="dialog"
            aria-label={`查看角色总数 ${dashboard.stats.characterCount} 详情`}
            onClick={() => onOpen({
              title: `角色资产概览 · 角色总数 ${dashboard.stats.characterCount}`,
              content: `本项目共有 ${dashboard.stats.characterCount} 个角色：${joinedNames(characterNames, '暂无角色')}。可在角色库中逐一切换查看对应五视图、档案与证据。`,
            })}
          >
            {dashboard.stats.characterCount}
          </button>
          <span>角色总数</span>
        </div>
      </div>

      <div className="character-designer__stat">
        <ShieldCheck size={18} aria-hidden="true" />
        <div>
          <button
            type="button"
            className="character-designer__number"
            aria-haspopup="dialog"
            aria-label={`查看可交付角色 ${dashboard.stats.readyCount} 详情`}
            onClick={() => onOpen({
              title: `角色资产概览 · 可交付角色 ${dashboard.stats.readyCount}`,
              content: `${dashboard.stats.readyCount} / ${dashboard.stats.characterCount} 个角色已满足当前交付要求。已达到可交付状态的角色：${joinedNames(readyNames, '暂无')}。`,
            })}
          >
            {dashboard.stats.readyCount}
          </button>
          <span>可交付角色</span>
        </div>
      </div>

      <div className="character-designer__stat">
        <UserRoundPlus size={18} aria-hidden="true" />
        <div>
          <div className="character-designer__view-totals" aria-label="有效视图数量">
            <button
              type="button"
              className="character-designer__number"
              aria-haspopup="dialog"
              aria-label={`查看有效视图 ${dashboard.stats.availableViewCount} 详情`}
              onClick={() => onOpen({
                title: `角色资产概览 · 有效视图 ${dashboard.stats.availableViewCount}`,
                content: `当前已有 ${dashboard.stats.availableViewCount} 个通过资产校验的视图。各角色有效视图：${joinedNames(perCharacterViews, '暂无角色')}。`,
              })}
            >
              {dashboard.stats.availableViewCount}
            </button>
            <span aria-hidden="true">/</span>
            <button
              type="button"
              className="character-designer__number is-secondary"
              aria-haspopup="dialog"
              aria-label={`查看应交视图 ${dashboard.stats.expectedViewCount} 详情`}
              onClick={() => onOpen({
                title: `角色资产概览 · 应交视图 ${dashboard.stats.expectedViewCount}`,
                content: `应交视图总数为 ${dashboard.stats.expectedViewCount}：${dashboard.stats.characterCount} 个角色 × ${dashboard.viewContract.views.length} 个标准视角。`,
              })}
            >
              {dashboard.stats.expectedViewCount}
            </button>
          </div>
          <span>有效视图</span>
        </div>
      </div>

      <div className="character-designer__contract">
        <span>固定五视图契约</span>
        <div className="character-designer__angles" aria-label="五视图角度详情">
          {dashboard.viewContract.views.map((definition, index) => (
            <span key={definition.key}>
              <button
                type="button"
                aria-haspopup="dialog"
                aria-label={`查看${definition.angleDegrees}度${definition.labelZh}契约详情`}
                onClick={() => onOpen({
                  title: `五视图契约 · ${definition.angleDegrees}° ${definition.labelZh}`,
                  content: `第 ${definition.order} 视角：${definition.labelZh}（${definition.labelEn}），标准角度 ${definition.angleDegrees}°。角色视图状态：${viewStatusSummary(dashboard, definition) || '暂无角色'}。`,
                })}
              >
                {definition.angleDegrees}°
              </button>
              {index < dashboard.viewContract.views.length - 1 && <i aria-hidden="true">·</i>}
            </span>
          ))}
        </div>
        <small>{dashboard.viewContract.version}</small>
      </div>
    </section>
  );
}
