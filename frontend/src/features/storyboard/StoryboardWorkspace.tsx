import { useMemo, useState } from 'react';
import { ArrowRight, CheckCircle2, Download, FileText, RefreshCw, Sparkles } from 'lucide-react';

import { StoryboardPromptDialog } from './StoryboardPromptDialog';
import { STORYBOARD_VISUAL_THEME } from './storyboardTheme';
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

function DownloadAction({ href, children }: { href?: string; children: string }) {
  if (!href) {
    return (
      <button type="button" className="storyboard-action" disabled>
        <Download aria-hidden="true" /> {children}
      </button>
    );
  }
  return (
    <a className="storyboard-action" href={href} download>
      <Download aria-hidden="true" /> {children}
    </a>
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
  gridUrl,
  prompt,
  promptDetail,
  onRefresh,
  onRegenerate,
  onContinue,
}: StoryboardWorkspaceProps) {
  const scenes = useMemo(() => buildScenes(Array.isArray(shots) ? shots : []), [shots]);
  const [selectedSceneId, setSelectedSceneId] = useState<string>(() => scenes[0]?.id || '');
  const [selectedFrameIndex, setSelectedFrameIndex] = useState(0);
  const [showPrompt, setShowPrompt] = useState(false);
  const selectedScene = scenes.find(scene => scene.id === selectedSceneId) || scenes[0];
  const completedScenes = scenes.filter(scene => scene.shots.length > 0 && scene.shots.every(shot => Boolean(shot.image_url))).length;

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
          <p>第 1 集 · {title}</p>
          <span className="storyboard-progress">{completedScenes}/{scenes.length} 个分镜场景已完成</span>
        </div>
        <div className="storyboard-header-actions" aria-label="故事板操作">
          <DownloadAction href={gridUrl}>下载全部分镜图</DownloadAction>
          <button type="button" className="storyboard-action" onClick={onRefresh}>
            <RefreshCw aria-hidden="true" /> 刷新
          </button>
          <button type="button" className="storyboard-action" onClick={onRegenerate}>
            <Sparkles aria-hidden="true" /> 一键创作全部分镜页
          </button>
        </div>
      </header>

      <div className="storyboard-body">
        <aside className="storyboard-scene-nav" aria-label="时序分镜场景">
          <div className="storyboard-scene-nav__heading">
            <span>时序分镜</span>
            <strong>第 1 集</strong>
            <small>{title}</small>
          </div>
          <div className="storyboard-scene-list">
            {scenes.map(scene => {
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
        </aside>

        <main className="storyboard-main">
          <div className="storyboard-main-toolbar">
            <div>
              <h2>{selectedScene.id} 时序分镜</h2>
              <p><strong>3×3</strong><span aria-hidden="true">·</span>{selectedScene.shots.length} 个连续瞬间</p>
            </div>
            <div className="storyboard-main-actions">
              <DownloadAction href={gridUrl}>下载本图</DownloadAction>
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
            {selectedScene.shots.map((shot, index) => {
              const number = index + 1;
              return (
                <button
                  type="button"
                  className={`storyboard-frame ${selectedFrameIndex === index ? 'is-selected' : ''}`}
                  key={`${selectedScene.id}-${number}`}
                  aria-label={`选择分镜 ${number}`}
                  aria-pressed={selectedFrameIndex === index}
                  onClick={() => setSelectedFrameIndex(index)}
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
