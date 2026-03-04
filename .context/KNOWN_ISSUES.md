# CLAWS 已知问题

## 活跃问题

### 1. Knot 平台 MCP 待配置

- **状态**: agents.yaml 已定义 mcp_deps，操作指南已写入 config/MCP_SETUP.md
- **待办**: 人工到 Knot 平台 Web UI 为 Scout/Analyst/Reviewer 配置 GitHub Remote MCP
- **URL**: `https://api.githubcopilot.com/mcp/` (免费托管，需 GitHub PAT)

## 已解决问题

### 2. config 目录双重来源 (2026-03-02 修复)

- docker-compose.yml 的 volume mount `./config:/app/config:ro` 在运行时覆盖 Dockerfile 的 COPY
- 修改 Prompt 后 `docker compose restart claws` 即可生效，无需重建镜像

### 3. memory 目录无清理机制 (2026-03-02 修复)

- 新增 cleanup_old_memory() 函数 + APScheduler 每日凌晨 3:00 定时清理
- 保留策略: 30 天（可通过 agents.yaml schedule.cleanup.retention_days 调整）
- 保护列表: DISCOVERIES.md, taste-changelog.md, weekly-digest.md, sessions.json 等永不清理

## 已解决问题

### 4. Scout Agent 输出不稳定 (2026-03-01 修复)

- claude-4.6-sonnet 偶尔会在 JSON 前后附加解释文本，需保留健壮解析
- 修复: extract_json 迁移到 json_repair 第三方包 + Prompt 格式约束加强
- 监控: ops_reporter 上报 json_parse_failed 事件
- v3 增强: Pipeline 状态机记录失败并支持自动重试

### 5. Evolve Agent 与 Runner 文件写入冲突 (2026-02-28 修复)

- 修复: Runner 是唯一文件写入者，Agent 只输出 JSON

### 6. 飞书推送格式不一致 (2026-03-01 修复)

- v2 问题: 5 个推送点各自拼接字符串，格式不统一，Markdown 语法在纯文本中不渲染
- v3 修复: 统一为 5 个纯文本模板函数 (_fmt_sense/_fmt_dive/_fmt_reflect/_fmt_review/_fmt_weekly)
- 所有推送改用 feishu_text，不再使用 feishu_card 的 interactive 模式

### 7. 推送无结构信息 (2026-03-01 修复)

- v2 问题: 周报直接截取 result["content"][:2000]，反思推送使用 push_parts 拼接
- v3 修复: 从 JSON 结构提取关键字段，使用标准化模板格式化

### 8. 飞书推送多层截断 (2026-03-02 修复)

- v3 问题: 三层截断导致飞书报告不完整 — _PUSH_MAX_LEN=2000 全局截断 + meta_observation[:200] 字段截断 + _truncate() 强制截尾
- 表现: 侦察报告趋势分析被截断、深度分析只显示前 800 字、反思报告 Evolve 内容被砍至 300 字
- 修复: 提升限额(4000) + 提升字段阈值(meta 600/dive 2000/evolve 600) + 移除 _truncate + 新增 _split_message 分段发送
