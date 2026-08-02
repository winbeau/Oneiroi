import { expect, type Page, test } from "@playwright/test";

type BackendOptions = {
  gpuCount?: number;
  failRequests?: boolean;
  emitComputeReadyEvent?: boolean;
  emitLoadingModelJobEvent?: boolean;
  replayPriorAttemptTerminalEvent?: boolean;
  onComputeEventsRequest?: () => void;
  onJobEventsRequest?: () => void;
};

async function mockBackend(page: Page, options: BackendOptions = {}) {
  const gpuCount = options.gpuCount ?? 1;
  let session: Record<string, unknown> | null = null;
  let conversations: Array<Record<string, unknown>> = [];
  let jobs: Array<Record<string, unknown>> = [];
  let assets: Array<Record<string, unknown>> = [];

  await page.route("**/v1/**", async (route) => {
    if (options.failRequests) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "GATEWAY_UNAVAILABLE" }),
      });
      return;
    }
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body: unknown, status = 200, contentType = "application/json") =>
      route.fulfill({ status, contentType, body: JSON.stringify(body) });

    if (path === "/v1/conversations" && method === "GET") return json(conversations);
    if (path === "/v1/conversations" && method === "POST") {
      const payload = request.postDataJSON() as { title: string };
      const conversation = {
        id: "conversation-e2e",
        title: payload.title,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      conversations = [conversation];
      return json(conversation, 201);
    }
    if (path === "/v1/jobs" && method === "GET") return json(jobs);
    if (path === "/v1/assets" && method === "GET") return json(assets);
    if (path === "/v1/compute/gpus") {
      return json({
        requestedDefault: 4,
        maximumSelectable: 4,
        gpus: Array.from({ length: 4 }, (_, index) => ({
          id: `GPU-e2e-${index}`,
          physicalIndex: index,
          name: "NVIDIA H100 80GB HBM3",
          vramTotalMiB: 81559,
          vramUsedMiB: index < gpuCount ? 0 : 40000,
          utilizationPercent: index < gpuCount ? 0 : 80,
          temperatureCelsius: 30,
          state: index < gpuCount ? "empty" : "foreign_busy",
          eligible: index < gpuCount,
          unavailableReason: index < gpuCount ? null : "EXTERNAL_COMPUTE_PROCESS",
          externalProcessCount: index < gpuCount ? 0 : 1,
        })),
      });
    }
    if (path === "/v1/compute/capabilities") {
      const hasSession = url.searchParams.has("sessionId");
      return json({
        requestedDefault: 4,
        maximumSelectable: 4,
        profiles: [
          {
            id: "ltx23-distilled-fast-v1",
            tier: "fast",
            available: !hasSession || Boolean(session),
            resolutions: ["720p", "1080p"],
            durations: Array.from({ length: 15 }, (_, index) => index + 1),
            unavailableReason: null,
          },
          {
            id: "ltx23-dev-hq-v1",
            tier: "hq",
            available: Boolean(session && gpuCount >= 2),
            resolutions: ["1080p"],
            durations: Array.from({ length: 15 }, (_, index) => index + 1),
            unavailableReason:
              session && gpuCount < 2 ? "HQ_REQUIRES_AT_LEAST_2_GPUS" : null,
          },
        ],
      });
    }
    if (path === "/v1/compute/sessions" && method === "POST") {
      const allocated = Math.min(gpuCount, 4);
      const fast = allocated >= 3 ? 2 : allocated >= 1 ? 1 : 0;
      const hq = allocated === 4 ? 2 : allocated >= 2 ? 1 : 0;
      session = {
        id: "compute-e2e",
        state: options.emitComputeReadyEvent
          ? "loading"
          : allocated < 4
            ? "degraded"
            : "ready",
        requestedGpuCount: 4,
        allocatedGpuCount: allocated,
        selectionMode: "auto",
        profilePolicy: "balanced",
        allowPartial: true,
        profilePlan: { fast, hq },
        slots: Array.from({ length: allocated }, (_, index) => ({
          id: `slot-${index}`,
          gpuId: `GPU-e2e-${index}`,
          physicalIndex: index,
          state: options.emitComputeReadyEvent ? "loading" : "ready",
          profile: index < fast ? "fast" : "hq",
          loadStage: options.emitComputeReadyEvent ? "loading_model" : "ready",
          loadProgress: options.emitComputeReadyEvent ? 60 : 100,
        })),
      };
      return json(session, 202);
    }
    if (path === "/v1/compute/sessions/compute-e2e" && method === "GET") {
      return json(session);
    }
    if (path.endsWith("/compute/sessions/compute-e2e/events")) {
      options.onComputeEventsRequest?.();
      if (options.emitComputeReadyEvent && session) {
        session = {
          ...session,
          state: "ready",
          slots: (session.slots as Array<Record<string, unknown>>).map((slot) => ({
            ...slot,
            state: "ready",
            loadStage: "ready",
            loadProgress: 100,
          })),
        };
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `id: 1\nevent: compute.session.ready\ndata: ${JSON.stringify(session)}\n\n`,
        });
      }
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: ": heartbeat\n\n" });
    }
    if (path.endsWith("/compute/sessions/compute-e2e/release") && method === "POST") {
      const released = { ...session, state: "released" };
      session = null;
      return json(released);
    }
    if (path === "/v1/jobs/i2v" && method === "POST") {
      const payload = request.postDataJSON() as {
        conversationId: string;
        computeSessionId: string;
        draft: Record<string, unknown>;
      };
      const now = new Date().toISOString();
      const job = {
        id: "job-e2e",
        conversationId: payload.conversationId,
        computeSessionId: payload.computeSessionId,
        createdAt: now,
        updatedAt: now,
        stage: "assigned",
        progress: 18,
        draft: payload.draft,
        profileId: "ltx23-distilled-fast-v1",
        gpu: { id: "GPU-e2e-0", physicalIndex: 0 },
        attempt: options.replayPriorAttemptTerminalEvent ? 2 : 1,
      };
      jobs = [job];
      return json(job, 202);
    }
    if (path === "/v1/jobs/job-e2e/events") {
      options.onJobEventsRequest?.();
      if (options.replayPriorAttemptTerminalEvent) {
        const current = {
          ...jobs[0],
          updatedAt: new Date(Date.now() + 1_000).toISOString(),
          stage: "generating",
          progress: 70,
          phase: "diffusion",
          currentStep: 5,
          totalSteps: 8,
        };
        jobs = [current];
        const prior = {
          ...current,
          attempt: 1,
          updatedAt: new Date(Date.now() - 1_000).toISOString(),
          stage: "failed",
          progress: 20,
          phase: "failed",
        };
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `id: 1\nevent: job.failed\ndata: ${JSON.stringify(prior)}\n\nid: 2\nevent: job.updated\ndata: ${JSON.stringify(current)}\n\n`,
        });
      }
      if (options.emitLoadingModelJobEvent) {
        const loading = {
          ...jobs[0],
          updatedAt: new Date().toISOString(),
          stage: "loading_model",
          progress: 0,
          phase: "model_loading",
        };
        jobs = [loading];
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `id: 1\nevent: job.updated\ndata: ${JSON.stringify(loading)}\n\n`,
        });
      }
      const succeeded = {
        ...jobs[0],
        stage: "succeeded",
        progress: 100,
        phase: "completed",
        warmStart: true,
        output: {
          assetId: "asset-e2e",
          fileUrl: "/v1/jobs/job-e2e/file",
          manifestUrl: "/v1/jobs/job-e2e/manifest",
          mediaType: "video/mp4",
          sizeBytes: 12345,
        },
      };
      jobs = [succeeded];
      assets = [
        {
          id: "asset-e2e",
          type: "video",
          title: "生成视频",
          createdAt: new Date().toISOString(),
          mediaType: "video/mp4",
          sizeBytes: 12345,
          previewUrl: "/v1/jobs/job-e2e/file",
          sourceJobId: "job-e2e",
        },
      ];
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `id: 1\nevent: job.updated\ndata: ${JSON.stringify({ ...succeeded, stage: "generating", progress: 70, phase: "diffusion", currentStep: 5, totalSteps: 8 })}\n\nid: 2\nevent: job.succeeded\ndata: ${JSON.stringify(succeeded)}\n\n`,
      });
    }
    if (path === "/v1/jobs/job-e2e" && method === "GET") return json(jobs[0]);
    return json({ detail: `unhandled ${method} ${path}` }, 404);
  });
}

