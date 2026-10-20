import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileText,
  ImageOff,
  Maximize2,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserRound,
  WandSparkles,
  XCircle,
} from 'lucide-react';
import { useState, type CSSProperties } from 'react';

import { MarkdownDocument } from '../writer/MarkdownDocument';
import { CharacterDetailDialog } from './CharacterDetailDialog';
import { confirmDetailFill, fillableDetailCount } from './detailFill';
import {
  CHARACTER_STATE_LABELS,
  type CharacterAssetState,
  type CharacterDashboardCharacter,
  type CharacterDashboardResponse,
  type CharacterRegenerateMode,
  type CharacterViewContract,
} from './types';
import { t } from '../../i18n';

const STATUS_ICONS = {
  MISSING: ImageOff,
  PARTIAL: Clock3,
  NEEDS_REVIEW: CircleAlert,
  FAILED: XCircle,
  READY: CheckCircle2,
} satisfies Record<CharacterAssetState, typeof CheckCircle2>;

export function CharacterStatusBadge({ status }: { status: CharacterAssetState }) {
  const Icon = STATUS_ICONS[status];
  return (
    <span className={`character-status character-status--${status.toLowerCase()}`}>
      <Icon size={13} aria-hidden="true" /> {CHARACTER_STATE_LABELS[status]}
    </span>
  );
}

