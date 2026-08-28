import { useMemo, useState } from 'react';
import { ArrowRight, CheckCircle2, ChevronDown, Download, FileText, RefreshCw, Sparkles } from 'lucide-react';

import { StoryboardPromptDialog } from './StoryboardPromptDialog';
import { STORYBOARD_VISUAL_THEME } from './storyboardTheme';
import { downloadStoryboardGrid, downloadStoryboardScene, downloadStoryboardShot } from './storyboardDownload';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';
import './StoryboardWorkspace.css';


export interface StoryboardShot {
  shot_id?: number;
  image_url?: string | null;
  size?: string;
  motion?: string;
  desc?: string;
  scene?: string;
  scene_id?: string;
  sceneId?: string;
}

interface StoryboardScene {
  id: string;
  title: string;
  shots: StoryboardShot[];
}

interface StoryboardWorkspaceProps {
  title: string;
  shots: StoryboardShot[];
  taskId?: string;
  gridUrl?: string;
  prompt?: string;
  promptDetail?: StoryboardPromptDetail;
  onRefresh: () => void;
  onRegenerate: () => void;
  onContinue?: () => void;
}


function sceneCode(shot: StoryboardShot, fallbackIndex: number) {
  return shot.scene_id || shot.sceneId || `E1S${String(Math.floor(fallbackIndex / 9) + 1).padStart(2, '0')}`;
}

function buildScenes(shots: StoryboardShot[]): StoryboardScene[] {
  const byId = new Map<string, StoryboardScene>();
  shots.forEach((shot, index) => {
    const id = sceneCode(shot, index);
    const existing = byId.get(id);
    if (existing) {
      existing.shots.push(shot);
      return;
    }
    const rawTitle = shot.scene?.trim();
    const title = rawTitle && !/继承.*场景圣经/.test(rawTitle) ? rawTitle : '连续场景';
    byId.set(id, { id, title, shots: [shot] });
  });
  return [...byId.values()];
}

interface StoryboardEpisodeGroup {
  number: number;
  scenes: StoryboardScene[];
}

function sceneEpisodeNumber(sceneId: string) {
  const match = sceneId.match(/E(\d{1,3})/i);
  return match ? Math.max(1, Math.min(200, Number(match[1]))) : 1;
}

function buildEpisodeGroups(scenes: StoryboardScene[]): StoryboardEpisodeGroup[] {
  const byEpisode = new Map<number, StoryboardScene[]>();
  scenes.forEach(scene => {
    const number = sceneEpisodeNumber(scene.id);
    const bucket = byEpisode.get(number);
    if (bucket) bucket.push(scene);
    else byEpisode.set(number, [scene]);
  });
  return [...byEpisode.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([number, groupScenes]) => ({ number, scenes: groupScenes }));
}

const GRID_SLOTS = 9;

function DownloadAction({
  onDownload,
  disabled,
  busy,
  children,
}: {
  onDownload: () => void;
  disabled?: boolean;
  busy?: boolean;
  children: string;
}) {
  return (
    <button
      type="button"
      className="storyboard-action"
      onClick={onDownload}
      disabled={disabled || busy}
    >
      <Download aria-hidden="true" /> {busy ? '下载中…' : children}
    </button>
  );
}

function StoryboardFrameMedia({ shot, alt }: { shot: StoryboardShot; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!shot.image_url) {
    return <div className="storyboard-frame__placeholder">分镜生成中</div>;
  }
  if (failed) {
    return <div className="storyboard-frame__placeholder">分镜图片暂不可用</div>;
  }
  return <img src={shot.image_url} alt={alt} onError={() => setFailed(true)} />;
}


