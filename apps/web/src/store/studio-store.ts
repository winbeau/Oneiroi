import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  BOOK_PROMPT,
  headFrameUrl,
  inspirationTemplates,
  tailFrameUrl,
} from "@/features/studio/templates";
import type {
  Conversation,
  GenerationDraft,
  InspirationTemplate,
  JobStage,
  StudioAsset,
  StudioJob,
} from "@/features/studio/types";
import { apiRequest, apiUrl } from "@/lib/api-client";

const now = () => new Date().toISOString();
const createId = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

const defaultDraft: GenerationDraft = {
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
  quantization: "fp8-cast",
  offload: "none",
  firstFrame: { name: "head.png", url: headFrameUrl },
  lastFrame: { name: "tail.png", url: tailFrameUrl },
};

const initialConversations: Conversation[] = [
  { id: "draft", title: "取书镜头", updatedAt: now() },
  {
    id: "product",
    title: "产品片段",
    updatedAt: new Date(Date.now() - 86_400_000).toISOString(),
  },
  {
    id: "character",
    title: "角色镜头",
    updatedAt: new Date(Date.now() - 259_200_000).toISOString(),
  },
];

const initialAssets: StudioAsset[] = [
  {
    id: "asset-head",
    type: "image",
    title: "取书镜头 · 首帧",
    createdAt: now(),
    previewUrl: headFrameUrl,
    draft: defaultDraft,
  },
  {
    id: "asset-tail",
    type: "image",
    title: "取书镜头 · 尾帧",
    createdAt: now(),
    previewUrl: tailFrameUrl,
    draft: defaultDraft,
  },
  ...inspirationTemplates.map<StudioAsset>((template) => ({
    id: `template-${template.id}`,
    type: "template",
    title: template.title,
    createdAt: now(),
    previewUrl: template.previewUrl,
    draft: {
      ...defaultDraft,
      ...template.settings,
      prompt: template.prompt,
      queue: template.settings.quality === "高质量" ? "hq" : "fast",
    },
  })),
];

type StudioState = {
  activeConversationId: string;
  conversations: Conversation[];
  draft: GenerationDraft;
  jobs: StudioJob[];
  assets: StudioAsset[];
  assetView: "grid" | "list";
  setActiveConversation: (id: string) => void;
  createConversation: () => void;
  updateDraft: (patch: Partial<GenerationDraft>) => void;
  applyTemplate: (template: InspirationTemplate) => void;
  submitDraft: () => string;
  cancelJob: (id: string) => void;
  retryJob: (id: string) => void;
  reuseJob: (id: string) => void;
  addAsset: (asset: StudioAsset) => void;
  deleteAsset: (id: string) => void;
  setAssetView: (view: "grid" | "list") => void;
  resumePendingJobs: () => void;
};

const timers = new Map<string, Array<ReturnType<typeof setTimeout>>>();
const eventSources = new Map<string, EventSource>();

const clearJobTimers = (jobId: string) => {
  for (const timer of timers.get(jobId) ?? []) clearTimeout(timer);
  timers.delete(jobId);
  eventSources.get(jobId)?.close();
  eventSources.delete(jobId);
};

const stageSequence: Array<{ stage: JobStage; progress: number; delay: number }> = [
  { stage: "uploaded", progress: 5, delay: 250 },
  { stage: "queued", progress: 12, delay: 800 },
  { stage: "assigned", progress: 20, delay: 1_450 },
  { stage: "preparing", progress: 34, delay: 2_250 },
  { stage: "generating", progress: 68, delay: 3_350 },
  { stage: "encoding", progress: 91, delay: 4_750 },
  { stage: "succeeded", progress: 100, delay: 5_650 },
];

