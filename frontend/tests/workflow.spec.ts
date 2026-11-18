import { test, expect, Page } from "@playwright/test";
const password = process.env.DEMO_PASSWORD || "123456123456zm";
async function login(page: Page, username: string) {
  await page.goto("/");
  await expect(page).toHaveTitle("IssueFlow · 内部问题登记");
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "工单工作台", exact: true }),
  ).toBeVisible();
}
async function open(page: Page, id: string) {
  await page.getByLabel("搜索编号或反馈内容").fill(id);
  await page.getByRole("button", { name: id, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: id, exact: true }),
  ).toBeVisible();
}
test("员工提交 → 技支补充请求 → 本人补充 → 人工复核 → 完成 → 终态只读", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("status of 401"))
      errors.push(message.text());
  });
  const id = "E2E-" + Date.now();
  await login(page, "xiaoli");
  await page
    .getByRole("button", { name: "提交工单", exact: true })
    .last()
    .click();
  await page.getByLabel("提交编号", { exact: true }).fill(id);
  await page
    .getByLabel("反馈内容", { exact: true })
    .fill("登录失败 <script>window.__xss=true</script>");
  await page.getByRole("button", { name: "确认提交" }).click();
  await expect(page.getByRole("heading", { name: id })).toBeVisible();
  await expect(
    page.getByText("登录失败 <script>window.__xss=true</script>", {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__xss,
    ),
  ).toBeUndefined();
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, "support");
  await open(page, id);
  await page
    .getByLabel("请求补充信息", { exact: true })
    .fill("请补充错误码与发生时间");
  await page.getByRole("button", { name: "发送补充请求" }).click();
  await expect(page.getByRole("heading", { name: "待补充信息" })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, "xiaoli");
  await open(page, id);
  await page
    .getByLabel("补充后的完整内容")
    .fill("系统登录提示403错误，发生在今天上午。");
  await page.getByRole("button", { name: "提交补充并重新分类" }).click();
  await expect(page.getByText("提交补充内容", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, "support");
  await open(page, id);
  await page
    .getByLabel("人工确认分类", { exact: true })
    .selectOption("uncertain");
  await page.getByLabel("更正原因").fill("尚需核实根因，人工改为待确认");
  await page.getByRole("button", { name: "保存分类" }).click();
  await expect(
    page.getByText("待确认 · 人工确认", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("工单状态", { exact: true })
    .selectOption("in_progress");
  await page.getByRole("button", { name: "更新状态" }).click();
  await expect(
    page.getByText("待处理 → 处理中", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("工单状态", { exact: true }).selectOption("completed");
  await page.getByRole("button", { name: "更新状态" }).click();
  await expect(page.getByText("工单已完成")).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("detail-desktop.png"),
    fullPage: true,
  });
  await page.getByText("查看首次提交原文").click();
  await expect(
    page
      .getByText("登录失败 <script>window.__xss=true</script>", { exact: true })
      .first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("桌面工作台、筛选与移动端布局", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page, "support");
  await open(page, "R001");
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  await page.screenshot({
    path: test.info().outputPath("workspace-desktop.png"),
  });
  await page.getByRole("tab", { name: "已完成", exact: true }).click();
  await expect(page.getByRole("tab", { name: "已完成" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("tab", { name: "全部工单" }).click();
  await page.getByLabel("分类筛选").selectOption("system_fault");
  await expect
    .poll(async () => [
      ...new Set(
        await page.locator("tbody tr td:nth-child(3)").allTextContents(),
      ),
    ])
    .toEqual(["系统故障"]);
  await page.getByLabel("分类筛选").selectOption("");
  await page.getByLabel("搜索编号或反馈内容").fill("R008");
  await expect(
    page.getByRole("button", { name: "R008", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("workspace-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("button", { name: "提交工单", exact: true })
    .last()
    .click();
  await expect(page.getByLabel("反馈内容", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("多用户示例显示创建者，员工仍只看自己的工单", async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page, 'support');
  await expect(page.getByRole('columnheader', { name: '创建者', exact: true })).toBeVisible();
  for (const [id, name, username] of [
    ['DEMO-ZHOU-01', '小周', 'xiaozhou'],
    ['DEMO-CHEN-01', '小陈', 'xiaochen'],
    ['DEMO-SUPPORT-01', '小林', 'support'],
    ['DEMO-SUPPORT2-01', '小吴', 'support2'],
  ]) {
    await page.getByLabel('搜索编号或反馈内容').fill(id);
    const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: id, exact: true }) });
    await expect(row.locator('.creator-name')).toHaveText(name);
    await expect(row.locator('.creator-account')).toHaveText(username);
    await open(page, id);
    await expect(page.getByText(`创建者：${name}（${username}）`, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '返回工作台', exact: true }).click();
  }
  await page.getByLabel('搜索编号或反馈内容').fill('DEMO-');
  await expect(page.getByRole('button', { name: 'DEMO-CHEN-01', exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('creators-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('搜索编号或反馈内容').fill('DEMO-CHEN-01');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  const mobileRow = page.getByRole('row').filter({ has: page.getByRole('button', { name: 'DEMO-CHEN-01', exact: true }) });
  await expect(mobileRow.getByText('创建者：小陈', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath('creators-mobile.png') });
  await page.getByRole('button', { name: '退出登录' }).click();
  await login(page, 'xiaozhou');
  await open(page, 'DEMO-ZHOU-01');
  await expect(page.getByText('创建者：小周（xiaozhou）', { exact: true })).toBeVisible();
  expect((await page.request.get('/api/tickets/DEMO-CHEN-01')).status()).toBe(404);
  const own = await page.request.get('/api/tickets?q=DEMO-');
  const data = await own.json();
  expect(data.total).toBeGreaterThanOrEqual(3);
  expect(data.items.every((ticket: { submitter_username: string }) => ticket.submitter_username === 'xiaozhou')).toBeTruthy();
  expect(errors).toEqual([]);
});