async function loadCompute(page: Page) {
  await page.goto("/compute");
  await expect(page.getByRole("button", { name: "热加载算力" })).toBeVisible();
  await page.getByRole("button", { name: "热加载算力" }).click();
  await page.getByRole("button", { name: "开始热加载" }).click();
  await expect(page.getByRole("link", { name: /张 H100/ })).toBeVisible();
}

test("compute page gates HQ and completes a video-first conversation", async ({ page }) => {
  await mockBackend(page, { gpuCount: 1 });
  await page.goto("/create");
  await expect(page.getByRole("link", { name: "算力未加载" })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeDisabled();
  await loadCompute(page);
  await expect(page.getByRole("heading", { name: "GPU Inventory" })).toBeVisible();
  await expect(page.getByRole("button", { name: "实时 3s" })).toBeVisible();
  await expect(page.getByText("GPU Workloads", { exact: true })).toBeVisible();
  await expect(page.getByText(/GPU-demo-0/)).toHaveCount(0);
  await expect(page.getByText("MEMORY USAGE", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/compute-demo-/)).toHaveCount(0);
  await page.goto("/create");
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "选择 LTX 2.3 模型" }).click();
  await expect(page.getByRole("button", { name: /LTX 2.3 高质量/ })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "生成", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("GPU 0").last()).toBeVisible();
  await expect(page.getByText("Oneiroi，让每个想象都有下一帧。")).toHaveCount(0);
});

