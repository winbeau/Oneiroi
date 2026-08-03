import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type {
  AgentCapabilities,
  AgentEvent,
  AgentMessage,
  AgentRun,
  AgentThread,
  AgentToolDecision,
} from "@/features/agent/types";
import type { GenerationDraft } from "@/features/studio/types";
import {
  ApiError,
  apiRequest,
  apiUrl,
  demoMode,
} from "@/lib/api-client";
import { subscribeDemoAgentEvents } from "@/lib/demo-api";
import { createUuid } from "@/lib/uuid";

export const agentKeys = {
  capabilities: ["agent", "capabilities"] as const,
  thread: (conversationId: string) => ["agent", "thread", conversationId] as const,
  messages: (threadId: string) => ["agent", "messages", threadId] as const,
  run: (runId: string) => ["agent", "run", runId] as const,
};

const terminalEvents = new Set([
  "agent.run.completed",
  "agent.run.failed",
  "agent.run.cancelled",
]);

function draftSnapshot(draft: GenerationDraft) {
  return {
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
  };
}

export interface PromptEnhanceResult {
  prompt: string;
  negativePrompt: string | null;
}

export function usePromptEnhance() {
  return useMutation({
    mutationFn: ({
      prompt,
      negativePrompt,
    }: {
      prompt: string;
      negativePrompt?: string | null;
    }) =>
      apiRequest<PromptEnhanceResult>("/v1/agent/prompt-enhance", {
        method: "POST",
        body: JSON.stringify({ prompt, negativePrompt: negativePrompt ?? null }),
      }),
  });
}

export interface TitleSummarizeResult {
  title: string;
}

export function useTitleSummarize() {
  return useMutation({
    mutationFn: (prompt: string) =>
      apiRequest<TitleSummarizeResult>("/v1/agent/title-summarize", {
        method: "POST",
        body: JSON.stringify({ prompt }),
      }),
    retry: false,
  });
}

export function useAgentCapabilities() {
  return useQuery({
    queryKey: agentKeys.capabilities,
    queryFn: async () => {
      try {
        return await apiRequest<AgentCapabilities>("/v1/agent/capabilities");
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export function useAgentThread(conversationId: string, enabled: boolean) {
  return useQuery({
    queryKey: agentKeys.thread(conversationId),
    queryFn: async () => {
      try {
        return await apiRequest<AgentThread>(
          `/v1/conversations/${conversationId}/agent/thread`,
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: enabled && Boolean(conversationId),
    retry: false,
  });
}

export function useAgentMessages(threadId: string, enabled: boolean) {
  return useQuery({
    queryKey: agentKeys.messages(threadId),
    queryFn: () =>
      apiRequest<AgentMessage[]>(`/v1/agent/threads/${threadId}/messages?limit=100`),
    enabled: enabled && Boolean(threadId),
    retry: false,
  });
}

export function useCreateAgentRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      conversationId,
      message,
      draft,
      assetIds,
      mode,
    }: {
      conversationId: string;
      message: string;
      draft: GenerationDraft;
      assetIds: string[];
      mode: "assist" | "image-analysis" | "storyboard";
    }) =>
      apiRequest<AgentRun>("/v1/agent/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": createUuid(),
        },
        body: JSON.stringify({
          conversationId,
          message,
          draftSnapshot: draftSnapshot(draft),
          assetIds,
          mode,
        }),
      }),
    onSuccess: (run) => {
      queryClient.setQueryData(agentKeys.run(run.id), run);
      void queryClient.invalidateQueries({
        queryKey: agentKeys.thread(run.conversationId),
      });
      void queryClient.invalidateQueries({ queryKey: agentKeys.messages(run.threadId) });
    },
  });
}

export function useAgentToolDecision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      toolCallId,
      decision,
    }: {
      toolCallId: string;
      decision: "approve" | "reject";
    }) =>
      apiRequest<AgentToolDecision>(
        `/v1/agent/tool-calls/${toolCallId}/${decision}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clientVersion: "oneiroi-web/0.1" }),
        },
      ),
    onSuccess: (decision) => {
      queryClient.setQueryData(agentKeys.run(decision.run.id), decision.run);
    },
  });
}

export function useCancelAgentRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiRequest<AgentRun>(`/v1/agent/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: (run) => queryClient.setQueryData(agentKeys.run(run.id), run),
  });
}

