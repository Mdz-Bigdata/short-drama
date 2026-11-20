import { AlertTriangle, Check, ChevronDown, ChevronUp, Clapperboard, Undo2, UserRound, Wrench, X } from 'lucide-react';
import { useState } from 'react';
import { t } from '../../i18n';
import type { ChatCard, StageChanged } from './chatCards';
import './ChatCardView.css';

/**
 * 聊天气泡里的卡片：助手改了什么、还等什么确认、这一轮调了哪些工具。
 *
 * 卡片只渲染在已有的 .chat-bubble.ai 里，不另起布局；按钮都交回外层：
 * 打开哪个看板、撤销怎么发，由工作台决定，这里只说"用户点了什么"。
 */

interface Props {
  card: ChatCard;
  /** 助手正在处理上一条：确认、放弃、撤销这类会再发一条指令的按钮先停一停。 */
  busy: boolean;
  onSend: (message: string) => void;
  onOpenCharacter?: (name: string) => void;
  onOpenStage?: (sceneId: string) => void;
  onUndoStage?: (sceneId: string, snapshotId: string) => void;
  onUndoFace?: (name: string, snapshotId: string) => void;
}

/** 超过这个长度的描述默认只露两行，点「展开」才全看。 */
const CLAMP_HINT_CHARS = 48;

function Clamped({ label, text }: { label: string; text: string }) {
  const [expanded, setExpanded] = useState(false);
  const canToggle = text.length > CLAMP_HINT_CHARS;
  return (
    <div className="chat-card__row">
      <span className="chat-card__label">{label}</span>
      <div className="chat-card__row-body">
        <p className={`chat-card__clamp${expanded || !canToggle ? '' : ' is-collapsed'}`}>{text || t('（空）')}</p>
        {canToggle && (
          <button type="button" className="chat-card__link" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
            {expanded ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />}
            {expanded ? t('收起') : t('展开')}
          </button>
        )}
      </div>
    </div>
  );
}

function FaceCard({ card, busy, onOpenCharacter, onUndoFace }: Props & { card: Extract<ChatCard, { kind: 'face_sculpt_changed' }> }) {
  return (
    <section className="chat-card chat-card--face" aria-label={t('捏脸已更新 · {name}', { name: card.name })}>
      <header className="chat-card__head">
        <strong className="chat-card__title">{t('捏脸已更新 · {name}', { name: card.name })}</strong>
        {card.sheetStale && (
          <span className="chat-card__badge is-warning"><AlertTriangle size={12} aria-hidden="true" />{t('定妆照需重出')}</span>
        )}
        {card.revision > 0 && <span className="chat-card__meta">{t('第 {n} 版', { n: card.revision })}</span>}
      </header>
      <Clamped label={t('改前')} text={card.before} />
      <Clamped label={t('改后')} text={card.after} />
      {(onOpenCharacter || (card.snapshotId && onUndoFace)) && (
        <footer className="chat-card__actions">
          {onOpenCharacter && (
            <button type="button" className="capsule-btn chat-card__btn" onClick={() => onOpenCharacter(card.name)}>
              <UserRound size={13} aria-hidden="true" />{t('打开角色页')}
            </button>
          )}
          {card.snapshotId && onUndoFace && (
            <button type="button" className="capsule-btn chat-card__btn" disabled={busy}
              onClick={() => onUndoFace(card.name, card.snapshotId as string)}>
              <Undo2 size={13} aria-hidden="true" />{t('撤销这一步')}
            </button>
          )}
        </footer>
      )}
    </section>
  );
}

type Chip = { name: string; tone?: 'added' | 'changed' | 'removed' };

function chipGroups(changed: StageChanged): Array<{ label: string; chips: Chip[] }> {
  return [
    { label: t('人物'), chips: changed.actors.map(name => ({ name })) },
    {
      label: t('布景'),
      chips: [
        ...changed.pieces_added.map(name => ({ name, tone: 'added' as const })),
        ...changed.pieces_changed.map(name => ({ name, tone: 'changed' as const })),
        ...changed.pieces_removed.map(name => ({ name, tone: 'removed' as const })),
      ],
    },
    { label: t('机位'), chips: changed.cameras.map(name => ({ name })) },
  ].filter(group => group.chips.length);
}

const TONE_TITLE: Record<NonNullable<Chip['tone']>, string> = { added: '新增', changed: '改动', removed: '移除' };
const TONE_MARK: Record<NonNullable<Chip['tone']>, string> = { added: '+', changed: '', removed: '−' };

