import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type {
  Conversation,
  GenerationDraft,
  StudioAsset,
  StudioJob,
} from "@/features/studio/types";
import { apiRequest, apiUrl, demoMode, uploadImage } from "@/lib/api-client";

const keys = {
  conversations: ["conversations"] as const,
  jobs: ["jobs"] as const,
  assets: ["assets"] as const,
};

const terminalJobStages = new Set(["succeeded", "failed", "cancelled"]);
const jobStageOrder = {
  draft: 0,
  uploaded: 1,
  queued: 2,
  assigned: 3,
  loading_model: 4,
  preparing: 5,
  generating: 6,
  encoding: 7,
  cancel_requested: 8,
  succeeded: 9,
  failed: 9,
  cancelled: 9,
} satisfies Record<StudioJob["stage"], number>;

function mergeJobEvent(current: StudioJob, next: StudioJob): StudioJob {
  if (next.attempt < current.attempt) return current;
  if (next.attempt > current.attempt) return next;
  if (terminalJobStages.has(current.stage) && !terminalJobStages.has(next.stage)) return current;
  if (jobStageOrder[next.stage] < jobStageOrder[current.stage]) return current;
  if (Date.parse(next.updatedAt) < Date.parse(current.updatedAt)) return current;
  return { ...next, progress: Math.max(current.progress, next.progress) };
}

function mergeJobList(current: StudioJob[] | undefined, next: StudioJob[]): StudioJob[] {
  if (!current) return next;
  const currentById = new Map(current.map((job) => [job.id, job]));
  return next.map((job) => {
    const previous = currentById.get(job.id);
    return previous ? mergeJobEvent(previous, job) : job;
  });
}

export function useConversations() {
  return useQuery({
    queryKey: keys.conversations,
    queryFn: () => apiRequest<Conversation[]>("/v1/conversations"),
    staleTime: 5 * 60_000,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      apiRequest<Conversation>("/v1/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    onSuccess: (conversation) => {
      queryClient.setQueryData<Conversation[]>(keys.conversations, (items = []) => [
        conversation,
        ...items,
      ]);
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) =>
      apiRequest<void>(`/v1/conversations/${conversationId}`, { method: "DELETE" }),
    onSuccess: (_, conversationId) => {
      queryClient.setQueryData<Conversation[]>(keys.conversations, (items = []) =>
        items.filter((item) => item.id !== conversationId),
      );
      // The conversation's jobs and every generated asset are gone server-side.
      void queryClient.invalidateQueries({ queryKey: keys.jobs });
      void queryClient.invalidateQueries({ queryKey: keys.assets });
    },
  });
}

