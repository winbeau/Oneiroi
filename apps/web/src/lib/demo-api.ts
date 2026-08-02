import type {
  AgentApproval,
  AgentEvent,
  AgentMessage,
  AgentRun,
  AgentThread,
  AgentToolCall,
  AgentToolDecision,
} from "@/features/agent/types";
import type {
  ComputeCapabilities,
  ComputeSession,
  Conversation,
  StudioAsset,
  StudioJob,
} from "@/features/studio/types";

const now = () => new Date().toISOString();
const id = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 12)}`;

const conversations: Conversation[] = [];
const jobs: Array<StudioJob & { demoStartedAt?: number }> = [];
const assets: StudioAsset[] = [];
let session: ComputeSession | null = null;
const agentThreads = new Map<string, AgentThread>();
const agentMessages = new Map<string, AgentMessage[]>();
const agentRuns = new Map<string, AgentRun>();
const agentEvents = new Map<string, AgentEvent[]>();
const agentSubscribers = new Map<string, Set<(event: AgentEvent) => void>>();
const agentToolCalls = new Map<string, AgentToolCall>();
const agentApprovals = new Map<string, AgentApproval>();
let agentEventId = 0;

export async function demoRequest<T>(pathWithQuery: string, init?: RequestInit): Promise<T> {
  const path = pathWithQuery.split("?", 1)[0];
  const method = init?.method ?? "GET";
  advanceJobs();

  if (path === "/v1/conversations" && method === "GET") return conversations as T;
  if (path === "/v1/conversations" && method === "POST") {
    const payload = JSON.parse(String(init?.body)) as { title: string };
    const conversation: Conversation = {
      id: id("conversation-demo"),
      title: payload.title,
      createdAt: now(),
      updatedAt: now(),
    };
    conversations.unshift(conversation);
    return conversation as T;
  }
  if (path === "/v1/agent/capabilities" && method === "GET") {
    return {
      enabled: true,
      configured: true,
      available: true,
      reasonCode: null,
      provider: "openai-responses",
      model: "gpt-5.6-sol",
      text: true,
      streaming: true,
      functionTools: true,
      imageInput: true,
      imageGeneration: true,
      usage: true,
      transports: ["sse"],
      websocketDeclared: true,
      websocketVerified: false,
      toolsEnabled: true,
      tools: [
        { name: "propose_draft_patch", risk: "proposal", requiresApproval: false },
        { name: "generate_reference_image", risk: "costly", requiresApproval: true },
      ],
      maxTurns: 8,
      maxToolCalls: 12,
      maxApprovals: 3,
    } as T;
  }
  const conversationThread = path.match(/^\/v1\/conversations\/([^/]+)\/agent\/thread$/)?.[1];
  if (conversationThread && method === "GET") {
    const thread = agentThreads.get(conversationThread);
    return (thread ?? null) as T;
  }
  const messageThread = path.match(/^\/v1\/agent\/threads\/([^/]+)\/messages$/)?.[1];
  if (messageThread && method === "GET") {
    return (agentMessages.get(messageThread) ?? []) as T;
  }
  if (path === "/v1/agent/runs" && method === "POST") {
    const payload = JSON.parse(String(init?.body)) as {
      conversationId: string;
      message: string;
      draftSnapshot: StudioJob["draft"];
    };
    const thread = ensureDemoAgentThread(payload.conversationId);
    const runId = id("agent-run-demo");
    const createdAt = now();
    const run: AgentRun = {
      id: runId,
      threadId: thread.id,
      conversationId: payload.conversationId,
      status: "queued",
      model: "gpt-5.6-sol",
      provider: "openai-responses",
      transport: "sse",
      reasoningEffort: "xhigh",
      promptVersion: "oneiroi-agent-v1",
      toolsetVersion: "oneiroi-tools-v1",
      inputSnapshot: payload.draftSnapshot as unknown as Record<string, unknown>,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, providerRequests: 0 },
      createdAt,
    };
    agentRuns.set(runId, run);
    agentMessages.get(thread.id)?.push({
      id: id("agent-message-demo"),
      threadId: thread.id,
      runId,
      sequence: (agentMessages.get(thread.id)?.length ?? 0) + 1,
      role: "user",
      content: { text: payload.message, rationale: [], warnings: [] },
      status: "completed",
      createdAt,
      completedAt: createdAt,
    });
    scheduleDemoAgentRun(run, payload.message, payload.draftSnapshot);
    return run as T;
  }
  const agentRunId = path.match(/^\/v1\/agent\/runs\/([^/]+)$/)?.[1];
  if (agentRunId && method === "GET") {
    const run = agentRuns.get(agentRunId);
    if (!run) throw new Error("AGENT_RUN_NOT_FOUND");
    return run as T;
  }
  const cancelRunId = path.match(/^\/v1\/agent\/runs\/([^/]+)\/cancel$/)?.[1];
  if (cancelRunId && method === "POST") {
    const run = agentRuns.get(cancelRunId);
    if (!run) throw new Error("AGENT_RUN_NOT_FOUND");
    const cancelled: AgentRun = { ...run, status: "cancelled", finishedAt: now() };
    agentRuns.set(run.id, cancelled);
    emitDemoAgentEvent(cancelled, "agent.run.cancelled", { status: "cancelled" });
    return cancelled as T;
  }
  const decisionMatch = path.match(
    /^\/v1\/agent\/tool-calls\/([^/]+)\/(approve|reject)$/,
  );
  if (decisionMatch && method === "POST") {
    const [, toolCallId, decision] = decisionMatch;
    return decideDemoAgentTool(toolCallId, decision === "approve") as T;
  }
  if (path === "/v1/jobs" && method === "GET") return jobs as T;
  if (path === "/v1/assets" && method === "GET") return assets as T;
  if (path === "/v1/compute/gpus") {
    return {
      requestedDefault: 4,
      maximumSelectable: 4,
      gpus: [0, 1, 2, 7].map((physicalIndex) => ({
        id: `GPU-demo-${physicalIndex}`,
        physicalIndex,
        name: "Demo H100 80GB",
        vramTotalMiB: 81559,
        vramUsedMiB: 0,
        utilizationPercent: 0,
        temperatureCelsius: 30,
        state: "empty",
        eligible: true,
        unavailableReason: null,
        externalProcessCount: 0,
      })),
    } as T;
  }
  if (path === "/v1/compute/capabilities") {
    const response: ComputeCapabilities = {
      requestedDefault: 4,
      maximumSelectable: 4,
      profiles: [
        {
          id: "ltx23-distilled-fast-v1",
          tier: "fast",
          available: session !== null,
          resolutions: ["720p", "1080p"],
          durations: Array.from({ length: 15 }, (_, index) => index + 1),
          unavailableReason: session ? null : "COMPUTE_NOT_READY",
        },
        {
          id: "ltx23-dev-hq-v1",
          tier: "hq",
          available: Boolean(session && session.allocatedGpuCount >= 2),
          resolutions: ["1080p"],
          durations: Array.from({ length: 15 }, (_, index) => index + 1),
          unavailableReason:
            session && session.allocatedGpuCount < 2
              ? "HQ_REQUIRES_AT_LEAST_2_GPUS"
              : null,
        },
      ],
    };
    return response as T;
  }
  if (path === "/v1/compute/sessions" && method === "POST") {
    const payload = JSON.parse(String(init?.body)) as { requestedGpuCount: number };
    const count = Math.min(payload.requestedGpuCount, 4);
    const fast = count >= 3 ? 2 : count >= 1 ? 1 : 0;
    const hq = count === 4 ? 2 : count >= 2 ? 1 : 0;
    session = {
      id: id("compute-demo"),
      ownerId: "demo-user",
      createdAt: now(),
      state: "ready",
      requestedGpuCount: payload.requestedGpuCount,
      allocatedGpuCount: count,
      selectionMode: "auto",
      profilePolicy: "balanced",
      allowPartial: true,
      profilePlan: { fast, hq },
      slots: Array.from({ length: count }, (_, index) => ({
        id: id("slot-demo"),
        gpuId: `GPU-demo-${index}`,
        physicalIndex: index,
        state: "ready",
        profile: index < fast ? "fast" : "hq",
        loadStage: "ready",
        loadProgress: 100,
      })),
    };
    return session as T;
  }
  if (path.startsWith("/v1/compute/sessions/") && path.endsWith("/release")) {
    const released = { ...session, state: "released" };
    session = null;
    return released as T;
  }
  if (path.startsWith("/v1/compute/sessions/") && method === "GET") return session as T;
  if (path === "/v1/jobs/i2v" && method === "POST") {
    const payload = JSON.parse(String(init?.body)) as {
      conversationId: string;
      computeSessionId: string;
      draft: StudioJob["draft"];
    };
    const created: StudioJob & { demoStartedAt: number } = {
      id: id("job-demo"),
      conversationId: payload.conversationId,
      computeSessionId: payload.computeSessionId,
      createdAt: now(),
      updatedAt: now(),
      stage: "assigned",
      progress: 18,
      draft: payload.draft,
      profileId:
        payload.draft.profile === "hq" ? "ltx23-dev-hq-v1" : "ltx23-distilled-fast-v1",
      gpu: { id: "GPU-demo-0", physicalIndex: 0 },
      attempt: 1,
      demoStartedAt: Date.now(),
    };
    jobs.unshift(created);
    return created as T;
  }
  const jobId = path.match(/^\/v1\/jobs\/([^/]+)/)?.[1];
  const job = jobs.find((item) => item.id === jobId);
  if (job && method === "GET") return job as T;
  if (job && path.endsWith("/cancel") && method === "POST") {
    job.stage = "cancelled";
    job.updatedAt = now();
    return job as T;
  }
  if (job && path.endsWith("/retry") && method === "POST") {
    job.stage = "assigned";
    job.progress = 18;
    job.attempt += 1;
    job.demoStartedAt = Date.now();
    return job as T;
  }
  throw new Error(`Demo endpoint is not implemented: ${method} ${path}`);
}

export async function demoUpload(file: File): Promise<StudioAsset> {
  const asset: StudioAsset = {
    id: id("asset-demo"),
    type: "image",
    title: file.name,
    createdAt: now(),
    mediaType: file.type,
    sizeBytes: file.size,
    previewUrl: URL.createObjectURL(file),
  };
  assets.unshift(asset);
  return asset;
}

export function subscribeDemoAgentEvents(
  runId: string,
  afterEventId: string,
  accept: (event: AgentEvent) => void,
) {
  const cursor = Number(afterEventId || 0);
  for (const event of agentEvents.get(runId) ?? []) {
    if (Number(event.id) > cursor) accept(event);
  }
  const listeners = agentSubscribers.get(runId) ?? new Set();
  listeners.add(accept);
  agentSubscribers.set(runId, listeners);
  return () => {
    listeners.delete(accept);
    if (listeners.size === 0) agentSubscribers.delete(runId);
  };
}

function ensureDemoAgentThread(conversationId: string): AgentThread {
  const existing = agentThreads.get(conversationId);
  if (existing) return existing;
  const createdAt = now();
  const thread: AgentThread = {
    id: id("agent-thread-demo"),
    conversationId,
    status: "active",
    summaryCursor: 0,
    promptVersion: "oneiroi-agent-v1",
    createdAt,
    updatedAt: createdAt,
  };
  agentThreads.set(conversationId, thread);
  agentMessages.set(thread.id, []);
  return thread;
}

function emitDemoAgentEvent(
  run: AgentRun,
  type: string,
  data: Record<string, unknown>,
) {
  const events = agentEvents.get(run.id) ?? [];
  const event: AgentEvent = {
    id: String(++agentEventId),
    type,
    runId: run.id,
    threadId: run.threadId,
    sequence: events.length + 1,
    data,
  };
  events.push(event);
  agentEvents.set(run.id, events);
  for (const listener of agentSubscribers.get(run.id) ?? []) listener(event);
}

function scheduleDemoAgentRun(
  run: AgentRun,
  message: string,
  draft: StudioJob["draft"],
) {
  window.setTimeout(() => {
    const streaming: AgentRun = { ...run, status: "streaming", startedAt: now() };
    agentRuns.set(run.id, streaming);
    emitDemoAgentEvent(streaming, "agent.run.started", { status: "streaming" });
  }, 120);

  const wantsImage = /参考图|首帧|尾帧|图片|图像/.test(message);
  if (wantsImage) {
    window.setTimeout(() => proposeDemoImageTool(run, message, draft), 420);
    return;
  }
  window.setTimeout(() => {
    const response = {
      text: "我把主体动作、镜头连续性和环境细节整理成了更稳定的生成描述。请确认建议后再应用到草稿。",
      draftProposal: {
        prompt: `${draft.prompt} 保持主体身份与场景几何一致，动作连续自然，镜头运动克制，光线稳定。`,
      },
      rationale: ["补充连续性约束", "减少镜头与主体漂移"],
      warnings: [],
    };
    emitDemoAgentEvent(run, "agent.message.delta", { delta: JSON.stringify(response) });
    finishDemoAgentRun(run, response);
  }, 650);
}

function proposeDemoImageTool(run: AgentRun, message: string, draft: StudioJob["draft"]) {
  const purpose = /尾帧/.test(message) ? "last-frame" : "first-frame";
  const toolCall: AgentToolCall = {
    id: id("agent-tool-demo"),
    runId: run.id,
    toolName: "generate_reference_image",
    toolVersion: "1",
    risk: "costly",
    arguments: {
      prompt: draft.prompt,
      negativePrompt: draft.negativePrompt,
      purpose,
      ratio: draft.ratio,
      count: 1,
      referenceAssetIds: [draft.firstFrameAssetId, draft.lastFrameAssetId].filter(Boolean),
    },
    argumentsHash: "demo-arguments-hash",
    status: "waiting_approval",
    createdAt: now(),
  };
  const approval: AgentApproval = {
    id: id("agent-approval-demo"),
    runId: run.id,
    toolCallId: toolCall.id,
    argumentsHash: toolCall.argumentsHash,
    status: "pending",
    estimatedCost: "约 1 次图片生成额度",
    expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
  };
  agentToolCalls.set(toolCall.id, toolCall);
  agentApprovals.set(toolCall.id, approval);
  const waiting: AgentRun = { ...run, status: "waiting_approval" };
  agentRuns.set(run.id, waiting);
  emitDemoAgentEvent(waiting, "agent.tool.proposed", { toolCall });
  emitDemoAgentEvent(waiting, "agent.approval.required", { toolCall, approval });
  emitDemoAgentEvent(waiting, "agent.run.waiting_approval", {
    status: "waiting_approval",
  });
}

function decideDemoAgentTool(toolCallId: string, approved: boolean): AgentToolDecision {
  const toolCall = agentToolCalls.get(toolCallId);
  const approval = agentApprovals.get(toolCallId);
  if (!toolCall || !approval) throw new Error("AGENT_APPROVAL_NOT_FOUND");
  const run = agentRuns.get(toolCall.runId);
  if (!run) throw new Error("AGENT_RUN_NOT_FOUND");

  const decidedAt = now();
  const nextApproval: AgentApproval = {
    ...approval,
    status: approved ? "consumed" : "rejected",
    decidedAt,
    ...(approved ? { consumedAt: decidedAt } : {}),
  };
  const nextTool: AgentToolCall = {
    ...toolCall,
    status: approved ? "approved" : "rejected",
    ...(approved ? {} : { finishedAt: decidedAt }),
  };
  const nextRun: AgentRun = { ...run, status: approved ? "executing_tool" : "streaming" };
  agentApprovals.set(toolCallId, nextApproval);
  agentToolCalls.set(toolCallId, nextTool);
  agentRuns.set(run.id, nextRun);

  if (approved) {
    window.setTimeout(() => completeDemoImageTool(nextRun, nextTool), 450);
  } else {
    emitDemoAgentEvent(nextRun, "agent.run.resumed", { status: "streaming" });
    window.setTimeout(
      () => finishDemoAgentRun(nextRun, { text: "已取消本次参考图生成，草稿没有发生变化。" }),
      260,
    );
  }
  return { approval: nextApproval, toolCall: nextTool, run: nextRun };
}

function completeDemoImageTool(run: AgentRun, toolCall: AgentToolCall) {
  const running: AgentToolCall = { ...toolCall, status: "running", startedAt: now() };
  agentToolCalls.set(toolCall.id, running);
  emitDemoAgentEvent(run, "agent.tool.started", { toolCall: running });

  const purpose = String(toolCall.arguments.purpose ?? "first-frame");
  const title = purpose === "last-frame" ? "Agent 尾帧参考图" : "Agent 首帧参考图";
  const assetId = id("asset-agent-demo");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#252328"/><stop offset=".5" stop-color="#6b5f8f"/><stop offset="1" stop-color="#d8b768"/></linearGradient></defs><rect width="1280" height="720" fill="url(#g)"/><circle cx="930" cy="220" r="120" fill="#f7d978" opacity=".55"/><path d="M0 610 Q320 420 640 590 T1280 500 V720 H0Z" fill="#19181b" opacity=".72"/></svg>`;
  const asset: StudioAsset = {
    id: assetId,
    type: "image",
    title,
    createdAt: now(),
    mediaType: "image/png",
    sizeBytes: svg.length,
    width: 1280,
    height: 720,
    previewUrl: `data:image/svg+xml,${encodeURIComponent(svg)}`,
  };
  assets.unshift(asset);
  const result = {
    assets: [
      {
        id: asset.id,
        type: "image",
        title: asset.title,
        mediaType: asset.mediaType,
        sizeBytes: asset.sizeBytes,
        width: asset.width,
        height: asset.height,
      },
    ],
    partial: false,
    errorCode: null,
  };
  const completed: AgentToolCall = {
    ...running,
    status: "succeeded",
    result,
    finishedAt: now(),
  };
  agentToolCalls.set(toolCall.id, completed);
  emitDemoAgentEvent(run, "agent.tool.completed", { toolCall: completed });
  finishDemoAgentRun(run, {
    text: "参考图已安全保存为候选资产。请选择设为首帧、尾帧或仅保存；我不会自动修改草稿。",
  });
}

