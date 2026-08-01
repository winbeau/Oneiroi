import type { components } from "@/generated/gateway";

export type AssetType = "image" | "video" | "template";
export type GenerationQuality = "快速" | "高质量";
export type GenerationRatio = components["schemas"]["GenerationDraft"]["ratio"];
export type GenerationResolution = components["schemas"]["GenerationDraft"]["resolution"];
export type GenerationDuration = components["schemas"]["GenerationDraft"]["duration"];
export type QueueTier = components["schemas"]["QueueTier"];
export type ProfileTier = components["schemas"]["ProfileTier"];
export type OffloadMode = components["schemas"]["GenerationDraft"]["offload"];
export type QuantizationMode = components["schemas"]["GenerationDraft"]["quantization"];
export type JobStage = components["schemas"]["JobStatus"];
export type ComputeSessionState = components["schemas"]["ComputeSessionState"];
export type GpuState = components["schemas"]["GpuState"];

export interface MediaReference {
  name: string;
  url: string;
  assetId?: string;
}

export interface InspirationTemplate {
  id: string;
  title: string;
  description: string;
  category: string;
  prompt: string;
  previewUrl: string;
  secondaryPreviewUrl?: string;
  settings: Pick<
    GenerationDraft,
    "quality" | "ratio" | "resolution" | "duration"
  > &
    Partial<GenerationDraft>;
}

export type GenerationDraft = components["schemas"]["GenerationDraft"] & {
  quality: GenerationQuality;
  firstFrame: MediaReference | null;
  lastFrame: MediaReference | null;
};

export type Conversation = components["schemas"]["ConversationResponse"];
export type GpuInfo = components["schemas"]["GpuInfo"];
export type GpuInventory = components["schemas"]["GpuInventoryResponse"];
export type ComputeSlot = components["schemas"]["ComputeSlot"];
export type ComputeSession = components["schemas"]["ComputeSessionSnapshot"];
export type ProfileCapability = components["schemas"]["ProfileCapability"];
export type ComputeCapabilities = components["schemas"]["ComputeCapabilitiesResponse"];
export type StudioJob = components["schemas"]["JobResponse"];

export type StudioAsset = Omit<
  components["schemas"]["AssetResponse"],
  "previewUrl"
> & {
  previewUrl: string;
  draft?: GenerationDraft;
};