export function CharacterLibrary({
  characters,
  selectedId,
  onSelect,
}: {
  characters: CharacterDashboardCharacter[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN');
  const filtered = normalizedQuery
    ? characters.filter(character => `${character.name} ${character.role} ${character.identity}`.toLocaleLowerCase('zh-CN').includes(normalizedQuery))
    : characters;

  return (
    <aside className="character-library" aria-labelledby="character-library-title">
      <header className="character-panel-heading">
        <div>
          <span className="character-section-kicker">CAST LIBRARY</span>
          <h2 id="character-library-title">{t('角色库')}</h2>
        </div>
        <span className="character-library__total">{characters.length}</span>
      </header>
      <label className="character-library__search">
        <Search size={16} aria-hidden="true" />
        <span className="sr-only">{t('搜索角色')}</span>
        <input
          type="search"
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder={t('搜索角色、身份、职能')}
        />
      </label>
      <div
        className="character-library__list"
        role="region"
        aria-label={t('角色列表，可上下滚动')}
        aria-live="polite"
        tabIndex={0}
      >
        {filtered.map((character, index) => {
          const selected = character.characterId === selectedId;
          const thumbnail = character.views.find(view => view.key === 'front' && view.imageUrl)?.imageUrl || character.sheetUrl;
          return (
            <button
              type="button"
              key={character.characterId}
              className={`character-library__item ${selected ? 'is-selected' : ''}`}
              aria-pressed={selected}
              onClick={() => onSelect(character.characterId)}
            >
              <span className="character-library__index">{String(index + 1).padStart(2, '0')}</span>
              <span className="character-library__avatar">
                {thumbnail ? <img src={thumbnail} alt="" /> : <UserRound size={21} aria-hidden="true" />}
              </span>
              <span className="character-library__copy">
                <span className="character-library__name">{character.name}</span>
                <span className="character-library__role">{character.role || '剧情角色'}</span>
                <span className={`character-library__state is-${character.regenerating ? 'regenerating' : character.assetState.toLowerCase()}`}>
                  {character.regenerating ? t('重新生成中') : CHARACTER_STATE_LABELS[character.assetState]}
                </span>
              </span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="character-library__empty" role="status">
            <Search size={24} aria-hidden="true" />
            <strong>{t('没有匹配角色')}</strong>
            <span>{t('换一个姓名或身份关键词试试。')}</span>
          </div>
        )}
      </div>
    </aside>
  );
}

function DefinitionRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="character-definition-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function CharacterInspector({ character, onRegenerate }: {
  character: CharacterDashboardCharacter;
  /** 只为这一名角色重新出设定集(mode=sheet)或只补高清身份视图(mode=hd)，都付费；不传则不显示按钮。 */
  onRegenerate?: (name: string, mode: CharacterRegenerateMode) => void;
}) {
  const [stateId, setStateId] = useState('');
  const [themeSelection, setThemeSelection] = useState({ characterId: character.characterId, index: 0 });
  const [showFullProfile, setShowFullProfile] = useState(false);
  const activeColorIndex = themeSelection.characterId === character.characterId ? themeSelection.index : 0;
  const activeState = character.states.find(state => state.stateId === stateId) || character.states[0];
  const available = character.views.filter(view => view.available).length;

  return (
    <aside className="character-inspector" aria-labelledby="character-inspector-title">
      <header className="character-panel-heading">
        <div>
          <span className="character-section-kicker">IDENTITY DNA</span>
          <h2 id="character-inspector-title">{t('角色基因档案')}</h2>
        </div>
        <CharacterStatusBadge status={character.assetState} />
      </header>

      <section className="character-inspector__identity" aria-label={t('角色基本信息')}>
        <div className="character-inspector__monogram" aria-hidden="true">{character.name.slice(0, 1)}</div>
        <div>
          <h3>{character.name}</h3>
          <p>{character.identity || character.description || '身份信息待编剧资产补充'}</p>
          <code>{character.characterId}</code>
        </div>
        <button
          type="button"
          className="character-detail-trigger"
          aria-haspopup="dialog"
          aria-label={`查看${character.name}完整角色档案`}
          onClick={() => setShowFullProfile(true)}
        >
          <Maximize2 size={14} aria-hidden="true" /> {t('完整档案')}
        </button>
      </section>

      {onRegenerate && (
        <section className="character-inspector__regenerate" aria-label={t('重新生成设定集')}>
          <button
            type="button"
            className="character-detail-trigger"
            disabled={Boolean(character.regenerating)}
            aria-label={`重新生成${character.name}的设定集`}
            onClick={() => {
              const confirmed = window.confirm(
                `重新为「${character.name}」生成一张数字演员设定集？\n这是一次付费出图，以现在的主肖像为身份参考；新图通过质检后才替换旧图，未通过则保留旧图。`,
              );
              if (confirmed) onRegenerate(character.name, 'sheet');
            }}
          >
            <RefreshCcw size={14} aria-hidden="true" /> {character.regenerating ? t('设定集生成中…') : t('重新生成设定集')}
          </button>
          <button
            type="button"
            className="character-detail-trigger"
            disabled={Boolean(character.regenerating)}
            aria-label={`为${character.name}生成高清身份视图`}
            onClick={() => {
              const confirmed = window.confirm(
                `为「${character.name}」补出高清身份视图？\n会以现有图片为身份参考再出两张图(三张脸、三张全身)，替换六个身份视图；设定集本身不变。`,
              );
              if (confirmed) onRegenerate(character.name, 'hd');
            }}
          >
            <Sparkles size={14} aria-hidden="true" /> {t('生成高清身份视图')}
          </button>
          {fillableDetailCount(character) > 0 && (
            <button
              type="button"
              className="character-detail-trigger"
              disabled={Boolean(character.regenerating)}
              aria-label={`为${character.name}补画细节格`}
              onClick={() => {
                if (confirmDetailFill(character)) onRegenerate(character.name, 'details');
              }}
            >
              <WandSparkles size={14} aria-hidden="true" /> {`补画细节格（${fillableDetailCount(character)}）`}
            </button>
          )}
          {character.regenerating && <small role="status">{t('后台生成中，完成后自动刷新，其他角色不受影响。')}</small>}
          {!character.regenerating && character.regenerationError && (
            <small className="character-inspector__regenerate-error" role="alert">
              上次重新生成未成功：{character.regenerationError}（已保留原图）
            </small>
          )}
        </section>
      )}

      <dl className="character-inspector__facts">
        <DefinitionRow label={t('剧情职能')} value={character.role} />
        <DefinitionRow label={t('声音 ID')} value={character.voiceId} />
        <DefinitionRow label={t('角色描述')} value={character.description} />
      </dl>

      {character.colors.length > 0 && (
        <section className="character-inspector__palette" aria-labelledby="character-palette-title">
          <h3 id="character-palette-title">{t('主题锁定')}</h3>
          <div aria-label={`${character.name} 主题色`}>
            {character.colors.map((color, index) => (
              <button
                type="button"
                key={`${color.hex}-${index}`}
                className={activeColorIndex === index ? 'is-active' : ''}
                aria-label={`选择主题色${color.name || color.hex}`}
                aria-pressed={activeColorIndex === index}
                onClick={() => setThemeSelection({ characterId: character.characterId, index })}
              >
                <i style={{ '--character-swatch': color.hex || '#846874' } as CSSProperties} aria-hidden="true" />
                {color.name || color.hex}
              </button>
            ))}
          </div>
        </section>
      )}

      {character.states.length > 0 && (
        <section className="character-inspector__states" aria-labelledby="character-state-title">
          <h3 id="character-state-title">{t('造型状态')}</h3>
          <div aria-label={`${character.name} 造型状态`}>
            {character.states.map((state, index) => {
              const selected = state.stateId === activeState?.stateId;
              return (
                <button
                  type="button"
                  key={state.stateId}
                  aria-pressed={selected}
                  onClick={() => setStateId(state.stateId)}
                >
                  {state.title || `状态 ${index + 1}`}
                </button>
              );
            })}
          </div>
          {activeState && (
            <dl className="character-inspector__state-detail">
              <DefinitionRow label={t('身份 DNA')} value={activeState.dna} />
              <DefinitionRow label={t('发型')} value={activeState.hair} />
              <DefinitionRow label={t('体型')} value={activeState.body} />
              <DefinitionRow label={t('服装')} value={activeState.clothing} />
              <DefinitionRow label={t('配饰')} value={activeState.accessories} />
              <DefinitionRow label={t('视觉风格')} value={activeState.style} />
            </dl>
          )}
        </section>
      )}

      <section className="character-inspector__readiness" aria-label={t('身份视图就绪度')}>
        <div><span>{t('身份视图就绪度')}</span><strong>{available} / 5</strong></div>
        <progress value={available} max={5}>{available} / 5</progress>
        <small>{character.quality.passed === true ? t('身份一致性质检已通过') : t('需全部视图可用并通过身份一致性质检')}</small>
      </section>

      {showFullProfile && (
        <CharacterDetailDialog
          title={`${character.name} · 完整角色档案`}
          onClose={() => setShowFullProfile(false)}
        >
          <div className="character-dialog__profile">
            <section>
              <span className="character-section-kicker">IDENTITY DNA</span>
              <h3>{character.name}</h3>
              <p>{character.identity || '身份信息待编剧资产补充'}</p>
              <code>{character.characterId}</code>
            </section>
            <dl>
              <DefinitionRow label={t('剧情职能')} value={character.role} />
              <DefinitionRow label={t('声音 ID')} value={character.voiceId} />
              <DefinitionRow label={t('角色描述')} value={character.description} />
              <DefinitionRow label={t('身份 DNA')} value={activeState?.dna} />
              <DefinitionRow label={t('发型')} value={activeState?.hair} />
              <DefinitionRow label={t('体型')} value={activeState?.body} />
              <DefinitionRow label={t('服装')} value={activeState?.clothing} />
              <DefinitionRow label={t('配饰')} value={activeState?.accessories} />
              <DefinitionRow label={t('视觉风格')} value={activeState?.style} />
            </dl>
          </div>
        </CharacterDetailDialog>
      )}
    </aside>
  );
}

function promptFor(character: CharacterDashboardCharacter, contract: CharacterViewContract): string {
  const state = character.states[0];
  const identity = state?.dna || character.identity || character.description || '锁定人物身份特征';
  const styling = [state?.hair, state?.body, state?.clothing, state?.accessories, state?.style].filter(Boolean).join('；');
  const views = contract.views.map(view => `${view.labelZh} ${view.angleDegrees}°`).join(' / ');
  const anchors = state?.anchors.map(anchor => `${anchor.view}: ${anchor.detail}`).filter(item => !item.endsWith(': ')).join('；');
  return [
    `${character.name}，${identity}。`,
    styling,
    `同一人物、同一服装、同一发型、同一体型；固定顺序：${views}。`,
    anchors ? `可见锚点：${anchors}。` : '',
    '纯色中性背景，全身站姿，等距构图，真实材质，禁止镜像替代与重复视角。',
  ].filter(Boolean).join('\n');
}

export function CharacterEvidencePanels({
  dashboard,
  character,
}: {
  dashboard: CharacterDashboardResponse;
  character: CharacterDashboardCharacter;
}) {
  const quality = character.quality;
  const [detail, setDetail] = useState<'prompt' | 'quality' | 'source' | null>(null);
  const prompt = promptFor(character, dashboard.viewContract);
  const sourceText = [
    character.description || character.identity,
    dashboard.rawText,
  ].filter(Boolean).join('\n\n');
  return (
    <div className="character-evidence">
      <section className="character-evidence__panel" aria-labelledby="character-prompt-title">
        <header>
          <Sparkles size={17} aria-hidden="true" /><h2 id="character-prompt-title">{t('设定集提示词')}</h2>
          <button type="button" aria-haspopup="dialog" aria-label={t('查看设定集提示词完整内容')} onClick={() => setDetail('prompt')}>
            <Maximize2 size={14} aria-hidden="true" /> {t('查看完整内容')}
          </button>
        </header>
        <pre>{prompt}</pre>
      </section>

      <section className="character-evidence__panel" aria-labelledby="character-quality-title">
        <header>
          <ShieldCheck size={17} aria-hidden="true" /><h2 id="character-quality-title">{t('质量报告')}</h2>
          <button type="button" aria-haspopup="dialog" aria-label={t('查看质量报告完整内容')} onClick={() => setDetail('quality')}>
            <Maximize2 size={14} aria-hidden="true" /> {t('查看完整内容')}
          </button>
        </header>
        <div className="character-quality-grid">
          <span><small>{t('检测结果')}</small><strong>{quality.passed === true ? 'PASS' : quality.passed === false ? 'FAIL' : 'PENDING'}</strong></span>
          <span><small>{t('色板相似度')}</small><strong>{quality.paletteSimilarity === null ? '—' : `${Math.round(quality.paletteSimilarity * 100)}%`}</strong></span>
          <span><small>{t('唯一视图')}</small><strong>{quality.uniqueViewHashes === null ? '—' : `${quality.uniqueViewHashes} / 5`}</strong></span>
        </div>
        {quality.issues.length > 0 ? (
          <ul className="character-quality-issues">
            {quality.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}><TriangleAlert size={14} aria-hidden="true" /><span>{issue.message || issue.code}</span></li>
            ))}
          </ul>
        ) : (
          <p className="character-quality-empty">{quality.passed ? t('五个视角差异与角色身份一致性均符合交付门槛。') : t('后端质检完成后，将在这里列出重复视角、低信息量或色板漂移。')}</p>
        )}
      </section>

      <section className="character-evidence__panel" aria-labelledby="character-source-title">
        <header>
          <FileText size={17} aria-hidden="true" /><h2 id="character-source-title">{t('角色原文与风险')}</h2>
          <button type="button" aria-haspopup="dialog" aria-label={t('查看角色原文与风险完整内容')} onClick={() => setDetail('source')}>
            <Maximize2 size={14} aria-hidden="true" /> {t('查看完整内容')}
          </button>
        </header>
        {dashboard.risks.length > 0 && (
          <ul className="character-risk-list">
            {dashboard.risks.slice(0, 3).map((risk, index) => (
              <li key={`${risk.item}-${index}`} data-status={risk.status}>
                <strong>{risk.status}</strong><span>{risk.item}{risk.note ? ` · ${risk.note}` : ''}</span>
              </li>
            ))}
          </ul>
        )}
        <pre>{sourceText || '角色设计原文尚未生成。'}</pre>
      </section>

      {detail === 'prompt' && (
        <CharacterDetailDialog title={t('设定集提示词')} onClose={() => setDetail(null)}>
          <pre className="character-dialog__pre">{prompt}</pre>
        </CharacterDetailDialog>
      )}
      {detail === 'quality' && (
        <CharacterDetailDialog title={t('质量报告')} onClose={() => setDetail(null)}>
          <div className="character-dialog__quality">
            <dl>
              <DefinitionRow label={t('检测结果')} value={quality.passed === true ? 'PASS' : quality.passed === false ? 'FAIL' : 'PENDING'} />
              <DefinitionRow label={t('色板相似度')} value={quality.paletteSimilarity === null ? '—' : `${Math.round(quality.paletteSimilarity * 100)}%`} />
              <DefinitionRow label={t('唯一视图')} value={quality.uniqueViewHashes === null ? '—' : `${quality.uniqueViewHashes} / 5`} />
            </dl>
            {quality.issues.length > 0 ? (
              <ul className="character-quality-issues">
                {quality.issues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`}><TriangleAlert size={14} aria-hidden="true" /><span>{issue.message || issue.code}</span></li>
                ))}
              </ul>
            ) : (
              <p>{quality.passed ? t('五个视角差异与角色身份一致性均符合交付门槛。') : t('后端质检完成后，将在这里列出重复视角、低信息量或色板漂移。')}</p>
            )}
          </div>
        </CharacterDetailDialog>
      )}
      {detail === 'source' && (
        <CharacterDetailDialog title={t('角色原文与风险')} onClose={() => setDetail(null)}>
          <div className="character-dialog__source">
            {dashboard.risks.length > 0 && (
              <ul className="character-risk-list">
                {dashboard.risks.map((risk, index) => (
                  <li key={`${risk.item}-${index}`} data-status={risk.status}>
                    <strong>{risk.status}</strong><span>{risk.item}{risk.note ? ` · ${risk.note}` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
            <MarkdownDocument
              source={sourceText || '角色设计原文尚未生成。'}
              ariaLabel="角色原文"
              className="character-dialog__markdown"
            />
          </div>
        </CharacterDetailDialog>
      )}
    </div>
  );
}