function finishDemoAgentRun(
  run: AgentRun,
  content: AgentMessage["content"],
) {
  const completedAt = now();
  const message: AgentMessage = {
    id: id("agent-message-demo"),
    threadId: run.threadId,
    runId: run.id,
    sequence: (agentMessages.get(run.threadId)?.length ?? 0) + 1,
    role: "assistant",
    content: {
      text: content.text,
      draftProposal: content.draftProposal,
      rationale: content.rationale ?? [],
      warnings: content.warnings ?? [],
    },
    status: "completed",
    createdAt: completedAt,
    completedAt,
  };
  agentMessages.get(run.threadId)?.push(message);
  const completed: AgentRun = {
    ...run,
    status: "completed",
    outputMessageId: message.id,
    finishedAt: completedAt,
    usage: { inputTokens: 320, outputTokens: 96, totalTokens: 416, providerRequests: 1 },
  };
  agentRuns.set(run.id, completed);
  emitDemoAgentEvent(completed, "agent.run.completed", { status: "completed" });
}

function advanceJobs() {
  for (const job of jobs) {
    if (!job.demoStartedAt || ["succeeded", "failed", "cancelled"].includes(job.stage)) continue;
    if (import.meta.env.VITE_DEMO_HOLD_JOBS === "true") {
      job.stage = "generating";
      job.progress = 65;
      job.phase = "diffusion";
      job.currentStep = 5;
      job.totalSteps = 8;
      job.updatedAt = now();
      continue;
    }
    const elapsed = Date.now() - job.demoStartedAt;
    if (elapsed >= 4_000) {
      job.stage = "succeeded";
      job.progress = 100;
      job.phase = "completed";
      job.warmStart = true;
      job.output = {
        assetId: `asset-${job.id}`,
        fileUrl: "",
        manifestUrl: "",
        mediaType: "video/mp4",
        sizeBytes: 0,
      };
    } else if (elapsed >= 3_000) {
      job.stage = "encoding";
      job.progress = 90;
      job.phase = "encoding";
    } else if (elapsed >= 1_500) {
      job.stage = "generating";
      job.progress = 65;
      job.phase = "diffusion";
      job.currentStep = 5;
      job.totalSteps = 8;
    } else if (elapsed >= 500) {
      job.stage = "preparing";
      job.progress = 30;
      job.phase = "prompt_encoding";
    }
    job.updatedAt = now();
  }
}
