export type User = {
  id: number;
  username: string;
  display_name: string;
  role: "employee" | "support";
};
export type Ticket = {
  id: number;
  request_id: string;
  submitter_id: number;
  submitter_name: string;
  submitter_username: string;
  original_text: string;
  current_text: string;
  category: string;
  classification_source: string;
  status: string;
  edit_requested: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};
export type History = {
  events: {
    id: number;
    actor_id: number | null;
    event_type: string;
    detail: Record<string, unknown>;
    created_at: string;
  }[];
  revisions: {
    id: number;
    old_text: string;
    new_text: string;
    editor_id: number;
    created_at: string;
  }[];
};
export const categories: Record<string, string> = {
  system_fault: "系统故障",
  permission_request: "权限申请",
  feature_suggestion: "功能建议",
  usage_consultation: "使用咨询",
  uncertain: "待确认",
};
export const statuses: Record<string, string> = {
  pending: "待处理",
  in_progress: "处理中",
  completed: "已完成",
};
export const sources: Record<string, string> = {
  pending: "分类中",
  rule: "规则识别",
  llm: "模型识别",
  fallback: "已降级，待人工确认",
  manual: "人工确认",
};
export function date(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD"].includes(options.method)) {
    const csrf =
      document.cookie
        .split("; ")
        .find((c) => c.startsWith("issueflow_csrf="))
        ?.split("=")
        .slice(1)
        .join("=") || "";
    headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch("/api" + path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      body.code,
      body.message || "请求失败，请重试",
    );
  return body;
}
