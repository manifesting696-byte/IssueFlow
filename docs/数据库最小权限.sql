-- 由 DBA 以迁移拥有者运行；先通过安全渠道创建 issueflow_runtime LOGIN 角色。
-- 不在本文件中写入生产密码。将应用 DATABASE_URL 指向该角色；迁移继续使用独立拥有者。
GRANT CONNECT ON DATABASE issueflow TO issueflow_runtime;
GRANT USAGE ON SCHEMA public TO issueflow_runtime;
GRANT SELECT ON users TO issueflow_runtime;
GRANT SELECT, INSERT ON tickets TO issueflow_runtime;
GRANT UPDATE (current_text, category, classification_source, status, edit_requested, version, updated_at) ON tickets TO issueflow_runtime;
GRANT SELECT, INSERT ON ticket_events, ticket_revisions TO issueflow_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO issueflow_runtime;
-- 不授予 DELETE、TRUNCATE、历史 UPDATE、Schema CREATE、角色管理或触发器管理权限。