test("compute load works when crypto.randomUUID is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      configurable: true,
      value: undefined,
    });
  });
  await mockBackend(page, { gpuCount: 1 });
  await loadCompute(page);
  await expect(page.getByRole("link", { name: /1 张 H100/ })).toBeVisible();
});

test("compute SSE does not reconnect when a snapshot updates", async ({ page }) => {
  let eventRequests = 0;
  await mockBackend(page, {
    gpuCount: 1,
    emitComputeReadyEvent: true,
    onComputeEventsRequest: () => {
      eventRequests += 1;
    },
  });
  await loadCompute(page);
  await expect(page.getByRole("link", { name: /1 张 H100/ })).toBeVisible();
  await page.waitForTimeout(500);
  expect(eventRequests).toBe(1);
});

test("job SSE stays subscribed and hides technical zero-progress recovery", async ({ page }) => {
  let eventRequests = 0;
  await mockBackend(page, {
    gpuCount: 1,
    emitLoadingModelJobEvent: true,
    onJobEventsRequest: () => {
      eventRequests += 1;
    },
  });
  await loadCompute(page);
  await page.goto("/create");
  await page.getByRole("button", { name: "生成", exact: true }).click();

  await expect(page.getByText("正在恢复匹配的模型").first()).toBeVisible();
  await expect(page.locator(".generation-waiting")).toBeVisible();
  await expect(page.getByText(/PipelineSpec/)).toHaveCount(0);
  await expect(page.getByText("0%", { exact: true })).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(eventRequests).toBe(1);
});

test("old terminal events do not close a retried job stream", async ({ page }) => {
  await mockBackend(page, { gpuCount: 1, replayPriorAttemptTerminalEvent: true });
  await loadCompute(page);
  await page.goto("/create");
  await page.getByRole("button", { name: "生成", exact: true }).click();

  await expect(page.getByText("正在生成视频", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("70%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("失败", { exact: true })).toHaveCount(0);
});

test("release returns compute control to the empty state", async ({ page }) => {
  await mockBackend(page, { gpuCount: 2 });
  await loadCompute(page);
  await page.getByRole("button", { name: "释放资源" }).click();
  await page.getByRole("button", { name: "确认释放" }).click();
  await expect(page.getByRole("link", { name: "算力未加载" })).toBeVisible();
});

test("production API failure never becomes a fake success", async ({ page }) => {
  await mockBackend(page, { failRequests: true });
  await page.goto("/create");

  await expect(page.getByText(/Gateway 会话服务不可用/)).toBeVisible();
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeDisabled();
  await page.waitForTimeout(1_000);
  await expect(page.getByText("已完成", { exact: true })).toHaveCount(0);
});

test("template remains editable in the streamlined creation composer", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/inspiration");
  await page.getByRole("button", { name: "套用到生成" }).first().click();
  await expect(page.getByRole("textbox", { name: "生成提示词" })).toHaveValue(
    /fortified mountain city/,
  );
  await expect(page.getByText("Oneiroi，让每个想象都有下一帧。")).toBeVisible();
  await expect(page.getByRole("button", { name: "更换首帧" })).toBeVisible();
  await expect(page.getByRole("button", { name: "上传尾帧" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Agent", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "打开高级参数" })).toHaveCount(0);

  await page.getByRole("button", { name: "选择画面比例和分辨率" }).click();
  await expect(page.getByRole("button", { name: "21:9", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "16:9", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "4:3", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "1:1", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "3:4", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "9:16", exact: true })).toBeEnabled();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "选择视频生成时长" }).click();
  await expect(page.getByRole("slider", { name: "视频时长" })).toHaveAttribute("min", "1");
  await expect(page.getByRole("slider", { name: "视频时长" })).toHaveAttribute("max", "15");
  const durationInput = page.getByRole("spinbutton", { name: "手动输入视频时长" });
  await durationInput.fill("15");
  await durationInput.press("Enter");
  await expect(page.getByRole("button", { name: "选择视频生成时长" })).toContainText("15 秒");
});

test("mobile workspace sidebar can collapse and reopen", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only interaction");
  await mockBackend(page);
  await page.goto("/create");
  await page.getByRole("button", { name: "展开会话栏" }).click();
  await expect(page.getByRole("button", { name: "新建创作" })).toBeVisible();
  await page.getByRole("button", { name: "收起会话栏" }).click();
  await expect(page.getByRole("button", { name: "展开会话栏" })).toBeVisible();
});