function StageCard({ card, busy, onOpenStage, onUndoStage }: Props & { card: Extract<ChatCard, { kind: 'stage_changed' }> }) {
  const groups = card.changed ? chipGroups(card.changed) : [];
  return (
    <section className="chat-card chat-card--stage" aria-label={t('舞台已改 · {scene}', { scene: card.sceneId })}>
      <header className="chat-card__head">
        <strong className="chat-card__title">{t('舞台已改 · {scene}', { scene: card.sceneId })}</strong>
        {card.revision > 0 && <span className="chat-card__meta">{t('第 {n} 版', { n: card.revision })}</span>}
      </header>
      {card.summary && <p className="chat-card__summary">{card.summary}</p>}
      {groups.map(group => (
        <div key={group.label} className="chat-card__row">
          <span className="chat-card__label">{group.label}</span>
          <div className="chat-card__chips">
            {group.chips.map((chip, index) => (
              <span key={`${chip.name}:${index}`} className={`chat-card__chip${chip.tone ? ` is-${chip.tone}` : ''}`}
                title={chip.tone ? t(TONE_TITLE[chip.tone]) : undefined}>
                {chip.tone ? TONE_MARK[chip.tone] : ''}{chip.name}
              </span>
            ))}
          </div>
        </div>
      ))}
      {card.failingChecks.length > 0 && (
        <div className="chat-card__checks" role="note">
          <span className="chat-card__badge is-danger"><AlertTriangle size={12} aria-hidden="true" />{t('未通过检查')}</span>
          <ul>
            {card.failingChecks.map(check => <li key={check}>{check}</li>)}
          </ul>
        </div>
      )}
      {(onOpenStage || (card.snapshotId && onUndoStage)) && (
        <footer className="chat-card__actions">
          {onOpenStage && (
            <button type="button" className="capsule-btn chat-card__btn" onClick={() => onOpenStage(card.sceneId)}>
              <Clapperboard size={13} aria-hidden="true" />{t('到导演台看这场')}
            </button>
          )}
          {card.snapshotId && onUndoStage && (
            <button type="button" className="capsule-btn chat-card__btn" disabled={busy}
              onClick={() => onUndoStage(card.sceneId, card.snapshotId as string)}>
              <Undo2 size={13} aria-hidden="true" />{t('撤销这一步')}
            </button>
          )}
        </footer>
      )}
    </section>
  );
}

/** 提议里的参数压成一行「键=值」：用户确认的是这个范围，不只是一个工具名。 */
function argumentLine(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([key, value]) => key !== 'task_id' && value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('、') : typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join('，');
}

function ProposalCard({ card, busy, onSend }: Props & { card: Extract<ChatCard, { kind: 'proposal' }> }) {
  const scope = argumentLine(card.arguments);
  return (
    <section className="chat-card chat-card--proposal" aria-label={t('等您确认')}>
      <header className="chat-card__head">
        <strong className="chat-card__title">{t('等您确认')}</strong>
        <span className="chat-card__meta">{card.tool}</span>
      </header>
      <p className="chat-card__summary">{card.message}</p>
      {scope && <p className="chat-card__args" title={t('这次确认的参数')}>{scope}</p>}
      <footer className="chat-card__actions">
        <button type="button" className="capsule-btn chat-card__btn is-primary" disabled={busy} onClick={() => onSend('/confirm')}>
          <Check size={13} aria-hidden="true" />{t('确认执行')}
        </button>
        <button type="button" className="capsule-btn chat-card__btn" disabled={busy} onClick={() => onSend('/cancel')}>
          <X size={13} aria-hidden="true" />{t('放弃')}
        </button>
      </footer>
    </section>
  );
}

function ToolCallsCard({ card }: { card: Extract<ChatCard, { kind: 'tool_calls' }> }) {
  const failed = card.calls.filter(call => !call.ok).length;
  return (
    <details className="chat-card chat-card--tools">
      <summary className="chat-card__tools-line">
        <Wrench size={12} aria-hidden="true" />
        <span>{t('调用了 {n} 个工具', { n: card.calls.length })}</span>
        {failed > 0 && <span className="chat-card__badge is-danger">{t('{n} 个失败', { n: failed })}</span>}
      </summary>
      <ul className="chat-card__tools">
        {card.calls.map((call, index) => (
          <li key={`${call.tool}:${index}`} className={call.ok ? 'is-ok' : 'is-failed'}>
            <code>{call.tool}</code>
            <span>{call.ok ? t('成功') : call.error || t('失败')}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ChatCardView(props: Props) {
  const { card } = props;
  switch (card.kind) {
    case 'face_sculpt_changed':
      return <FaceCard {...props} card={card} />;
    case 'stage_changed':
      return <StageCard {...props} card={card} />;
    case 'proposal':
      return <ProposalCard {...props} card={card} />;
    case 'tool_calls':
      return <ToolCallsCard card={card} />;
    default:
      return null;
  }
}
