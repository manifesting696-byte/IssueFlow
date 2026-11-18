"use client";
import { useState } from "react";
import { api, Ticket } from "../lib/api";
export default function CreateTicket({
  onCreated,
  onCancel,
}: {
  onCreated: (ticket: Ticket) => void;
  onCancel: () => void;
}) {
  const [requestId, setRequestId] = useState(() => "R-" + crypto.randomUUID());
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onCreated(
        await api<Ticket>("/tickets", {
          method: "POST",
          body: JSON.stringify({ request_id: requestId, content }),
        }),
      );
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="form-section">
      <h2>提交工单</h2>

      <form onSubmit={submit}>
        <label>
          提交编号
          <input
            aria-label="提交编号"
            value={requestId}
            onChange={(e) => setRequestId(e.target.value)}
            pattern={"[A-Za-z0-9_\\-]{1,64}"}
            maxLength={64}
            required
          />
        </label>
        <label>
          反馈内容
          <textarea
            aria-label="反馈内容"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            required
            maxLength={5000}
          />
          <small className="character-count">
            {Array.from(content).length} / 5000
          </small>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="primary" disabled={busy || !content.trim()}>
            {busy ? "正在提交…" : "确认提交"}
          </button>
          <button type="button" onClick={onCancel}>
            返回工作台
          </button>
        </div>
      </form>
    </section>
  );
}
