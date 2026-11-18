"use client";
import { useState } from "react";
import { Layers2 } from "lucide-react";
import { api, User } from "../lib/api";
export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await api("/auth/csrf");
      onLogin(
        await api<User>("/auth/login", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(data)),
        }),
      );
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-form">
        <div className="brand">
          <span className="brand-mark">
            <Layers2 size={18} />
          </span>
          IssueFlow
        </div>
        <h1 className="sr-only">登录工作台</h1>
        <form onSubmit={submit}>
          <label>
            用户名
            <input
              name="username"
              autoComplete="username"
              required
              maxLength={50}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={200}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? "正在登录…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
