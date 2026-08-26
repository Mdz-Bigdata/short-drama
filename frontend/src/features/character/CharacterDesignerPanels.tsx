import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileText,
  ImageOff,
  Maximize2,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserRound,
  XCircle,
} from 'lucide-react';
import { useState, type CSSProperties } from 'react';

import { MarkdownDocument } from '../writer/MarkdownDocument';
import { CharacterDetailDialog } from './CharacterDetailDialog';
import {
  CHARACTER_STATE_LABELS,
  type CharacterAssetState,
  type CharacterDashboardCharacter,
  type CharacterDashboardResponse,
  type CharacterViewContract,
} from './types';

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
          <h2 id="character-library-title">角色库</h2>
        </div>
        <span className="character-library__total">{characters.length}</span>
      </header>
      <label className="character-library__search">
        <Search size={16} aria-hidden="true" />
        <span className="sr-only">搜索角色</span>
        <input
          type="search"
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="搜索角色、身份、职能"
        />
      </label>
      <div className="character-library__list" aria-live="polite">
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
                <span className={`character-library__state is-${character.assetState.toLowerCase()}`}>
                  {CHARACTER_STATE_LABELS[character.assetState]}
                </span>
              </span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="character-library__empty" role="status">
            <Search size={24} aria-hidden="true" />
            <strong>没有匹配角色</strong>
            <span>换一个姓名或身份关键词试试。</span>
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

