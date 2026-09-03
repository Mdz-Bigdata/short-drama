import { ImageIcon, Video } from 'lucide-react';
import { useState } from 'react';

import './StageFivePreview.css';


export interface ProductionShot {
  shot_id?: number | string;
  size?: string;
  motion?: string;
  desc?: string;
  image_url?: string;
  end_frame_url?: string;
  video_url?: string;
  contract_fingerprint?: string;
  video_route_decision?: {
    mode?: string;
    provider_family?: string;
    reasons?: string[];
    fallbacks?: string[];
    unused_assets?: string[];
  };
}

interface Props {
  asset?: ProductionShot | ProductionShot[] | null;
  videoModel: string;
  imageModel: string;
}

interface MediaPaneProps {
  kind: 'video' | 'image';
  url: string;
  shotLabel: string;
  model: string;
}


function MediaPane({ kind, url, shotLabel, model }: MediaPaneProps) {
  const [failed, setFailed] = useState(false);
  const isVideo = kind === 'video';
  const mediaLabel = isVideo ? '图生视频动态画面' : '文生图底片首帧';

  return (
    <section className="stage-five-media-pane" aria-label={`${shotLabel} ${mediaLabel}`}>
      <div className="stage-five-media-label">
        {isVideo ? <Video aria-hidden="true" /> : <ImageIcon aria-hidden="true" />}
        <span>{mediaLabel}</span>
        <small>{model}</small>
      </div>
      <div className="stage-five-media-frame">
        {failed ? (
          <div className="stage-five-media-error" role="status">
            当前媒体无法载入，请重新生成或检查文件地址。
          </div>
        ) : isVideo ? (
          <video
            src={url}
            controls
            loop
            preload="metadata"
            aria-label={`${shotLabel} ${mediaLabel}`}
            onError={() => setFailed(true)}
          />
        ) : (
          <img
            src={url}
            alt={`${shotLabel} ${mediaLabel}`}
            onError={() => setFailed(true)}
          />
        )}
      </div>
    </section>
  );
}


function ShotCard({ shot, index, videoModel, imageModel }: {
  shot: ProductionShot;
  index: number;
  videoModel: string;
  imageModel: string;
}) {
  const shotId = shot.shot_id || index + 1;
  const shotLabel = `镜头 ${shotId}`;
  const hasVideo = Boolean(shot.video_url);
  const hasImage = Boolean(shot.image_url);
  const readyMediaCount = Number(hasVideo) + Number(hasImage);
  const pendingMessage = hasVideo && !hasImage
    ? '首帧图片仍在生成，已优先放大可用视频。'
    : hasImage && !hasVideo
      ? '动态视频仍在生成，已优先放大可用首帧。'
      : '';

  return (
    <article className="stage-five-shot-card" aria-label={`${shotLabel} 视觉资产`}>
      <header className="stage-five-shot-header">
        <strong>{shotLabel} <span>({shot.size || 'MS'} · {shot.motion || 'Dolly In'})</span></strong>
        <p>{shot.desc || '分镜画面'}</p>
      </header>

      {shot.video_route_decision && (
        <div className="stage-five-route" aria-label={`${shotLabel} 视频路由`}>
          <span>自动路由：{shot.video_route_decision.mode} · {shot.video_route_decision.provider_family}</span>
          {shot.contract_fingerprint && <code>契约 {shot.contract_fingerprint.slice(0, 12)}</code>}
          {shot.video_route_decision.reasons?.[0] && <small>{shot.video_route_decision.reasons[0]}</small>}
        </div>
      )}

      <div className={`stage-five-media-grid${readyMediaCount === 1 ? ' is-single' : ''}`}>
        {hasVideo && (
          <MediaPane
            key={`video-${shot.video_url}`}
            kind="video"
            url={shot.video_url!}
            shotLabel={shotLabel}
            model={videoModel}
          />
        )}
        {hasImage && (
          <MediaPane
            key={`image-${shot.image_url}`}
            kind="image"
            url={shot.image_url!}
            shotLabel={shotLabel}
            model={imageModel}
          />
        )}
        {readyMediaCount === 0 && (
          <div className="stage-five-media-empty" role="status">
            <Video aria-hidden="true" />
            <strong>镜头媒体生成中</strong>
            <span>视频与首帧完成后会自动显示在此处。</span>
          </div>
        )}
      </div>

      {pendingMessage && <p className="stage-five-pending-note" role="status">{pendingMessage}</p>}
    </article>
  );
}


export function StageFivePreview({ asset, videoModel, imageModel }: Props) {
  const shots = Array.isArray(asset) ? asset : asset ? [asset] : [];

  if (shots.length === 0) {
    return (
      <div className="stage-five-empty" role="status">
        暂无视觉片段资产。请先运行此阶段以生成底片与视频。
      </div>
    );
  }

  return (
    <div className="stage-five-preview-content">
      <div
        className="stage-five-shot-list"
        role="region"
        aria-label="Stage 5 镜头资产列表"
        tabIndex={0}
      >
        {shots.map((shot, index) => (
          <ShotCard
            key={`${shot.shot_id || 'shot'}-${index}`}
            shot={shot}
            index={index}
            videoModel={videoModel}
            imageModel={imageModel}
          />
        ))}
      </div>
    </div>
  );
}
