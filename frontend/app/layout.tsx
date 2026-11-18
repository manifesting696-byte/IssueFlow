import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "IssueFlow · 内部问题登记",
  description: "员工反馈与技术支持工单工作台",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
