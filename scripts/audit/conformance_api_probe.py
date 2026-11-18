"""独立符合性探测：直接打真实运行的 IssueFlow API（127.0.0.1:8010）。

只使用虚构账号/虚构正文；新建工单统一使用 AUDIT- 前缀，按项目"审计保留"原则不删除。
每个断言输出 (用例, 期望, 实际, 结论)。
"""
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8010"
PASSWORD = "123456123456zm"
STAMP = time.strftime("%m%d%H%M%S")
rows = []


def check(name, expected, actual, ok=None):
    if ok is None:
        ok = expected == actual
    rows.append((name, expected, actual, "PASS" if ok else "FAIL"))


def session(username):
    c = httpx.Client(base_url=BASE, timeout=10.0, trust_env=False)
    token = c.get("/api/auth/csrf").json()["csrf_token"]
    c.headers["x-csrf-token"] = token
    r = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, (username, r.status_code, r.text)
    c.headers["x-csrf-token"] = c.cookies["issueflow_csrf"]
    return c


def main():
    anon = httpx.Client(base_url=BASE, timeout=10.0, trust_env=False)
    check("未登录 GET /api/tickets", 401, anon.get("/api/tickets").status_code)
    check("未登录 POST /api/tickets", 401, anon.post("/api/tickets", json={"request_id": "x", "content": "y"}).status_code)

    li = session("xiaoli")
    zhou = session("xiaozhou")
    sup = session("support")

    rid = "AUDIT-" + STAMP
    body = "系统登录页面一直转圈，我进不去。" + STAMP

    # --- 输入校验 ---
    for label, content in [("空串", ""), ("单空格", " "), ("换行制表", "\n\t\r"), ("全角空格", "\u3000\u3000"),
                           ("超长5001", "字" * 5001)]:
        r = li.post("/api/tickets", json={"request_id": rid + "-bad", "content": content})
        check(f"非法正文({label})", 422, r.status_code)
    for label, identifier in [("含空格", "A B"), ("路径穿越", "../x"), ("空", ""), ("65字符", "X" * 65), ("中文", "中文编号")]:
        r = li.post("/api/tickets", json={"request_id": identifier, "content": "登录失败"})
        check(f"非法编号({label})", 422, r.status_code)
    r = li.post("/api/tickets", json={"request_id": rid + "-extra", "content": "登录失败", "submitter_id": 2})
    check("请求体额外字段 submitter_id", 422, r.status_code)
    r = li.post("/api/tickets", json={"request_id": rid + "-len", "content": "字" * 5000})
    check("正文恰好5000字符", 201, r.status_code, r.status_code in (201,))

    # --- 创建与幂等 ---
    r1 = li.post("/api/tickets", json={"request_id": rid, "content": body})
    check("首次创建", 201, r1.status_code)
    t = r1.json()
    check("创建后含原文", body, t["original_text"])
    check("创建后 current=original", True, t["current_text"] == t["original_text"])
    ver = t["version"]

    r2 = li.post("/api/tickets", json={"request_id": rid, "content": body})
    check("同人同原文重试", 200, r2.status_code)
    check("重试返回同一条", t["id"], r2.json()["id"])
    r3 = li.post("/api/tickets", json={"request_id": rid, "content": body + "改"})
    check("同号异文", 409, r3.status_code)
    check("同号异文错误码", "REQUEST_ID_CONFLICT", r3.json().get("code"))
    check("冲突响应不泄露原文", True, body not in r3.text and str(t["submitter_id"]) not in r3.text)
    r3b = zhou.post("/api/tickets", json={"request_id": rid, "content": body})
    check("同号异人", 409, r3b.status_code)

    # 大小写与下划线保留
    lower = li.post("/api/tickets", json={"request_id": (rid + "-case").lower(), "content": "登录失败" + STAMP})
    upper = li.post("/api/tickets", json={"request_id": (rid + "-case").upper(), "content": "登录失败" + STAMP})
    check("request_id 大小写区分", (201, 201, True), (lower.status_code, upper.status_code,
          lower.json()["request_id"] != upper.json()["request_id"]))

    # --- 数据/角色边界 ---
    check("员工读他人工单详情", 404, zhou.get(f"/api/tickets/{rid}").status_code)
    check("员工读他人工单历史", 404, zhou.get(f"/api/tickets/{rid}/history").status_code)
    listing = zhou.get("/api/tickets", params={"page_size": 100}).json()
    check("员工列表仅本人", True, all(i["submitter_id"] == zhou.get("/api/auth/me").json()["id"] for i in listing["items"]))
    check("员工改状态", 403, li.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver}).status_code)
    check("员工发起补充", 403, li.post(f"/api/tickets/{rid}/clarification-request", json={"message": "补充", "expected_version": ver}).status_code)
    check("技支代改他人正文", 403, sup.patch(f"/api/tickets/{rid}/content", json={"content": "越权修改", "expected_version": ver}).status_code)

    # --- 补充请求与正文修订 ---
    check("无补充请求时员工改正文", 409, li.patch(f"/api/tickets/{rid}/content", json={"content": "修改", "expected_version": ver}).status_code)
    r = sup.post(f"/api/tickets/{rid}/clarification-request", json={"message": "请提供错误码与时间", "expected_version": ver})
    check("技支发起补充", 200, r.status_code)
    ver = r.json()["version"]
    check("edit_requested 已置位", True, r.json()["edit_requested"])
    r = sup.post(f"/api/tickets/{rid}/clarification-request", json={"message": "再发一次", "expected_version": ver})
    check("重复补充请求", 409, r.status_code)
    check("重复补充错误码", "CLARIFICATION_ALREADY_REQUESTED", r.json().get("code"))
    r = li.patch(f"/api/tickets/{rid}/content", json={"content": body, "expected_version": ver})
    check("补充内容与当前相同", 409, r.status_code)
    r = li.patch(f"/api/tickets/{rid}/content", json={"content": "  ", "expected_version": ver})
    check("补充内容仅空白", 422, r.status_code)
    r = li.patch(f"/api/tickets/{rid}/content", json={"content": "系统登录提示403错误，发生在08:20左右" + STAMP, "expected_version": ver})
    check("提交者补充正文", 200, r.status_code)
    t2 = r.json()
    ver = t2["version"]
    check("原文不变", body, t2["original_text"])
    check("当前正文更新", True, t2["current_text"].startswith("系统登录提示403"))
    check("补充后 edit_requested 关闭", False, t2["edit_requested"])
    check("补充后重新分类来源", ("pending", "rule", "llm", "fallback"), t2["classification_source"],
          t2["classification_source"] in ("pending", "rule", "llm", "fallback"))
    h = li.get(f"/api/tickets/{rid}/history").json()
    check("修订记录 1 条", 1, len(h["revisions"]))
    check("修订含完整旧新内容", True, h["revisions"][0]["old_text"] == body and h["revisions"][0]["new_text"].startswith("系统登录提示403"))
    check("content_updated 仅引用 revision_id", True,
          any(e["event_type"] == "content_updated" and set(e["detail"].keys()) == {"revision_id"} for e in h["events"]))
    check("clarification_requested 带要求", True,
          any(e["event_type"] == "clarification_requested" and e["detail"].get("message") == "请提供错误码与时间" for e in h["events"]))

    # --- 版本 CAS ---
    check("使用过期版本改状态", 409, sup.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver - 1}).status_code)
    check("过期版本错误码", "TICKET_VERSION_CONFLICT",
          sup.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver - 1}).json().get("code"))

    # --- 分类未完成不允许结单（建议规则）---
    if t2["classification_source"] == "pending":
        r = sup.patch(f"/api/tickets/{rid}/status", json={"status": "completed", "expected_version": ver})
        check("分类pending时结单", 409, r.status_code)
    r = sup.patch(f"/api/tickets/{rid}/category", json={"category": "system_fault", "reason": "确认是登录异常", "expected_version": ver})
    check("技支人工确认分类", 200, r.status_code)
    ver = r.json()["version"]
    check("人工分类来源", ("manual", "system_fault"), (r.json()["classification_source"], r.json()["category"]))
    r = sup.patch(f"/api/tickets/{rid}/category", json={"category": "system_fault", "reason": "原因不能空", "expected_version": ver})
    check("重复相同分类(manual)", 200, r.status_code)
    check("重复相同分类不涨版本", ver, r.json()["version"])
    r = sup.patch(f"/api/tickets/{rid}/category", json={"category": "system_fault", "reason": "   ", "expected_version": ver})
    check("分类原因为空白", 422, r.status_code)
    r = sup.patch(f"/api/tickets/{rid}/category", json={"category": "not_a_category", "reason": "x", "expected_version": ver})
    check("非法分类值", 422, r.status_code)

    # --- 状态机 ---
    r = sup.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver})
    check("pending→in_progress", 200, r.status_code)
    ver = r.json()["version"]
    r = sup.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver})
    check("同状态空操作", 200, r.status_code)
    check("同状态不涨版本", ver, r.json()["version"])
    r = sup.patch(f"/api/tickets/{rid}/status", json={"status": "pending", "expected_version": ver})
    check("in_progress→pending", 200, r.status_code)
    ver = r.json()["version"]
    r = sup.patch(f"/api/tickets/{rid}/status", json={"status": "completed", "expected_version": ver})
    check("pending→completed", 200, r.status_code)
    ver = r.json()["version"]

    # --- 终态只读 ---
    check("完成后改状态", 409, sup.patch(f"/api/tickets/{rid}/status", json={"status": "in_progress", "expected_version": ver}).status_code)
    check("完成后改分类", 409, sup.patch(f"/api/tickets/{rid}/category", json={"category": "uncertain", "reason": "复核", "expected_version": ver}).status_code)
    check("完成后发起补充", 409, sup.post(f"/api/tickets/{rid}/clarification-request", json={"message": "补充", "expected_version": ver}).status_code)
    check("完成后查详情", 200, li.get(f"/api/tickets/{rid}").status_code)
    check("完成后查历史", 200, li.get(f"/api/tickets/{rid}/history").status_code)
    r = li.post("/api/tickets", json={"request_id": rid, "content": body})
    check("完成后同号幂等重试", 200, r.status_code)
    check("完成后重试仍是终态", "completed", r.json()["status"])

    # --- 分页与筛选 ---
    check("page_size 超上限", 422, sup.get("/api/tickets", params={"page_size": 101}).status_code)
    check("page=0", 422, sup.get("/api/tickets", params={"page": 0}).status_code)
    check("非法 status 枚举", 422, sup.get("/api/tickets", params={"status": "done"}).status_code)
    q = sup.get("/api/tickets", params={"q": rid, "category": "system_fault", "status": "completed"}).json()
    check("技支按编号+分类+状态检索", True, any(i["request_id"] == rid for i in q["items"]))
    check("LIKE 通配符按字面处理", 0, sup.get("/api/tickets", params={"q": "%_%"}).json()["total"])

    # --- CSRF / 安全头 ---
    nohdr = httpx.Client(base_url=BASE, timeout=10.0, trust_env=False, cookies=li.cookies)
    check("缺 CSRF 头的写请求", 403, nohdr.post("/api/tickets", json={"request_id": "AUDIT-CSRF", "content": "登录失败"}).status_code)
    hdr = li.get("/api/health")
    check("安全响应头", ("nosniff", "DENY", "no-store"),
          (hdr.headers.get("x-content-type-options"), hdr.headers.get("x-frame-options"), hdr.headers.get("cache-control")))
    check("XSS 正文按原始文本存储", True, "<script>" in li.post("/api/tickets", json={"request_id": "AUDIT-XSS-" + STAMP,
          "content": "<script>alert(1)</script> 登录失败"}).json()["original_text"])

    width = [max(len(str(r[0])), 10) for r in rows]
    print(f"{'用例'.ljust(width[0])} | {'期望'.ljust(28)} | {'实际'.ljust(28)} | 结论")
    print("-" * (width[0] + 70))
    for name, exp, act, res in rows:
        print(f"{str(name).ljust(width[0])} | {str(exp)[:28].ljust(28)} | {str(act)[:28].ljust(28)} | {res}")
    fails = [r for r in rows if r[3] == "FAIL"]
    print(f"\n合计 {len(rows)} 项，PASS {len(rows) - len(fails)}，FAIL {len(fails)}")
    for name, exp, act, _ in fails:
        print("FAIL:", name, "| 期望", exp, "| 实际", act)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