export function StoryboardWorkspace({
  title,
  shots,
  taskId,
  gridUrl,
  prompt,
  promptDetail,
  onRefresh,
  onRegenerate,
  onContinue,
}: StoryboardWorkspaceProps) {
  const normalizedShots = useMemo(() => (Array.isArray(shots) ? shots : []), [shots]);
  const scenes = useMemo(() => buildScenes(normalizedShots), [normalizedShots]);
  const episodeGroups = useMemo(() => buildEpisodeGroups(scenes), [scenes]);
  const [selectedSceneId, setSelectedSceneId] = useState<string>(() => scenes[0]?.id || '');
  const [selectedFrameIndex, setSelectedFrameIndex] = useState(0);
  const [showPrompt, setShowPrompt] = useState(false);
  const [downloadBusyKey, setDownloadBusyKey] = useState('');
  const [downloadNotice, setDownloadNotice] = useState('');
  const [collapsedEpisodes, setCollapsedEpisodes] = useState<ReadonlySet<number>>(new Set());
  const selectedScene = scenes.find(scene => scene.id === selectedSceneId) || scenes[0];
  const selectedEpisodeNumber = selectedScene ? sceneEpisodeNumber(selectedScene.id) : 1;
  const completedScenes = scenes.filter(scene => scene.shots.length > 0 && scene.shots.every(shot => Boolean(shot.image_url))).length;

  const toggleEpisode = (number: number) => {
    setCollapsedEpisodes(current => {
      const next = new Set(current);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      return next;
    });
  };

  const runDownload = async (busyKey: string, request: () => Promise<boolean>) => {
    if (downloadBusyKey) return;
    setDownloadBusyKey(busyKey);
    setDownloadNotice('');
    const succeeded = await request();
    setDownloadBusyKey('');
    setDownloadNotice(succeeded ? '' : '分镜图下载失败，请确认后端服务可用后重试。');
  };

  const downloadGrid = (filenameBase: string) => {
    if (!taskId) return;
    void runDownload('grid', () => downloadStoryboardGrid(taskId, filenameBase));
  };

  // The per-scene action composes that scene's own board, so the saved file
  // always matches the scene named in its filename.
  const downloadScene = (sceneId: string) => {
    if (!taskId) return;
    void runDownload(`scene-${sceneId}`, () => downloadStoryboardScene(taskId, sceneId, `${sceneId}-时序分镜`));
  };

  const downloadShot = (shot: StoryboardShot, sceneId: string, frameNumber: number) => {
    if (!taskId || !shot.image_url) return;
    const shotIndex = normalizedShots.indexOf(shot);
    if (shotIndex < 0) return;
    void runDownload(
      `shot-${shotIndex}`,
      () => downloadStoryboardShot(taskId, shotIndex, `${sceneId}-分镜${frameNumber}`),
    );
  };

  if (!selectedScene) {
    return (
      <section
        className="storyboard-workspace storyboard-workspace--empty"
        data-visual-theme={STORYBOARD_VISUAL_THEME.id}
        aria-labelledby="storyboard-title"
      >
        <h1 id="storyboard-title">分镜故事板</h1>
        <p>暂无可展示的时序分镜。</p>
        <button type="button" className="storyboard-action" onClick={onRefresh}>
          <RefreshCw aria-hidden="true" /> 刷新
        </button>
      </section>
    );
  }

  return (
    <section className="storyboard-workspace" data-visual-theme={STORYBOARD_VISUAL_THEME.id} aria-labelledby="storyboard-title">
      <header className="storyboard-header">
        <div className="storyboard-heading">
          <h1 id="storyboard-title">分镜故事板</h1>
          <p>第 {selectedEpisodeNumber} 集 · {title}</p>
          <span className="storyboard-progress">{completedScenes}/{scenes.length} 个分镜场景已完成</span>
        </div>
        <div className="storyboard-header-actions" aria-label="故事板操作">
          <DownloadAction
            onDownload={() => downloadGrid('全部分镜图')}
            disabled={!taskId || !gridUrl}
            busy={downloadBusyKey === 'grid'}
          >
            下载全部分镜图
          </DownloadAction>
          <button type="button" className="storyboard-action" onClick={onRefresh}>
            <RefreshCw aria-hidden="true" /> 刷新
          </button>
          <button type="button" className="storyboard-action" onClick={onRegenerate}>
            <Sparkles aria-hidden="true" /> 一键创作全部分镜页
          </button>
        </div>
      </header>

      {downloadNotice && <p className="storyboard-download-notice" role="status">{downloadNotice}</p>}

      <div className="storyboard-body">
        <aside className="storyboard-scene-nav" aria-label="分集与时序分镜目录">
          <div className="storyboard-scene-nav__heading">
            <span>时序分镜</span>
            <strong>共 {episodeGroups.length} 集</strong>
            <small>{title}</small>
          </div>
          <div className="storyboard-scene-list">
            {episodeGroups.map(group => {
              const expanded = !collapsedEpisodes.has(group.number);
              const completeCount = group.scenes.filter(scene => scene.shots.length > 0 && scene.shots.every(shot => Boolean(shot.image_url))).length;
              return (
                <div className="storyboard-episode-group" key={group.number}>
                  <button
                    type="button"
                    className={`storyboard-episode-toggle ${group.number === selectedEpisodeNumber ? 'is-current' : ''}`}
                    aria-expanded={expanded}
                    onClick={() => toggleEpisode(group.number)}
                  >
                    <ChevronDown aria-hidden="true" className={expanded ? '' : 'is-collapsed'} />
                    <strong>第 {group.number} 集</strong>
                    <span>{completeCount}/{group.scenes.length} 个分镜场景</span>
                  </button>
                  {expanded && group.scenes.map(scene => {
                    const isSelected = scene.id === selectedScene.id;
                    const isComplete = scene.shots.every(shot => Boolean(shot.image_url));
                    return (
                      <button
                        key={scene.id}
                        type="button"
                        className={`storyboard-scene-card ${isSelected ? 'is-selected' : ''}`}
                        onClick={() => {
                          setSelectedSceneId(scene.id);
                          setSelectedFrameIndex(0);
                        }}
                        aria-pressed={isSelected}
                      >
                        <span className="storyboard-scene-card__topline">
                          <strong>{scene.id}</strong>
                          <span className="storyboard-scene-card__format">3 × 3</span>
                          <span className={`storyboard-scene-card__status ${isComplete ? 'is-complete' : ''}`}>
                            {isComplete ? <CheckCircle2 aria-hidden="true" /> : <span aria-hidden="true">◌</span>}
                            {isComplete ? '已完成' : '待创作'}
                          </span>
                        </span>
                        <span className="storyboard-scene-card__title">{scene.title}</span>
                        <span className="storyboard-scene-card__count">{scene.shots.length} 个连续瞬间</span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </aside>

        <main className="storyboard-main">
          <div className="storyboard-main-toolbar">
            <div>
              <h2>{selectedScene.id} 时序分镜</h2>
              <p><strong>3×3</strong><span aria-hidden="true">·</span>{selectedScene.shots.length} 个连续瞬间</p>
            </div>
            <div className="storyboard-main-actions">
              <DownloadAction
                onDownload={() => downloadScene(selectedScene.id)}
                disabled={!taskId || !selectedScene.shots.some(shot => Boolean(shot.image_url))}
                busy={downloadBusyKey === `scene-${selectedScene.id}`}
              >
                下载本图
              </DownloadAction>
              <button
                type="button"
                className="storyboard-action"
                onClick={() => setShowPrompt(value => !value)}
                aria-expanded={showPrompt}
              >
                <FileText aria-hidden="true" /> 查看提示词
              </button>
              <button type="button" className="storyboard-action" onClick={onRegenerate}>
                <RefreshCw aria-hidden="true" /> 重新创作本分镜
              </button>
            </div>
          </div>

          <div className="storyboard-grid" aria-label={`${selectedScene.id} 3×3 时序分镜`}>
            {Array.from(
              { length: Math.max(GRID_SLOTS, selectedScene.shots.length) },
              (_, index) => selectedScene.shots[index] ?? null,
            ).map((shot, index) => {
              const number = index + 1;
              if (!shot) {
                return (
                  <div className="storyboard-frame storyboard-frame--vacant" key={`${selectedScene.id}-vacant-${number}`}>
                    <span className="storyboard-frame__vacant-label">画格 {number} · 空位</span>
                  </div>
                );
              }
              const downloadable = Boolean(taskId && shot.image_url);
              return (
                <button
                  type="button"
                  className={`storyboard-frame ${selectedFrameIndex === index ? 'is-selected' : ''}`}
                  key={`${selectedScene.id}-${number}`}
                  aria-label={downloadable ? `下载分镜 ${number}` : `选择分镜 ${number}`}
                  aria-pressed={selectedFrameIndex === index}
                  onClick={() => {
                    setSelectedFrameIndex(index);
                    downloadShot(shot, selectedScene.id, number);
                  }}
                >
                  <StoryboardFrameMedia
                    key={shot.image_url || 'pending'}
                    shot={shot}
                    alt={`${selectedScene.id} 分镜 ${number}：${shot.desc || '连续画面'}`}
                  />
                  <span className="storyboard-frame__caption">
                    <span className="storyboard-frame__number">{number}</span>
                    <span className="storyboard-frame__meta">{shot.size || '景别待定'} · {shot.motion || '运镜待定'}</span>
                  </span>
                  {downloadable && (
                    <span className="storyboard-frame__download" aria-hidden="true">
                      <Download /> 点击下载
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </main>
      </div>

      <footer className="storyboard-footer">
        <div>
          <strong>{completedScenes}/{scenes.length} 个分镜场景已完成</strong>
          <span>{shots.filter(shot => Boolean(shot.image_url)).length}/{shots.length} 个画格已生成</span>
        </div>
        <button type="button" onClick={onContinue} disabled={!onContinue}>
          确认分镜，继续视觉制作 <ArrowRight aria-hidden="true" />
        </button>
      </footer>
      {showPrompt && (
        <StoryboardPromptDialog
          detail={promptDetail}
          fallbackPrompt={prompt}
          onClose={() => setShowPrompt(false)}
        />
      )}
    </section>
  );
}
