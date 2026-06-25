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
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
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
    [key: string]: any;
  };
  logs: {
    [key: string]: string;
  };
  videoUrl?: string;
  shortLink?: string;
  prContent?: string;
}