type StreamState = {
  connected: boolean;
  reconnecting: boolean;
  error: string;
};

export function useAgentRunStream(
  runId: string,
  onEvent: (event: AgentEvent) => void,
): StreamState {
  const callback = useRef(onEvent);
  const [state, setState] = useState<StreamState>({
    connected: false,
    reconnecting: false,
    error: "",
  });

  useEffect(() => {
    callback.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!runId) {
      return;
    }

    let stopped = false;
    let lastEventId = sessionStorage.getItem(`oneiroi-agent-event:${runId}`) ?? "";
    const controller = new AbortController();

    const accept = (event: AgentEvent) => {
      if (stopped) return;
      if (event.id) {
        const current = Number(lastEventId || 0);
        const next = Number(event.id);
        if (Number.isFinite(next) && next <= current) return;
        lastEventId = event.id;
        sessionStorage.setItem(`oneiroi-agent-event:${runId}`, event.id);
      }
      callback.current(event);
    };

    if (demoMode) {
      queueMicrotask(() => {
        if (!stopped) setState({ connected: true, reconnecting: false, error: "" });
      });
      const unsubscribe = subscribeDemoAgentEvents(runId, lastEventId, accept);
      return () => {
        stopped = true;
        unsubscribe();
      };
    }

    const connect = async () => {
      let attempts = 0;
      while (!stopped) {
        try {
          const response = await fetch(apiUrl(`/v1/agent/runs/${runId}/events`), {
            credentials: "same-origin",
            headers: {
              Accept: "text/event-stream",
              ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
            },
            signal: controller.signal,
          });
          if (!response.ok || !response.body) {
            throw new Error(`Agent stream failed: ${response.status}`);
          }
          attempts = 0;
          setState({ connected: true, reconnecting: false, error: "" });
          const terminal = await readEventStream(response.body, accept);
          if (terminal || stopped) return;
          throw new Error("Agent stream closed before completion");
        } catch (error) {
          if (stopped || controller.signal.aborted) return;
          attempts += 1;
          const message = error instanceof Error ? error.message : "Agent stream unavailable";
          setState({ connected: false, reconnecting: true, error: message });
          await new Promise((resolve) =>
            window.setTimeout(resolve, Math.min(1_000 * 2 ** (attempts - 1), 8_000)),
          );
        }
      }
    };

    void connect();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [runId]);

  return runId
    ? state
    : { connected: false, reconnecting: false, error: "" };
}

async function readEventStream(
  stream: ReadableStream<Uint8Array>,
  accept: (event: AgentEvent) => void,
): Promise<boolean> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "message";
  let eventId = "";
  let data: string[] = [];
  let terminal = false;

  const dispatch = () => {
    if (data.length === 0) {
      eventType = "message";
      eventId = "";
      return;
    }
    try {
      const payload = JSON.parse(data.join("\n")) as {
        runId?: unknown;
        threadId?: unknown;
        sequence?: unknown;
        data?: unknown;
      };
      if (
        typeof payload.runId === "string" &&
        typeof payload.threadId === "string" &&
        typeof payload.sequence === "number" &&
        payload.data !== null &&
        typeof payload.data === "object"
      ) {
        const event: AgentEvent = {
          id: eventId,
          type: eventType,
          runId: payload.runId,
          threadId: payload.threadId,
          sequence: payload.sequence,
          data: payload.data as Record<string, unknown>,
        };
        accept(event);
        terminal ||= terminalEvents.has(eventType);
      }
    } catch {
      // Ignore malformed/untrusted stream frames and resume at the next SSE boundary.
    }
    eventType = "message";
    eventId = "";
    data = [];
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = done ? "" : (lines.pop() ?? "");
      for (const line of lines) {
        if (line === "") {
          dispatch();
          continue;
        }
        if (line.startsWith(":")) continue;
        const separator = line.indexOf(":");
        const field = separator === -1 ? line : line.slice(0, separator);
        const valueText = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
        if (field === "event") eventType = valueText;
        if (field === "id") eventId = valueText;
        if (field === "data") data.push(valueText);
      }
      if (done) {
        dispatch();
        return terminal;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
