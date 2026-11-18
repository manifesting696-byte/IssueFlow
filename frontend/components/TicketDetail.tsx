"use client";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  categories,
  date,
  History,
  sources,
  statuses,
  Ticket,
  User,
} from "../lib/api";
const eventLabels: Record<string, string> = {
  ticket_created: "创建工单",
  ticket_classified: "完成自动分类",
  classification_failed: "分类降级，待人工确认",
  category_corrected: "人工修正分类",
  clarification_requested: "请求补充信息",
  clarification_closed: "关闭补充请求",
  content_updated: "提交补充内容",
  status_changed: "变更工单状态",
};
function eventText(type: string, detail: Record<string, unknown>) {
  if (type === "status_changed")
    return `${statuses[String(detail.old_status)]} → ${statuses[String(detail.new_status)]}`;
  if (type === "category_corrected")
    return `${categories[String(detail.old_category)]} → ${categories[String(detail.new_category)]}；原因：${detail.reason}`;
  if (type === "clarification_requested") return String(detail.message);
  if (type === "ticket_classified")
    return `${categories[String(detail.category)]} · ${sources[String(detail.source)]}${detail.evidence ? "；依据：" + detail.evidence : ""}`;
  return "";
}
export default function TicketDetail({
  initial,
  user,
  onBack,
  onChange,
}: {
  initial: Ticket;
  user: User;
  onBack: () => void;
  onChange: () => void;
}) {
  const [ticket, setTicket] = useState(initial);
  const [history, setHistory] = useState<History>({
    events: [],
    revisions: [],
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [category, setCategory] = useState(initial.category);
  const [status, setStatus] = useState(initial.status);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [content, setContent] = useState(initial.current_text);
  const base = "/tickets/" + encodeURIComponent(initial.request_id);
  const refresh = useCallback(async () => {
    const [next, history] = await Promise.all([
      api<Ticket>(base),
      api<History>(base + "/history"),
    ]);
    setTicket(next);
    setHistory(history);
    setCategory(next.category);
    setStatus(next.status);
    setContent(next.current_text);
  }, [base]);
  useEffect(() => {
    refresh()
      .then(() => setLoaded(true))
      .catch((e) => setError(e.message));
  }, [refresh]);
  async function mutate(
    path: string,
    values: Record<string, unknown>,
    method = "PATCH",
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(base + path, {
        method,
        body: JSON.stringify({ ...values, expected_version: ticket.version }),
      });
      await refresh();
      onChange();
      setNotice("操作已保存");
      setReason("");
      setMessage("");
    } catch (error) {
      setError((error as Error).message);
      if (error instanceof ApiError && error.status === 409) {
        await refresh();
        setNotice("已刷新至最新版本，请确认后重新操作");
      }
    } finally {
      setBusy(false);
    }
  }
  const closed = ticket.status === "completed";
  const request = [...history.events]
    .reverse()
    .find((event) => event.event_type === "clarification_requested");
  if (!loaded)
    return (
      <div>
        <p role="status">正在读取工单…</p>
        {error && (
          <>
            <p className="error" role="alert">
              {error}
            </p>
            <button onClick={onBack}>返回工作台</button>
          </>
        )}
      </div>
    );
  return (
    <>
      <div className="detail-top">
        <button onClick={onBack}>
          <ArrowLeft size={16} />
          返回工作台
        </button>
        <button
          aria-label="刷新工单"
          onClick={() => refresh().catch((e) => setError(e.message))}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="detail-heading">
        <h2>{ticket.request_id}</h2>
        <span className={"status " + ticket.status}>
          {statuses[ticket.status]}
        </span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="detail-grid">
        <section>
          <div className="meta">
            <span>创建者：{ticket.submitter_name}（{ticket.submitter_username}）</span>
            <span>
              {categories[ticket.category]} ·{" "}
              {sources[ticket.classification_source]}
            </span>
            <span>提交于 {date(ticket.created_at)}</span>
          </div>
          <h3>反馈内容</h3>
          <p className="feedback">{ticket.current_text}</p>
          {ticket.current_text !== ticket.original_text && (
            <details>
              <summary>查看首次提交原文</summary>
              <p className="feedback original">{ticket.original_text}</p>
            </details>
          )}
          {ticket.edit_requested && (
            <div className="clarification">
              <h3>待补充信息</h3>
              <p>{String(request?.detail.message || "请补充问题信息")}</p>
            </div>
          )}
          {ticket.submitter_id === user.id &&
            ticket.edit_requested &&
            !closed && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutate("/content", { content });
                }}
              >
                <label>
                  补充后的完整内容
                  <textarea
                    rows={5}
                    required
                    maxLength={5000}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                  />
                </label>
                <button
                  className="primary"
                  disabled={
                    busy || !content.trim() || content === ticket.current_text
                  }
                >
                  提交补充并重新分类
                </button>
              </form>
            )}
          <h3 className="history-heading">操作历史</h3>
          <ol className="timeline">
            {history.events.map((event) => (
              <li key={event.id}>
                <div>
                  <strong>
                    {eventLabels[event.event_type] || event.event_type}
                  </strong>
                  <span>
                    {event.actor_id === null
                      ? "系统"
                      : "用户 #" + event.actor_id}{" "}
                    · {date(event.created_at)}
                  </span>
                </div>
                {eventText(event.event_type, event.detail) && (
                  <p>{eventText(event.event_type, event.detail)}</p>
                )}
                {event.event_type === "content_updated" &&
                  history.revisions
                    .filter((r) => r.id === event.detail.revision_id)
                    .map((r) => (
                      <details key={r.id}>
                        <summary>查看正文修订</summary>
                        <p className="feedback">修改前：{r.old_text}</p>
                        <p className="feedback">修改后：{r.new_text}</p>
                      </details>
                    ))}
              </li>
            ))}
          </ol>
        </section>
        <aside className="operation-panel">
          <h3>{user.role === "support" ? "处理工单" : "处理进度"}</h3>
          {closed ? (
            <p className="muted">工单已完成</p>
          ) : user.role === "support" ? (
            <>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutate("/status", { status });
                }}
              >
                <label>
                  工单状态
                  <select
                    aria-label="工单状态"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    {Object.entries(statuses).map(([key, value]) => (
                      <option key={key} value={key}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <button disabled={busy || status === ticket.status}>
                  更新状态
                </button>
              </form>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutate("/category", { category, reason });
                }}
              >
                <label>
                  人工确认分类
                  <select
                    aria-label="人工确认分类"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    {Object.entries(categories).map(([key, value]) => (
                      <option key={key} value={key}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  更正原因
                  <textarea
                    rows={2}
                    maxLength={1000}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    required
                  />
                </label>
                <button disabled={busy || !reason.trim() || category === ticket.category}>保存分类</button>
              </form>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutate("/clarification-request", { message }, "POST");
                }}
              >
                <label>
                  请求补充信息
                  <textarea
                    rows={3}
                    maxLength={1000}
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    required
                    disabled={ticket.edit_requested}
                    placeholder={
                      ticket.edit_requested
                        ? "已有待响应的补充请求"
                        : "说明需要员工补充的信息"
                    }
                  />
                </label>
                <button
                  disabled={busy || ticket.edit_requested || !message.trim()}
                >
                  发送补充请求
                </button>
              </form>
            </>
          ) : (
            <p className="muted">由技术支持跟进</p>
          )}
        </aside>
      </div>
    </>
  );
}
