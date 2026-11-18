"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ClipboardList,
  FilePlus2,
  LogOut,
  UserRound,
  Plus,
  Layers2,
} from "lucide-react";
import { api, ApiError, Ticket, User } from "../lib/api";
import Login from "../components/Login";
import TicketList from "../components/TicketList";
import CreateTicket from "../components/CreateTicket";
import TicketDetail from "../components/TicketDetail";
export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<"list" | "create" | "detail">("list");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [items, setItems] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch((error) => {
        if (!(error instanceof ApiError && error.status === 401))
          setError(error.message);
      })
      .finally(() => setReady(true));
  }, []);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    if (!user || view !== "list") return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ page: String(page), q: query });
        if (status) params.set("status", status);
        if (category) params.set("category", category);
        const data = await api<{ items: Ticket[]; total: number }>(
          "/tickets?" + params,
          { signal: controller.signal },
        );
        setItems(data.items);
        setTotal(data.total);
      } catch (error) {
        if (!controller.signal.aborted) {
          if (error instanceof ApiError && error.status === 401) setUser(null);
          setError((error as Error).message);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [user, view, page, query, status, category, revision]);
  if (!ready) return <div className="boot">正在打开 IssueFlow…</div>;
  if (!user)
    return (
      <Login
        onLogin={(user) => {
          setUser(user);
          setView("list");
          setPage(1);
          setError("");
        }}
      />
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Layers2 size={18} />
          </span>
          IssueFlow
        </div>
        <nav aria-label="主导航">
          <button
            aria-current={view !== "create" ? "page" : undefined}
            className={view !== "create" ? "active" : ""}
            onClick={() => {
              setView("list");
              refresh();
            }}
          >
            <ClipboardList size={20} />
            工单工作台
          </button>
          <button
            aria-current={view === "create" ? "page" : undefined}
            className={view === "create" ? "active" : ""}
            onClick={() => setView("create")}
          >
            <FilePlus2 size={20} />
            提交工单
          </button>
        </nav>
        <div className="user-panel">
          <span className="avatar">
            <UserRound size={23} />
          </span>
          <div>
            <strong>{user.display_name}</strong>
            <small>{user.role === "support" ? "技术支持" : "员工"}</small>
          </div>
          <button
            aria-label="退出登录"
            title="退出登录"
            onClick={async () => {
              try {
                await api("/auth/logout", { method: "POST" });
                setUser(null);
                setSelected(null);
                setItems([]);
              } catch (error) {
                setError((error as Error).message);
              }
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main className="workspace">
        {view === "list" && (
          <>
            <header className="page-header">
              <div>
                <h1>工单工作台</h1>
              </div>
              <button className="primary" onClick={() => setView("create")}>
                <Plus size={16} aria-hidden="true" />
                提交工单
              </button>
            </header>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <TicketList
              items={items}
              total={total}
              page={page}
              status={status}
              category={category}
              query={query}
              loading={loading}
              onStatus={(s) => {
                setStatus(s);
                setPage(1);
              }}
              onCategory={(s) => {
                setCategory(s);
                setPage(1);
              }}
              onQuery={(s) => {
                setQuery(s);
                setPage(1);
              }}
              onPage={setPage}
              onOpen={(ticket) => {
                setSelected(ticket);
                setView("detail");
              }}
            />
          </>
        )}
        {view === "create" && (
          <CreateTicket
            onCancel={() => setView("list")}
            onCreated={(ticket) => {
              setSelected(ticket);
              setView("detail");
              refresh();
            }}
          />
        )}
        {view === "detail" && selected && (
          <TicketDetail
            key={selected.id}
            initial={selected}
            user={user}
            onBack={() => setView("list")}
            onChange={refresh}
          />
        )}
      </main>
    </div>
  );
}
