r"""服务层补充探测：覆盖既有 pytest 未涉及的规范条目（使用独立 issueflow_test 库）。

用法：仓库根目录执行
    .\.venv\Scripts\python.exe scripts\audit\service_invariants_probe.py
前置：docker compose up -d db；已 createdb issueflow_test。
"""
import os
import secrets
import sys
import threading
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://issueflow:issueflow_local@127.0.0.1:5432/issueflow_test")
os.environ["JWT_SECRET"] = "audit-only-" + secrets.token_urlsafe(40)
os.environ["LLM_ENABLED"] = "false"

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update

from app.auth import hasher
from app.classifier import rule_classify
from app.db import Session, engine
from app.errors import BusinessError
from app.models import Event, Ticket, User, utcnow
from app.schemas import CategoryUpdate, Clarification, ContentUpdate, StatusUpdate
from app.service import Principal, apply_classification, create, detail, mutate, recover_pending

if not engine.url.database.endswith("_test"):
    raise SystemExit("拒绝对非 _test 数据库执行探测")

rows = []


def check(name, expected, actual, ok=None):
    ok = expected == actual if ok is None else ok
    rows.append((name, expected, actual, "PASS" if ok else "FAIL"))


def reset():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ticket_events, ticket_revisions, tickets, users RESTART IDENTITY CASCADE"))
    pw = hasher.hash("Test-password-2026!")
    with Session.begin() as db:
        db.add_all([
            User(username="emp", display_name="员工", password_hash=pw, role="employee"),
            User(username="emp2", display_name="员工2", password_hash=pw, role="employee"),
            User(username="sup", display_name="技支", password_hash=pw, role="support"),
        ])


def events(ticket_id, event_type=None):
    with Session() as db:
        found = db.scalars(select(Event).where(Event.ticket_id == ticket_id).order_by(Event.id)).all()
        return [e for e in found if event_type is None or e.event_type == event_type]


