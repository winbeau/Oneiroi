export type QualityTier = "快速" | "高质量";
export type AspectRatio = "16:9" | "9:16" | "1:1";
export type ResolutionPreset = "720p" | "1080p";
export type DurationPreset = 5 | 8 | 10;
export type QueueTier = "fast" | "hq";
export type QuantizationMode = "fp8-cast" | "none";
export type OffloadMode = "none" | "cpu";

export type JobStage =
  | "draft"
  | "uploaded"
  | "queued"
  | "assigned"
  | "preparing"
  | "generating"
  | "encoding"
  | "succeeded"
  | "failed"
  | "cancelled";

export type MediaReference = {
  name: string;
  url: string;
};

export type GenerationSettings = {
  mode: "I2V";
  quality: QualityTier;
  ratio: AspectRatio;
  resolution: ResolutionPreset;
  duration: DurationPreset;
  seed: number;
  firstStrength: number;
  lastStrength: number;
  enhancePrompt: boolean;
  negativePrompt: string;
  queue: QueueTier;
  quantization: QuantizationMode;
  offload: OffloadMode;
};

export type GenerationDraft = GenerationSettings & {
  prompt: string;
  firstFrame: MediaReference | null;
  lastFrame: MediaReference | null;
};

export type StudioJob = {
  id: string;
  conversationId: string;
  createdAt: string;
  updatedAt: string;
  stage: JobStage;
  progress: number;
  draft: GenerationDraft;
  previewUrl: string | null;
  errorMessage?: string;
};

export type AssetType = "image" | "video" | "template";

export type StudioAsset = {
  id: string;
  type: AssetType;
  title: string;
  createdAt: string;
  previewUrl: string;
  sourceJobId?: string;
  draft?: GenerationDraft;
};

export type Conversation = {
  id: string;
  title: string;
  updatedAt: string;
};

export type InspirationTemplate = {
  id: string;
  title: string;
  description: string;
  category: "团队灵感" | "项目模板" | "历史案例";
  prompt: string;
  previewUrl: string;
  secondaryPreviewUrl?: string;
  settings: Pick<
    GenerationSettings,
    "quality" | "ratio" | "resolution" | "duration"
  >;
};
