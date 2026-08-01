import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type {
  ComputeCapabilities,
  ComputeSession,
  GpuInventory,
} from "@/features/studio/types";
import { apiRequest, apiUrl, demoMode } from "@/lib/api-client";
import { useComputeUiStore } from "@/store/compute-ui-store";

const computeKeys = {
  gpus: ["compute", "gpus"] as const,
  capabilities: (sessionId: string) => ["compute", "capabilities", sessionId] as const,
  session: (sessionId: string) => ["compute", "session", sessionId] as const,
};

export function useComputeGpus() {
  return useQuery({
    queryKey: computeKeys.gpus,
    queryFn: () => apiRequest<GpuInventory>("/v1/compute/gpus"),
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

  useEffect(() => {
    if (demoMode || !session || ["released", "failed"].includes(session.state)) return;
    const source = new EventSource(apiUrl(`/v1/compute/sessions/${session.id}/events`));
    const update = (event: Event) => {
      const next = JSON.parse((event as MessageEvent<string>).data) as ComputeSession;
      queryClient.setQueryData(computeKeys.session(session.id), next);
      void queryClient.invalidateQueries({
        queryKey: computeKeys.capabilities(session.id),
      });
      if (next.state === "released") {
        source.close();
        clearActiveSession();
      }
    };
    for (const eventName of [
      "compute.session.updated",
      "compute.session.ready",
      "compute.session.degraded",
      "compute.session.released",
    ]) {
      source.addEventListener(eventName, update);
    }
    source.addEventListener("compute.slot.updated", () => {
      void queryClient.invalidateQueries({ queryKey: computeKeys.session(session.id) });
    });
    source.addEventListener("error", () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: computeKeys.session(session.id) });
    });
    return () => source.close();
  }, [clearActiveSession, queryClient, session]);
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
          "Idempotency-Key": crypto.randomUUID(),
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
