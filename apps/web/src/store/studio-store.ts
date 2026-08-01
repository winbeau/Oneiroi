import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  BOOK_PROMPT,
  headFrameUrl,
  tailFrameUrl,
} from "@/features/studio/templates";
import type {
  GenerationDraft,
  InspirationTemplate,
} from "@/features/studio/types";

export const defaultDraft: GenerationDraft = {
  mode: "I2V",
  prompt: BOOK_PROMPT,
  quality: "快速",
  ratio: "16:9",
  resolution: "720p",
  duration: 5,
  seed: 42,
  firstStrength: 1,
  lastStrength: 1,
  enhancePrompt: false,
  negativePrompt:
    "flicker, camera shake, identity drift, deformed hands, warped furniture, changing room geometry, text artifacts",
  queue: "fast",
  profile: "fast",
  quantization: "fp8-cast",
  offload: "none",
  firstFrame: { name: "head.png", url: headFrameUrl },
  lastFrame: { name: "tail.png", url: tailFrameUrl },
};

type StudioState = {
  activeConversationId: string;
  draft: GenerationDraft;
  assetView: "grid" | "list";
  setActiveConversation: (id: string) => void;
  updateDraft: (patch: Partial<GenerationDraft>) => void;
  resetDraft: () => void;
  applyTemplate: (template: InspirationTemplate) => void;
  setAssetView: (view: "grid" | "list") => void;
};

export const useStudioStore = create<StudioState>()(
  persist(
    (set) => ({
      activeConversationId: "",
      draft: defaultDraft,
      assetView: "grid",
      setActiveConversation: (activeConversationId) => set({ activeConversationId }),
      updateDraft: (patch) =>
        set((state) => ({
          draft: {
            ...state.draft,
            ...patch,
            ...(patch.quality
              ? {
                  queue: patch.quality === "高质量" ? "hq" : "fast",
                  profile: patch.quality === "高质量" ? "hq" : "fast",
                  resolution:
                    patch.quality === "高质量" ? "1080p" : state.draft.resolution,
                }
              : {}),
          },
        })),
      resetDraft: () =>
        set({
          draft: {
            ...defaultDraft,
            prompt: "",
            firstFrame: null,
            lastFrame: null,
          },
        }),
      applyTemplate: (template) =>
        set((state) => ({
          draft: {
            ...state.draft,
            ...template.settings,
            prompt: template.prompt,
            queue: template.settings.quality === "高质量" ? "hq" : "fast",
            profile: template.settings.quality === "高质量" ? "hq" : "fast",
            firstFrame: {
              name: `${template.id}-first.png`,
              url: template.previewUrl,
            },
            lastFrame: template.secondaryPreviewUrl
              ? {
                  name: `${template.id}-last.png`,
                  url: template.secondaryPreviewUrl,
                }
              : null,
          },
        })),
      setAssetView: (assetView) => set({ assetView }),
    }),
    {
      name: "oneiroi-studio-ui-v2",
      partialize: (state) => ({
        activeConversationId: state.activeConversationId,
        draft: state.draft,
        assetView: state.assetView,
      }),
    },
  ),
);