export function CharacterInspector({ character }: { character: CharacterDashboardCharacter }) {
  const [stateId, setStateId] = useState('');
  const [showFullProfile, setShowFullProfile] = useState(false);
  const activeState = character.states.find(state => state.stateId === stateId) || character.states[0];
  const available = character.views.filter(view => view.available).length;

  return (
    <aside className="character-inspector" aria-labelledby="character-inspector-title">
      <header className="character-panel-heading">
        <div>
          <span className="character-section-kicker">IDENTITY DNA</span>
          <h2 id="character-inspector-title">角色基因档案</h2>
        </div>
        <CharacterStatusBadge status={character.assetState} />
      </header>

      <section className="character-inspector__identity" aria-label="角色基本信息">
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
          <Maximize2 size={14} aria-hidden="true" /> 完整档案
        </button>
      </section>

      <dl className="character-inspector__facts">
        <DefinitionRow label="剧情职能" value={character.role} />
        <DefinitionRow label="声音 ID" value={character.voiceId} />
        <DefinitionRow label="角色描述" value={character.description} />
      </dl>

      {character.colors.length > 0 && (
        <section className="character-inspector__palette" aria-labelledby="character-palette-title">
          <h3 id="character-palette-title">主色锁定</h3>
          <div>
            {character.colors.map((color, index) => (
              <span key={`${color.hex}-${index}`}>
                <i style={{ '--character-swatch': color.hex || '#64748b' } as CSSProperties} aria-hidden="true" />
                {color.name || color.hex}
              </span>
            ))}
          </div>
        </section>
      )}

      {character.states.length > 0 && (
        <section className="character-inspector__states" aria-labelledby="character-state-title">
          <h3 id="character-state-title">造型状态</h3>
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
              <DefinitionRow label="身份 DNA" value={activeState.dna} />
              <DefinitionRow label="发型" value={activeState.hair} />
              <DefinitionRow label="体型" value={activeState.body} />
              <DefinitionRow label="服装" value={activeState.clothing} />
              <DefinitionRow label="配饰" value={activeState.accessories} />
              <DefinitionRow label="视觉风格" value={activeState.style} />
            </dl>
          )}
        </section>
      )}

      <section className="character-inspector__readiness" aria-label="五视图就绪度">
        <div><span>五视图就绪度</span><strong>{available} / 5</strong></div>
        <progress value={available} max={5}>{available} / 5</progress>
        <small>{character.quality.passed === true ? '身份一致性质检已通过' : '需全部视图可用并通过身份一致性质检'}</small>
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
              <DefinitionRow label="剧情职能" value={character.role} />
              <DefinitionRow label="声音 ID" value={character.voiceId} />
              <DefinitionRow label="角色描述" value={character.description} />
              <DefinitionRow label="身份 DNA" value={activeState?.dna} />
              <DefinitionRow label="发型" value={activeState?.hair} />
              <DefinitionRow label="体型" value={activeState?.body} />
              <DefinitionRow label="服装" value={activeState?.clothing} />
              <DefinitionRow label="配饰" value={activeState?.accessories} />
              <DefinitionRow label="视觉风格" value={activeState?.style} />
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
          <Sparkles size={17} aria-hidden="true" /><h2 id="character-prompt-title">五视图提示词</h2>
          <button type="button" aria-haspopup="dialog" aria-label="查看五视图提示词完整内容" onClick={() => setDetail('prompt')}>
            <Maximize2 size={14} aria-hidden="true" /> 查看完整内容
          </button>
        </header>
        <pre>{prompt}</pre>
      </section>

      <section className="character-evidence__panel" aria-labelledby="character-quality-title">
        <header>
          <ShieldCheck size={17} aria-hidden="true" /><h2 id="character-quality-title">质量报告</h2>
          <button type="button" aria-haspopup="dialog" aria-label="查看质量报告完整内容" onClick={() => setDetail('quality')}>
            <Maximize2 size={14} aria-hidden="true" /> 查看完整内容
          </button>
        </header>
        <div className="character-quality-grid">
          <span><small>检测结果</small><strong>{quality.passed === true ? 'PASS' : quality.passed === false ? 'FAIL' : 'PENDING'}</strong></span>
          <span><small>色板相似度</small><strong>{quality.paletteSimilarity === null ? '—' : `${Math.round(quality.paletteSimilarity * 100)}%`}</strong></span>
          <span><small>唯一视图</small><strong>{quality.uniqueViewHashes === null ? '—' : `${quality.uniqueViewHashes} / 5`}</strong></span>
        </div>
        {quality.issues.length > 0 ? (
          <ul className="character-quality-issues">
            {quality.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}><TriangleAlert size={14} aria-hidden="true" /><span>{issue.message || issue.code}</span></li>
            ))}
          </ul>
        ) : (
          <p className="character-quality-empty">{quality.passed ? '五个视角差异与角色身份一致性均符合交付门槛。' : '后端质检完成后，将在这里列出重复视角、低信息量或色板漂移。'}</p>
        )}
      </section>

      <section className="character-evidence__panel" aria-labelledby="character-source-title">
        <header>
          <FileText size={17} aria-hidden="true" /><h2 id="character-source-title">角色原文与风险</h2>
          <button type="button" aria-haspopup="dialog" aria-label="查看角色原文与风险完整内容" onClick={() => setDetail('source')}>
            <Maximize2 size={14} aria-hidden="true" /> 查看完整内容
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
        <CharacterDetailDialog title="五视图提示词" onClose={() => setDetail(null)}>
          <pre className="character-dialog__pre">{prompt}</pre>
        </CharacterDetailDialog>
      )}
      {detail === 'quality' && (
        <CharacterDetailDialog title="质量报告" onClose={() => setDetail(null)}>
          <div className="character-dialog__quality">
            <dl>
              <DefinitionRow label="检测结果" value={quality.passed === true ? 'PASS' : quality.passed === false ? 'FAIL' : 'PENDING'} />
              <DefinitionRow label="色板相似度" value={quality.paletteSimilarity === null ? '—' : `${Math.round(quality.paletteSimilarity * 100)}%`} />
              <DefinitionRow label="唯一视图" value={quality.uniqueViewHashes === null ? '—' : `${quality.uniqueViewHashes} / 5`} />
            </dl>
            {quality.issues.length > 0 ? (
              <ul className="character-quality-issues">
                {quality.issues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`}><TriangleAlert size={14} aria-hidden="true" /><span>{issue.message || issue.code}</span></li>
                ))}
              </ul>
            ) : (
              <p>{quality.passed ? '五个视角差异与角色身份一致性均符合交付门槛。' : '后端质检完成后，将在这里列出重复视角、低信息量或色板漂移。'}</p>
            )}
          </div>
        </CharacterDetailDialog>
      )}
      {detail === 'source' && (
        <CharacterDetailDialog title="角色原文与风险" onClose={() => setDetail(null)}>
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
