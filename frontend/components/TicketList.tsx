"use client";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  X,
  LoaderCircle,
} from "lucide-react";
import { categories, date, statuses, Ticket } from "../lib/api";
export default function TicketList({
  items,
  total,
  page,
  status,
  category,
  query,
  loading,
  onStatus,
  onCategory,
  onQuery,
  onPage,
  onOpen,
}: {
  items: Ticket[];
  total: number;
  page: number;
  status: string;
  category: string;
  query: string;
  loading: boolean;
  onStatus: (s: string) => void;
  onCategory: (s: string) => void;
  onQuery: (s: string) => void;
  onPage: (p: number) => void;
  onOpen: (t: Ticket) => void;
}) {
  return (
    <>
      <div
        className="tabs"
        role="tablist"
        aria-label="工单状态"
        onKeyDown={(event) => {
          const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
          if (!keys.includes(event.key)) return;
          event.preventDefault();
          const tabs = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>(
              '[role="tab"]',
            ),
          );
          const index = tabs.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          const next =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? tabs.length - 1
                : (index +
                    (event.key === "ArrowRight" ? 1 : -1) +
                    tabs.length) %
                  tabs.length;
          tabs[next]?.focus();
          tabs[next]?.click();
        }}
      >
        {[["", "全部工单"], ...Object.entries(statuses)].map(
          ([value, text]) => (
            <button
              key={value}
              role="tab"
              tabIndex={status === value ? 0 : -1}
              aria-selected={status === value}
              className={status === value ? "selected" : ""}
              onClick={() => onStatus(value)}
            >
              {text}
            </button>
          ),
        )}
      </div>
      <div className="filters">
        <div className="search">
          <Search size={19} />
          <input
            aria-label="搜索编号或反馈内容"
            placeholder="搜索编号或反馈内容"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            maxLength={200}
          />
          {query && (
            <button
              className="search-clear"
              aria-label="清空搜索"
              onClick={() => onQuery("")}
            >
              <X size={14} />
            </button>
          )}
        </div>
        <select
          aria-label="分类筛选"
          value={category}
          onChange={(e) => onCategory(e.target.value)}
        >
          <option value="">全部分类</option>
          {Object.entries(categories).map(([key, value]) => (
            <option key={key} value={key}>
              {value}
            </option>
          ))}
        </select>
      </div>
      <div className="table-wrap" aria-busy={loading}>
        <table aria-label="工单列表">
          <thead>
            <tr>
              <th scope="col">工单编号</th>
              <th scope="col">反馈内容</th>
              <th scope="col">分类</th>
              <th scope="col">状态</th>
              <th scope="col">创建者</th>
              <th scope="col">提交时间</th>
            </tr>
          </thead>
          <tbody>
            {items.map((ticket) => (
              <tr key={ticket.id}>
                <td>
                  <button
                    className="ticket-link"
                    onClick={() => onOpen(ticket)}
                  >
                    {ticket.request_id}
                  </button>
                </td>
                <td>
                  <button
                    className="content-link"
                    onClick={() => onOpen(ticket)}
                  >
                    {ticket.current_text}
                  </button>
                  {ticket.edit_requested && (
                    <span className="supplement-label">待补充</span>
                  )}
                  <span className="mobile-creator">创建者：{ticket.submitter_name}</span>
                </td>
                <td>{categories[ticket.category]}</td>
                <td>
                  <span className={"status " + ticket.status}>
                    {statuses[ticket.status]}
                  </span>
                </td>
                <td className="creator-cell">
                  <span className="creator-name" title={ticket.submitter_name}>{ticket.submitter_name}</span>
                  <span className="creator-account" title={ticket.submitter_username}>{ticket.submitter_username}</span>
                </td>
                <td className="time">{date(ticket.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && (
          <div className="empty">
            {loading ? (
              <LoaderCircle
                className="spinner"
                size={20}
                aria-label="正在读取工单"
              />
            ) : (
              "暂无工单"
            )}
            {!loading && (query || category || status) && (
              <button
                onClick={() => {
                  onQuery("");
                  onCategory("");
                  onStatus("");
                }}
              >
                清除筛选
              </button>
            )}
          </div>
        )}
      </div>
      <div className="pagination">
        <span>共 {total} 条</span>
        <div>
          <button
            aria-label="上一页"
            title="上一页"
            disabled={page <= 1 || loading}
            onClick={() => onPage(page - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <span className="page-number" aria-label={`第 ${page} 页`}>
            {page}
          </span>
          <button
            aria-label="下一页"
            title="下一页"
            disabled={page * 20 >= total || loading}
            onClick={() => onPage(page + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </>
  );
}
