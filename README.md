# GitHub AI Daily

每天北京时间 09:30 独立扫描 GitHub 上的 AI Agent、Claude Skills、MCP、RAG 和 LLM 应用项目，保存 Star 快照并把中文日报发送到邮箱。

## GitHub Secrets

在仓库 `Settings → Secrets and variables → Actions` 中创建：

- `SMTP_USERNAME`：用于发信的 Gmail 地址
- `SMTP_APP_PASSWORD`：该 Gmail 账号的 16 位应用专用密码

收件地址已在工作流中设置为 `qwei02476@gmail.com`。

## 手动测试

打开 `Actions → GitHub AI Daily → Run workflow`。首次运行会建立快照；从第二天开始计算真实 Star 日增量。
