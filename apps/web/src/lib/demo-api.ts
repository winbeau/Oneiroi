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