export function useRenameConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: string; title: string }) =>
      apiRequest<Conversation>(`/v1/conversations/${conversationId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    onSuccess: (conversation) => {
      queryClient.setQueryData<Conversation[]>(keys.conversations, (items = []) =>
        items.map((item) => (item.id === conversation.id ? conversation : item)),
      );
    },
  });
}

export function useJobs() {
  return useQuery<StudioJob[]>({
    queryKey: keys.jobs,
    queryFn: () => apiRequest<StudioJob[]>("/v1/jobs"),
    structuralSharing: (current, next) =>
      mergeJobList(
        Array.isArray(current) ? (current as StudioJob[]) : undefined,
        next as StudioJob[],
      ),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
      )
        ? 5_000
        : false,
    staleTime: 30_000,
  });
}

export function useJobEvents(jobs: StudioJob[]) {
  const queryClient = useQueryClient();
  const sources = useRef(new Map<string, EventSource>());
  const activeJobIds = jobs
    .filter((job) => !terminalJobStages.has(job.stage))
    .map((job) => job.id)
    .sort();
  const activeJobKey = activeJobIds.join("\u0000");

  useEffect(() => {
    if (demoMode) return;
    const active = new Set(activeJobKey ? activeJobKey.split("\u0000") : []);
    for (const [jobId, source] of sources.current) {
      if (!active.has(jobId)) {
        source.close();
        sources.current.delete(jobId);
      }
    }
    for (const jobId of active) {
      if (sources.current.has(jobId)) continue;
      const source = new EventSource(apiUrl(`/v1/jobs/${jobId}/events`));
      sources.current.set(jobId, source);
      const update = (event: Event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as StudioJob;
        let accepted = next;
        queryClient.setQueryData<StudioJob[]>(keys.jobs, (items = []) =>
          items.some((item) => item.id === next.id)
            ? items.map((item) => {
                if (item.id !== next.id) return item;
                accepted = mergeJobEvent(item, next);
                return accepted;
              })
            : [next, ...items],
        );
        if (terminalJobStages.has(accepted.stage)) {
          void queryClient.invalidateQueries({ queryKey: keys.assets });
          source.close();
          sources.current.delete(jobId);
        }
      };
      for (const eventName of [
        "job.updated",
        "job.assigned",
        "job.cancel_requested",
        "job.cancelled",
        "job.failed",
        "job.succeeded",
      ]) {
        source.addEventListener(eventName, update);
      }
      source.addEventListener("error", () => {
        void queryClient.invalidateQueries({ queryKey: keys.jobs });
      });
    }
  }, [activeJobKey, queryClient]);

  useEffect(() => {
    const subscriptions = sources.current;
    return () => {
      for (const source of subscriptions.values()) source.close();
      subscriptions.clear();
    };
  }, []);
}

export function useCreateJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      conversationId,
      computeSessionId,
      draft,
    }: {
      conversationId: string;
      computeSessionId: string;
      draft: GenerationDraft;
    }) =>
      apiRequest<StudioJob>("/v1/jobs/i2v", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversationId,
          computeSessionId,
          draft: {
            mode: draft.mode,
            prompt: draft.prompt,
            negativePrompt: draft.negativePrompt,
            queue: draft.queue,
            profile: draft.profile,
            ratio: draft.ratio,
            resolution: draft.resolution,
            duration: draft.duration,
            seed: draft.seed,
            firstStrength: draft.firstStrength,
            lastStrength: draft.lastStrength,
            enhancePrompt: draft.enhancePrompt,
            quantization: draft.quantization,
            offload: draft.offload,
            firstFrameAssetId: draft.firstFrame?.assetId ?? null,
            lastFrameAssetId: draft.lastFrame?.assetId ?? null,
          },
        }),
      }),
    onSuccess: (job) => {
      queryClient.setQueryData<StudioJob[]>(keys.jobs, (items = []) => [job, ...items]);
    },
  });
}

export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      apiRequest<StudioJob>(`/v1/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: (job) => updateJob(queryClient, job),
  });
}

export function useRetryJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      apiRequest<StudioJob>(`/v1/jobs/${jobId}/retry`, { method: "POST" }),
    onSuccess: (job) => updateJob(queryClient, job),
  });
}

export function useAssets() {
  return useQuery({
    queryKey: keys.assets,
    queryFn: () => apiRequest<StudioAsset[]>("/v1/assets"),
    // Assets only change through upload / delete / a finished job; avoid refetching
    // on every mount and focus. The mutations invalidate or patch the cache directly.
    staleTime: 5 * 60_000,
  });
}

export function useUploadImage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) =>
      uploadImage<StudioAsset>(file, title),
    onSuccess: (asset) => {
      queryClient.setQueryData<StudioAsset[]>(keys.assets, (items = []) => [
        asset,
        ...items,
      ]);
    },
  });
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (assetId: string) =>
      apiRequest<void>(`/v1/assets/${assetId}`, { method: "DELETE" }),
    onSuccess: (_, assetId) => {
      queryClient.setQueryData<StudioAsset[]>(keys.assets, (items = []) =>
        items.filter((asset) => asset.id !== assetId),
      );
    },
  });
}

function updateJob(
  queryClient: ReturnType<typeof useQueryClient>,
  job: StudioJob,
) {
  queryClient.setQueryData<StudioJob[]>(keys.jobs, (items = []) =>
    items.map((item) => (item.id === job.id ? mergeJobEvent(item, job) : item)),
  );
}
