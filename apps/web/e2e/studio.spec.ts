import { expect, test } from "@playwright/test";

test("template to generation to asset flow", async ({ page }) => {
  await page.goto("/inspiration");

  await expect(page.getByRole("heading", { name: "从一个清晰想法开始" })).toBeVisible();
  await page.getByRole("button", { name: "套用到生成" }).first().click();

  await expect(page).toHaveURL(/\/create$/);
  await expect(page.getByRole("textbox", { name: "生成提示词" })).toHaveValue(
    /built-in headboard shelf/,
  );

  await page.getByRole("button", { name: "生成", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible({ timeout: 12_000 });

  await page.getByRole("link", { name: "资产" }).click();
  await expect(page.getByText(/生成视频/).first()).toBeVisible();
});

test("create landing centers the composer with image video and Agent entries", async ({ page }) => {
  await page.goto("/create");

  await expect(page.getByText("从两个瞬间，生长出一段镜头")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "生成提示词" })).toBeVisible();
  await expect(page.getByRole("button", { name: "图片", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "视频", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Agent", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Agent", exact: true }).click();
  await expect(page.getByRole("button", { name: "收起 Agent 模式" })).toBeVisible();
});

test("advanced controls and asset preview remain accessible", async ({ page }) => {
  await page.goto("/create");

  await page.getByRole("button", { name: "打开高级参数" }).click();
  await expect(page.getByText("精确控制随机性、关键帧约束与显存策略。")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("link", { name: "资产" }).click();
  await page.getByRole("button", { name: /^预览 / }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "关闭预览" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("mobile workspace sidebar can collapse and reopen", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only interaction");
  await page.goto("/create");

  await expect(page.getByRole("button", { name: "展开会话栏" })).toBeVisible();
  await page.getByRole("button", { name: "展开会话栏" }).click();
  await expect(page.getByRole("button", { name: "新建创作" })).toBeInViewport();
  await page.getByRole("button", { name: "收起会话栏" }).click();
  await expect(page.getByRole("button", { name: "展开会话栏" })).toBeVisible();
});
