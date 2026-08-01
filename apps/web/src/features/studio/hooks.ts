import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";

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

export function useConversations() {
  return useQuery({
    queryKey: keys.conversations,
    queryFn: () => apiRequest<Conversation[]>("/v1/conversations"),
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

export function useJobs() {
  return useQuery({
    queryKey: keys.jobs,
    queryFn: () => apiRequest<StudioJob[]>("/v1/jobs"),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
      )
        ? 5_000
        : false,
  });
}

export function useJobEvents(jobs: StudioJob[]) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (demoMode) return;
    const active = jobs.filter(
      (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
    );
    const sources = active.map((job) => {
      const source = new EventSource(apiUrl(`/v1/jobs/${job.id}/events`));
      const update = (event: Event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as StudioJob;
        queryClient.setQueryData<StudioJob[]>(keys.jobs, (items = []) =>
          items.some((item) => item.id === next.id)
            ? items.map((item) => (item.id === next.id ? next : item))
            : [next, ...items],
        );
        if (["succeeded", "failed", "cancelled"].includes(next.stage)) {
          void queryClient.invalidateQueries({ queryKey: keys.assets });
          source.close();
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
        source.close();
        void queryClient.invalidateQueries({ queryKey: keys.jobs });
      });
      return source;
    });
    return () => sources.forEach((source) => source.close());
  }, [jobs, queryClient]);
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
    items.map((item) => (item.id === job.id ? job : item)),
  );
}