def main():
    reset()
    emp, emp2, sup = Principal(1, "employee"), Principal(2, "employee"), Principal(3, "support")

    # 1) 分类未完成时禁止结单（安全规范 §6.2 建议规则）
    snap, _ = create(emp, "P1", "登录失败")
    with Session.begin() as db:
        db.execute(update(Ticket).where(Ticket.request_id == "P1").values(classification_source="pending"))
    try:
        mutate(sup, "P1", "status", StatusUpdate(expected_version=snap["version"], status="completed"))
        check("pending 分类时结单被拒绝", (409, "CLASSIFICATION_PENDING"), (200, "NO_ERROR"))
    except BusinessError as e:
        check("pending 分类时结单被拒绝", (409, "CLASSIFICATION_PENDING"), (e.status, e.code))

    # 2) 结单时关闭待响应补充请求 + clarification_closed 事件（规范 §6.2）
    snap2, _ = create(emp, "P2", "登录失败")
    apply_classification(snap2, rule_classify("登录失败"))
    t = detail(emp, "P2")
    t = mutate(sup, "P2", "clarification", Clarification(expected_version=t["version"], message="请补充错误码"))
    done = mutate(sup, "P2", "status", StatusUpdate(expected_version=t["version"], status="completed"))
    check("结单后 edit_requested", False, done["edit_requested"])
    closed = events(done["id"], "clarification_closed")
    check("结单写 clarification_closed", (1, "ticket_completed"), (len(closed), closed[0].detail.get("reason")))
    check("结单事件顺序",
          ["ticket_created", "ticket_classified", "clarification_requested", "status_changed", "clarification_closed"],
          [e.event_type for e in events(done["id"])])

    # 3) 系统分类事件 actor_id 为空且带证据（规范 §1.4）
    classified = events(done["id"], "ticket_classified")[0]
    check("系统事件 actor_id=NULL", None, classified.actor_id)
    check("分类事件含规则版本/证据", True, {"rule_version", "evidence", "reason"} <= set(classified.detail))

    # 4) 并发同号但不同原文：只能一张、另一方 409（补充 T04 只测同文的空白）
    results = []
    barrier = threading.Barrier(2)

    def run(content):
        barrier.wait()
        try:
            _, created = create(emp, "RACE2", content)
            results.append(("ok", created))
        except BusinessError as e:
            results.append((e.status, e.code))

    threads = [threading.Thread(target=run, args=(c,)) for c in ("登录失败", "系统特别慢")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with Session() as db:
        count = db.scalar(select(func.count()).select_from(Ticket).where(Ticket.request_id == "RACE2"))
    check("并发同号异文：仅一张工单", 1, count)
    check("并发同号异文：一方成功一方 409", True,
          any(r[0] == "ok" for r in results) and any(r[0] == 409 and r[1] == "REQUEST_ID_CONFLICT" for r in results))
    print("   并发结果:", sorted(map(str, results)))

    # 5) 越权：技支不是提交者也不能改正文；他人不可见时按 404（规范 §3/§8）
    snap3, _ = create(emp, "P3", "登录失败")
    apply_classification(snap3, rule_classify("登录失败"))
    t3 = detail(emp, "P3")
    t3 = mutate(sup, "P3", "clarification", Clarification(expected_version=t3["version"], message="补充"))
    try:
        mutate(sup, "P3", "content", ContentUpdate(expected_version=t3["version"], content="技支代改"))
        check("技支改他人正文", (403, "FORBIDDEN"), (200, "NO_ERROR"))
    except BusinessError as e:
        check("技支改他人正文", (403, "FORBIDDEN"), (e.status, e.code))
    try:
        mutate(emp2, "P3", "content", ContentUpdate(expected_version=t3["version"], content="他人改我"))
        check("他人改我正文（不可见优先 404）", (404, "TICKET_NOT_FOUND"), (200, "NO_ERROR"))
    except BusinessError as e:
        check("他人改我正文（不可见优先 404）", (404, "TICKET_NOT_FOUND"), (e.status, e.code))
    try:
        mutate(emp2, "P3", "status", StatusUpdate(expected_version=t3["version"], status="completed"))
        check("员工2改状态", (403, "FORBIDDEN"), (200, "NO_ERROR"))
    except BusinessError as e:
        check("员工2改状态", (403, "FORBIDDEN"), (e.status, e.code))

    # 6) 分类值未变化但来源变化时的事件语义（规范 §6.5 "有实际变化才记录事件"）
    #    当前实现：来源 rule→manual 会写一条 old_category==new_category 的 category_corrected（见审查报告 D2）。
    t4 = detail(emp, "P3")
    before = len(events(t4["id"], "category_corrected"))
    mutate(sup, "P3", "category", CategoryUpdate(expected_version=t4["version"], category=t4["category"], reason="确认无误"))
    after = events(t4["id"], "category_corrected")
    check("同值人工确认写入事件（既有行为，见 D2）", 1, len(after) - before)
    if after:
        print("   事件细节:", after[-1].detail)

    # 7) pending 恢复任务：按 updated_at 老化后降级，重复执行幂等（规范 §7.3）
    snap5, _ = create(emp, "P5", "含糊信息")
    with Session.begin() as db:
        db.execute(update(Ticket).where(Ticket.request_id == "P5")
                   .values(updated_at=utcnow() - timedelta(minutes=2)))
    check("恢复一次", 1, recover_pending())
    check("恢复重复执行", 0, recover_pending())
    p5 = detail(emp, "P5")
    check("恢复结果", ("uncertain", "fallback"), (p5["category"], p5["classification_source"]))
    check("恢复事件幂等", 1, len(events(p5["id"], "classification_failed")))

    # 8) 过期快照回写失败（规范 §7.2）
    snap6, _ = create(emp, "P6", "登录失败")
    t6 = detail(emp, "P6")
    mutate(sup, "P6", "status", StatusUpdate(expected_version=t6["version"], status="in_progress"))
    check("到期分类快照被拒绝", False, apply_classification(snap6, rule_classify("登录失败")))
    check("未覆盖当前分类来源", "pending", detail(emp, "P6")["classification_source"])

    width = max(len(str(r[0])) for r in rows)
    for name, exp, act, res in rows:
        print(f"{str(name).ljust(width)} | 期望 {str(exp)[:38].ljust(38)} | 实际 {str(act)[:38].ljust(38)} | {res}")
    fails = [r for r in rows if r[3] == "FAIL"]
    print(f"\n合计 {len(rows)} 项，PASS {len(rows) - len(fails)}，FAIL {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
