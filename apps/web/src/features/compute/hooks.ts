import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type {
  ComputeCapabilities,
  ComputeSession,
  GpuInventory,
} from "@/features/studio/types";
import { apiRequest, apiUrl, demoMode } from "@/lib/api-client";
import { createUuid } from "@/lib/uuid";
import { useComputeUiStore } from "@/store/compute-ui-store";

const computeKeys = {
  gpus: ["compute", "gpus"] as const,
  capabilities: (sessionId: string) => ["compute", "capabilities", sessionId] as const,
  session: (sessionId: string) => ["compute", "session", sessionId] as const,
};

export function useComputeGpus(refetchInterval: number | false = false) {
  return useQuery({
    queryKey: computeKeys.gpus,
    queryFn: () => apiRequest<GpuInventory>("/v1/compute/gpus"),
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}

export function useComputeCapabilities(sessionId = "") {
  return useQuery({
    queryKey: computeKeys.capabilities(sessionId),
    queryFn: () =>
      apiRequest<ComputeCapabilities>(
        `/v1/compute/capabilities${sessionId ? `?sessionId=${encodeURIComponent(sessionId)}` : ""}`,
      ),
  });
}

export function useComputeSession() {
  const sessionId = useComputeUiStore((state) => state.activeSessionId);
  return useQuery({
    queryKey: computeKeys.session(sessionId),
    queryFn: () => apiRequest<ComputeSession>(`/v1/compute/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    refetchInterval: (query) =>
      ["allocating", "loading", "draining", "releasing"].includes(
        query.state.data?.state ?? "",
      )
        ? 2_000
        : false,
  });
}

export function useComputeSessionEvents(session?: ComputeSession) {
  const queryClient = useQueryClient();
  const clearActiveSession = useComputeUiStore((state) => state.clearActiveSession);
  const sessionId = session?.id ?? "";
  const terminal = !session || ["released", "failed"].includes(session.state);

  useEffect(() => {
    if (demoMode || !sessionId || terminal) return;
    const source = new EventSource(apiUrl(`/v1/compute/sessions/${sessionId}/events`));
    const update = (event: Event) => {
      const next = JSON.parse((event as MessageEvent<string>).data) as ComputeSession;
      queryClient.setQueryData(computeKeys.session(sessionId), next);
      void queryClient.invalidateQueries({
        queryKey: computeKeys.capabilities(sessionId),
      });
      if (["released", "failed"].includes(next.state)) {
        source.close();
        if (next.state === "released") clearActiveSession();
      }
    };
    for (const eventName of [
      "compute.session.updated",
      "compute.session.ready",
      "compute.session.degraded",
      "compute.session.failed",
      "compute.session.released",
    ]) {
      source.addEventListener(eventName, update);
    }
    source.addEventListener("compute.slot.updated", () => {
      void queryClient.invalidateQueries({ queryKey: computeKeys.session(sessionId) });
    });
    source.addEventListener("error", () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: computeKeys.session(sessionId) });
    });
    return () => source.close();
  }, [clearActiveSession, queryClient, sessionId, terminal]);
}

export function useCreateComputeSession() {
  const queryClient = useQueryClient();
  const setActiveSessionId = useComputeUiStore((state) => state.setActiveSessionId);
  return useMutation({
    mutationFn: (payload: {
      requestedGpuCount: number;
      selectionMode: "auto" | "manual";
      gpuIds: string[];
      allowPartial: boolean;
    }) =>
      apiRequest<ComputeSession>("/v1/compute/sessions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": createUuid(),
        },
        body: JSON.stringify({ ...payload, profilePolicy: "balanced" }),
      }),
    onSuccess: (session) => {
      setActiveSessionId(session.id);
      queryClient.setQueryData(computeKeys.session(session.id), session);
    },
  });
}

export function useReleaseComputeSession() {
  const queryClient = useQueryClient();
  const clearActiveSession = useComputeUiStore((state) => state.clearActiveSession);
  return useMutation({
    mutationFn: ({
      sessionId,
      policy,
      confirmed,
    }: {
      sessionId: string;
      policy: "when_idle" | "cancel_running";
      confirmed: boolean;
    }) =>
      apiRequest<ComputeSession>(`/v1/compute/sessions/${sessionId}/release`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy, confirmed }),
      }),
    onSuccess: (session) => {
      queryClient.setQueryData(computeKeys.session(session.id), session);
      if (session.state === "released") clearActiveSession();
    },
  });
}
