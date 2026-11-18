// Real browser recording with Chinese explanatory subtitles; no credentials in the video.
import { chromium, expect } from "@playwright/test";
import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
const out = path.resolve("../deliverables");
await mkdir(out, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  recordVideo: { dir: out, size: { width: 1440, height: 960 } },
});
const page = await context.newPage();
const started = Date.now();
const segments = [];
const id = "DEMO-" + Date.now();
const original = "今天登录失败，刷新后仍然无法进入工作台。";
async function caption(title, text, seconds = 12) {
  segments.push({
    seconds: Math.round((Date.now() - started) / 1000),
    title,
    text,
  });
  console.log(title);
  await page.evaluate(
    ({ title, text }) => {
      let element = document.getElementById("demo-caption");
      if (!element) {
        element = document.createElement("div");
        element.id = "demo-caption";
        document.body.append(element);
      }
      element.style.cssText =
        'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);width:92%;max-width:1250px;padding:16px 24px;background:#14233bf2;color:white;border-radius:10px;z-index:9999;font:16px/1.65 Arial,"Microsoft YaHei",sans-serif;pointer-events:none;box-shadow:0 4px 30px #17223522';
      element.replaceChildren();
      const heading = document.createElement("strong");
      heading.textContent = title;
      heading.style.cssText =
        "display:block;font-size:19px;margin-bottom:4px;color:#b9d1ff";
      const body = document.createElement("span");
      body.textContent = text;
      element.append(heading, body);
    },
    { title, text },
  );
  await page.waitForTimeout(seconds * 1000);
}
async function login(username) {
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.DEMO_PASSWORD || "123456123456zm");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "工单工作台", exact: true }),
  ).toBeVisible();
}
async function logout() {
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "登录工作台" })).toBeVisible();
}
async function open() {
  await page.getByLabel("搜索编号或反馈内容").fill(id);
  await page.getByRole("button", { name: id, exact: true }).click();
}
try {
  await page.goto("http://localhost:3000");
  await caption(
    "01 · IssueFlow 本地业务演示",
    "企业内部问题登记小助手。演示包含员工提交、规则分类、幂等重试、技术支持处理、补充信息、历史追溯与终态锁定。",
  );
  await login("xiaoli");
  await expect(
    page.getByRole("button", { name: "R001", exact: true }),
  ).toBeVisible();
  await caption(
    "02 · 使用者与信息边界",
    "当前为员工小李。列表仅包含本人提交的工单；身份来自登录账号，后端执行数据归属校验。技术支持拥有共享工单池。",
  );
  await page
    .getByRole("button", { name: "提交工单", exact: true })
    .last()
    .click();
  await page.getByLabel("提交编号", { exact: true }).fill(id);
  await page.getByLabel("反馈内容", { exact: true }).fill("   ");
  await expect(page.getByRole("button", { name: "确认提交" })).toBeDisabled();
  await caption(
    "03 · 空白校验与原文保留",
    "仅空白内容无法提交；后端还会验证 Unicode 空白、长度与编号格式。有效文本完整保存，不裁剪、改写或推测缺失信息。",
  );
  await page.getByLabel("反馈内容", { exact: true }).fill(original);
  await caption(
    "04 · 唯一提交编号",
    "编号用于系统全局幂等。首次提交创建一张工单；同一人以同一编号、同一原文重试会返回原工单。",
  );
  await page.getByRole("button", { name: "确认提交" }).click();
  await expect(page.getByRole("heading", { name: id })).toBeVisible();
  await caption(
    "05 · 分类与业务成功分开",
    "该反馈命中“登录失败”高确定性规则。规则不确定时才使用 DeepSeek；总预算为60秒，超时或输出无效则降级待确认，工单仍然保存成功。",
  );
  await page.getByRole("button", { name: "提交工单", exact: true }).click();
  await page.getByLabel("提交编号", { exact: true }).fill(id);
  await page.getByLabel("反馈内容", { exact: true }).fill(original);
  await page.getByRole("button", { name: "确认提交" }).click();
  await expect(page.getByRole("heading", { name: id })).toBeVisible();
  await caption(
    "06 · 重试不会重复建单",
    "再次提交返回相同工单和原有历史，不新增创建事件、不再次初始化分类。数据库唯一约束是并发下的最终裁决。",
  );
  await logout();
  await login("support");
  await caption(
    "07 · 技术支持工作台",
    "切换为技术支持小林，可查询所有员工工单。技支也能提交自己的工单，但不能代改他人的原始反馈。",
  );
  await open();
  await page
    .getByLabel("人工确认分类", { exact: true })
    .selectOption("uncertain");
  await page
    .getByLabel("更正原因")
    .fill("根因仍需核实，人工将分类调整为待确认。");
  await caption(
    "08 · 人工复核须填写原因",
    "模型输出只是派生信息。技术支持可以确认或纠正分类，必须说明理由；旧模型结果不会覆盖已人工确认的分类。",
  );
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
  await caption(
    "09 · 状态流转与并发控制",
    "工单进入处理中，事件记录操作人、前后状态与时间。每次写入携带预期版本；并发冲突返回 409，不能静默覆盖。",
  );
  await page
    .getByLabel("请求补充信息", { exact: true })
    .fill("请补充登录页面的具体错误码，以及首次出现问题的时间。");
  await page.getByRole("button", { name: "发送补充请求" }).click();
  await expect(page.getByRole("heading", { name: "待补充信息" })).toBeVisible();
  await caption(
    "10 · 有限授权的补充请求",
    "技术支持发起一次待响应的补充请求，不新增第四种处理状态。请求本身只记审计事件，不伪造正文修订。",
  );
  await logout();
  await login("xiaoli");
  await open();
  await page
    .getByLabel("补充后的完整内容")
    .fill("系统登录提示403错误，今天上午9点首次出现，刷新后仍无法进入。");
  await caption(
    "11 · 只有提交者本人可以回应",
    "小李收到补充要求后更新当前有效内容。没有开放请求时不能主动编辑；技术支持也不能替员工改写正文。",
  );
  await page.getByRole("button", { name: "提交补充并重新分类" }).click();
  await expect(page.getByText("提交补充内容", { exact: true })).toBeVisible();
  await caption(
    "12 · 正文修订与重新分类",
    "更新当前正文、关闭补充授权、保存旧新内容和操作事件，在同一事务提交。然后按新版本重新分类，旧响应不能过期回写。",
  );
  await page.getByText("查看首次提交原文").click();
  await caption(
    "13 · 首次原文始终保留",
    "展开后仍可看到首次反馈。当前内容可在授权补充中变化，original_text 永不覆盖；历史记录在数据库层禁止修改和删除。",
  );
  await logout();
  await login("support");
  await open();
  await page.getByLabel("工单状态", { exact: true }).selectOption("completed");
  await page.getByRole("button", { name: "更新状态" }).click();
  await expect(
    page.getByText("工单已完成，内容、分类与状态均已锁定。"),
  ).toBeVisible();
  await caption(
    "14 · 已完成是终态",
    "完成后不能再改变状态、分类或正文，也不能重新打开。若仍有待回应的补充请求，完成事务会同时关闭请求并记录原因。",
  );
  await page
    .getByRole("heading", { name: "操作历史" })
    .scrollIntoViewIfNeeded();
  await caption(
    "15 · 可追溯的业务历史",
    "创建、自动分类、人工复核、状态变化、补充请求与正文修订均可查询。系统动作 actor 为空，不伪装为技术支持人员。",
  );
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  await page.getByRole("tab", { name: "已完成", exact: true }).click();
  await caption(
    "16 · 查询和持续运行",
    "工作台支持状态、分类、文字搜索与分页。PostgreSQL 持久化数据；轻量恢复任务会将长期中断的分类安全降级。",
  );
  await caption(
    "17 · 已验证的安全与一致性",
    "交付包含真实 PostgreSQL 独立连接并发、审计失败回滚、权限与归属、模型超时及乱序响应测试；另有真实 pg_dump / pg_restore 的四表数据核对。",
  );
  await caption(
    "18 · 边界与上线取舍",
    "V1 不包含管理员、派单、评论、删除和撤销。真实企业上线前应完成身份接入、HTTPS、外部模型合规审批、最小数据库权限和定时加密备份。",
  );
  while (Date.now() - started < 300000)
    await page.waitForTimeout(Math.min(15000, 300000 - (Date.now() - started)));
  await context.close();
  const target = path.join(out, "IssueFlow-演示.webm");
  await rename(await page.video().path(), target);
  await writeFile(
    path.join(out, "演示分段.json"),
    JSON.stringify(
      { session_wall_seconds: (Date.now() - started) / 1000, ticket: id, segments },
      null,
      2,
    ),
  );
  console.log("Video saved: " + target);
} finally {
  await browser.close();
}
