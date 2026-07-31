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

test("mobile workspace sidebar can collapse and reopen", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only interaction");
  await page.goto("/create");

  await expect(page.getByRole("button", { name: "展开会话栏" })).toBeVisible();
  await page.getByRole("button", { name: "展开会话栏" }).click();
  await expect(page.getByRole("button", { name: "新建创作" })).toBeInViewport();
  await page.getByRole("button", { name: "收起会话栏" }).click();
  await expect(page.getByRole("button", { name: "展开会话栏" })).toBeVisible();
});