export const useStudioStore = create<StudioState>()(
  persist(
    (set, get) => {
      const applyRemoteJob = (job: StudioJob) => {
        set((state) => {
          const exists = state.jobs.some((candidate) => candidate.id === job.id);
          const jobs = exists
            ? state.jobs.map((candidate) => (candidate.id === job.id ? job : candidate))
            : [job, ...state.jobs];
          const alreadyAdded = state.assets.some((asset) => asset.sourceJobId === job.id);
          const assets =
            job.stage === "succeeded" && !alreadyAdded
              ? [
                  {
                    id: createId("asset"),
                    type: "video" as const,
                    title: `${state.conversations.find((item) => item.id === job.conversationId)?.title ?? "未命名创作"} · 生成视频`,
                    createdAt: now(),
                    previewUrl:
                      job.previewUrl ??
                      job.draft.lastFrame?.url ??
                      job.draft.firstFrame?.url ??
                      tailFrameUrl,
                    sourceJobId: job.id,
                    draft: job.draft,
                  },
                  ...state.assets,
                ]
              : state.assets;
          return { jobs, assets };
        });
      };

      const startRemoteStream = (jobId: string) => {
        const source = new EventSource(apiUrl(`/v1/jobs/${jobId}/events`));
        eventSources.set(jobId, source);
        source.addEventListener("job", (event) => {
          const remoteJob = JSON.parse((event as MessageEvent<string>).data) as StudioJob;
          applyRemoteJob(remoteJob);
          if (["succeeded", "failed", "cancelled"].includes(remoteJob.stage)) {
            clearJobTimers(jobId);
          }
        });
        source.addEventListener("error", () => {
          source.close();
          eventSources.delete(jobId);
          const current = get().jobs.find((candidate) => candidate.id === jobId);
          if (current && !["succeeded", "failed", "cancelled"].includes(current.stage)) {
            scheduleJob(jobId, current.stage);
          }
        });
      };

      const scheduleJob = (jobId: string, fromStage?: JobStage) => {
        clearJobTimers(jobId);
        const job = get().jobs.find((candidate) => candidate.id === jobId);
        if (!job || ["succeeded", "failed", "cancelled"].includes(job.stage)) return;

        const currentIndex = fromStage
          ? stageSequence.findIndex((item) => item.stage === fromStage)
          : -1;
        const remaining = stageSequence.slice(Math.max(0, currentIndex + 1));
        const scheduled: Array<ReturnType<typeof setTimeout>> = [];

        remaining.forEach((step, index) => {
          scheduled.push(
            setTimeout(() => {
              const current = get().jobs.find((candidate) => candidate.id === jobId);
              if (!current || ["succeeded", "failed", "cancelled"].includes(current.stage)) {
                clearJobTimers(jobId);
                return;
              }

              const shouldFail =
                step.stage === "encoding" &&
                current.draft.prompt.toLowerCase().includes("[fail]");

              if (shouldFail) {
                set((state) => ({
                  jobs: state.jobs.map((candidate) =>
                    candidate.id === jobId
                      ? {
                          ...candidate,
                          stage: "failed",
                          progress: 88,
                          updatedAt: now(),
                          errorMessage:
                            "模拟编码失败。移除 Prompt 中的 [fail] 后可重试。",
                        }
                      : candidate,
                  ),
                }));
                clearJobTimers(jobId);
                return;
              }

              set((state) => {
                const updatedJobs = state.jobs.map((candidate) =>
                  candidate.id === jobId
                    ? {
                        ...candidate,
                        stage: step.stage,
                        progress: step.progress,
                        updatedAt: now(),
                        previewUrl:
                          step.stage === "succeeded"
                            ? candidate.draft.lastFrame?.url ??
                              candidate.draft.firstFrame?.url ??
                              tailFrameUrl
                            : candidate.previewUrl,
                      }
                    : candidate,
                );
                const completedJob = updatedJobs.find(
                  (candidate) => candidate.id === jobId,
                );
                const alreadyAdded = state.assets.some(
                  (asset) => asset.sourceJobId === jobId,
                );
                const assets =
                  step.stage === "succeeded" && completedJob && !alreadyAdded
                    ? [
                        {
                          id: createId("asset"),
                          type: "video" as const,
                          title: `${state.conversations.find((item) => item.id === completedJob.conversationId)?.title ?? "未命名创作"} · 生成视频`,
                          createdAt: now(),
                          previewUrl: completedJob.previewUrl ?? tailFrameUrl,
                          sourceJobId: jobId,
                          draft: completedJob.draft,
                        },
                        ...state.assets,
                      ]
                    : state.assets;
                return { jobs: updatedJobs, assets };
              });

              if (step.stage === "succeeded") clearJobTimers(jobId);
            },
            Math.max(250, step.delay - index * 80),
          ),
        );
        });
        timers.set(jobId, scheduled);
      };

      return {
        activeConversationId: "draft",
        conversations: initialConversations,
        draft: defaultDraft,
        jobs: [],
        assets: initialAssets,
        assetView: "grid",
        setActiveConversation: (activeConversationId) => set({ activeConversationId }),
        createConversation: () => {
          const conversation: Conversation = {
            id: createId("conversation"),
            title: "未命名创作",
            updatedAt: now(),
          };
          set((state) => ({
            activeConversationId: conversation.id,
            conversations: [conversation, ...state.conversations],
            draft: { ...defaultDraft, prompt: "", firstFrame: null, lastFrame: null },
          }));
        },
        updateDraft: (patch) =>
          set((state) => ({
            draft: {
              ...state.draft,
              ...patch,
              ...(patch.quality
                ? {
                    queue: patch.quality === "高质量" ? "hq" : "fast",
                    resolution:
                      patch.quality === "高质量" ? "1080p" : state.draft.resolution,
                  }
                : {}),
            },
          })),
        applyTemplate: (template) =>
          set((state) => ({
            draft: {
              ...state.draft,
              ...template.settings,
              prompt: template.prompt,
              queue: template.settings.quality === "高质量" ? "hq" : "fast",
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
        submitDraft: () => {
          const state = get();
          const id = createId("job");
          const createdAt = now();
          const job: StudioJob = {
            id,
            conversationId: state.activeConversationId,
            createdAt,
            updatedAt: createdAt,
            stage: "uploaded",
            progress: 5,
            draft: structuredClone(state.draft),
            previewUrl: null,
          };
          set((current) => ({
            jobs: [job, ...current.jobs],
            conversations: current.conversations.map((conversation) =>
              conversation.id === current.activeConversationId
                ? {
                    ...conversation,
                    title:
                      conversation.title === "未命名创作" && current.draft.prompt
                        ? current.draft.prompt.slice(0, 18)
                        : conversation.title,
                    updatedAt: createdAt,
                  }
                : conversation,
            ),
          }));
          void apiRequest<StudioJob>("/v1/jobs/i2v", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              conversationId: state.activeConversationId,
              draft: state.draft,
            }),
          })
            .then((remoteJob) => {
              clearJobTimers(id);
              set((current) => ({
                jobs: current.jobs.map((candidate) =>
                  candidate.id === id ? remoteJob : candidate,
                ),
              }));
              startRemoteStream(remoteJob.id);
            })
            .catch(() => scheduleJob(id, "uploaded"));
          return id;
        },
        cancelJob: (id) => {
          clearJobTimers(id);
          void apiRequest<StudioJob>(`/v1/jobs/${id}/cancel`, { method: "POST" }).catch(
            () => undefined,
          );
          set((state) => ({
            jobs: state.jobs.map((job) =>
              job.id === id && !["succeeded", "failed"].includes(job.stage)
                ? { ...job, stage: "cancelled", updatedAt: now() }
                : job,
            ),
          }));
        },
        retryJob: (id) => {
          const job = get().jobs.find((candidate) => candidate.id === id);
          if (!job) return;
          set({ draft: structuredClone(job.draft), activeConversationId: job.conversationId });
          get().submitDraft();
        },
        reuseJob: (id) => {
          const job = get().jobs.find((candidate) => candidate.id === id);
          if (job) set({ draft: structuredClone(job.draft), activeConversationId: job.conversationId });
        },
        addAsset: (asset) => set((state) => ({ assets: [asset, ...state.assets] })),
        deleteAsset: (id) =>
          set((state) => ({ assets: state.assets.filter((asset) => asset.id !== id) })),
        setAssetView: (assetView) => set({ assetView }),
        resumePendingJobs: () => {
          for (const job of get().jobs) {
            if (!["succeeded", "failed", "cancelled"].includes(job.stage)) {
              scheduleJob(job.id, job.stage);
            }
          }
        },
      };
    },
    {
      name: "oneiroi-studio-demo-v1",
      partialize: (state) => ({
        activeConversationId: state.activeConversationId,
        conversations: state.conversations,
        draft: state.draft,
        jobs: state.jobs,
        assets: state.assets,
        assetView: state.assetView,
      }),
    },
  ),
);
