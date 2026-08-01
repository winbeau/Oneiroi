import { expect, type Page, test } from "@playwright/test";

type BackendOptions = { gpuCount?: number; failRequests?: boolean };

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
            durations: [5, 8, 10],
            unavailableReason: null,
          },
          {
            id: "ltx23-dev-hq-v1",
            tier: "hq",
            available: Boolean(session && gpuCount >= 2),
            resolutions: ["1080p"],
            durations: [5],
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
        state: allocated < 4 ? "degraded" : "ready",
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
          state: "ready",
          profile: index < fast ? "fast" : "hq",
          loadStage: "ready",
          loadProgress: 100,
        })),
      };
      return json(session, 202);
    }
    if (path === "/v1/compute/sessions/compute-e2e" && method === "GET") {
      return json(session);
    }
    if (path.endsWith("/compute/sessions/compute-e2e/events")) {
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
        attempt: 1,
      };
      jobs = [job];
      return json(job, 202);
    }
    if (path === "/v1/jobs/job-e2e/events") {
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

test("compute load gates HQ and completes a real API-driven timeline", async ({ page }) => {
  await mockBackend(page, { gpuCount: 1 });
  await page.goto("/create");

  await expect(page.getByText("GPU 资源未加载")).toBeVisible();
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "热加载" }).click();
  await page.getByRole("button", { name: "开始热加载" }).click();

  await expect(page.getByText(/1 张 H100/)).toBeVisible();
  await expect(page.getByRole("button", { name: "高质量" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await page.getByRole("button", { name: "生成", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("GPU 0").last()).toBeVisible();
});

test("compute load works when crypto.randomUUID is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      configurable: true,
      value: undefined,
    });
  });
  await mockBackend(page, { gpuCount: 1 });
  await page.goto("/create");
  await page.getByRole("button", { name: "热加载" }).click();
  await page.getByRole("button", { name: "开始热加载" }).click();

  await expect(page.getByText(/1 张 H100/)).toBeVisible();
});

test("release returns compute control to the empty state", async ({ page }) => {
  await mockBackend(page, { gpuCount: 2 });
  await page.goto("/create");
  await page.getByRole("button", { name: "热加载" }).click();
  await page.getByRole("button", { name: "开始热加载" }).click();
  await page.getByRole("button", { name: "释放资源" }).click();
  await page.getByRole("button", { name: "确认释放" }).click();
  await expect(page.getByText("GPU 资源未加载")).toBeVisible();
});

test("production API failure never becomes a fake success", async ({ page }) => {
  await mockBackend(page, { failRequests: true });
  await page.goto("/create");

  await expect(page.getByText(/Gateway 会话服务不可用/)).toBeVisible();
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeDisabled();
  await page.waitForTimeout(1_000);
  await expect(page.getByText("已完成", { exact: true })).toHaveCount(0);
});

test("template remains editable and Agent suggestions require explicit adoption", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/inspiration");
  await page.getByRole("button", { name: "套用到生成" }).first().click();
  await expect(page.getByRole("textbox", { name: "生成提示词" })).toHaveValue(
    /built-in headboard shelf/,
  );
  await page.getByRole("button", { name: "Agent", exact: true }).click();
  await page.getByPlaceholder("例如：她从隐藏书柜里拿出一本书").fill("她打开柜门");
  await page.getByRole("button", { name: "整理镜头" }).click();
  await expect(page.getByText("镜头建议 · 等待确认")).toBeVisible();
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
