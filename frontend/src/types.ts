export interface TaskConfig {
  titleSuggestion: string;
  directorStyle: string;
  shotStyle: string;
  llmModel: string;
  imageModel: string;
  videoModel: string;
  ttsModel: string;
  oneClick: boolean;
  episodeCount: number;
}

export interface TaskResponse {
  taskId: string;
  currentStage: number;
  stageName: string;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed' | 'awaiting_quality_review' | 'quality_failed';
  config: {
    titleSuggestion: string;
    directorStyle: string;
    shotStyle: string;
    llmModel: string;
    imageModel: string;
    videoModel: string;
    ttsModel: string;
    oneClick: boolean;
    episodeCount?: number;
  };
  assets: {
    // Provider/stage payloads are intentionally heterogeneous and validated by
    // the backend contracts before rendering.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    [key: string]: any;
  };
  logs: {
    [key: string]: string;
  };
  videoUrl?: string;
  shortLink?: string;
  prContent?: string;
}
